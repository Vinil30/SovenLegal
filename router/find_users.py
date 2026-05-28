import json
from datetime import datetime

from bson import ObjectId
from flask import jsonify, redirect, render_template, session, url_for
from openai import OpenAI


def register_routes(app, context):
    db = context["db"]
    answers_col = context["answers_col"]
    queries = db["queries"]
    FAISS_INDEX_PATH = context["FAISS_INDEX_PATH"]
    OPENAI_API_KEY = context["OPENAI_API_KEY"]
    OPENAI_BASE_URL = context["OPENAI_BASE_URL"]
    OPENAI_MODEL = context["OPENAI_MODEL"]
    retriever_cache = {"retriever": None}

    def get_retriever():
        if retriever_cache["retriever"] is None:
            from langchain_community.embeddings import HuggingFaceEmbeddings
            from langchain_community.vectorstores import FAISS

            embedding_model = HuggingFaceEmbeddings(
                model_name="sentence-transformers/all-MiniLM-L6-v2"
            )
            vectorstore = FAISS.load_local(
                FAISS_INDEX_PATH,
                embedding_model,
                allow_dangerous_deserialization=True
            )
            retriever_cache["retriever"] = vectorstore.as_retriever(
                search_kwargs={"k": 6}
            )

        return retriever_cache["retriever"]


    @app.route("/find_users/<query_id>", methods=["GET"])
    def answer_query(query_id):
        if "user" not in session:
            return redirect(url_for("login"))

        user_id = session["user"]

        if not ObjectId.is_valid(query_id):
            return jsonify({"error": "Invalid query ID"}), 400

        try:
            #Check cache
            existing = answers_col.find_one({"query_id": query_id, "user_id": user_id})
            if existing:
                print(f"Cache hit for query_id: {query_id}")
                return render_template(
                    "findusers.html",
                    users=list(existing.get("result", {}).get("similar_queries", {}).values()),
                    query_id=query_id,
                    query=existing.get("result", {}).get("query", "")
                )

            # Fetch query text
            query_doc = queries.find_one({"_id": ObjectId(query_id), "user_id": user_id})
            if not query_doc:
                return jsonify({"error": "Query not found"}), 404

            query_text = query_doc["text"]
            print(f"Processing new query: {query_text}")

            # Retrieve docs
            try:
                retriever = get_retriever()
                docs = retriever.invoke(query_text)
                context = "\n".join([d.page_content for d in docs[:6]])
                print(f"Retrieved {len(docs)} documents from FAISS")
            except Exception as e:
                print(f"FAISS retrieval error: {str(e)}")
                return jsonify({"error": "Failed to retrieve similar documents"}), 500

            prompt = f"""
    You are a legal AI assistant that finds similar legal queries. 
    Based on the context provided, return the 6 most similar queries to the user's query.

    Return ONLY a valid JSON object with this exact structure:

    {{
      "similar_queries": {{
        "Query1": {{
          "OID": "string",
          "name": "string",
          "advocate": "string",
          "Query": "string",
          "state_of_resolvation": "Yes/No",
          "how_it_got_resolved": "string"
        }},
        "Query2": {{ ... }},
        "Query3": {{ ... }},
        "Query4": {{ ... }},
        "Query5": {{ ... }},
        "Query6": {{ ... }}
      }}
    }}

    Context (similar legal documents/queries): {context}

    User query: {query_text}

    ⚠️ IMPORTANT: 
    - Return only the JSON object, no additional text, no explanations. 
    - Replace `...` with actual data. 
    - Ensure valid JSON syntax.
    """

            try:
                client = OpenAI(
                    api_key=OPENAI_API_KEY,
                    base_url=OPENAI_BASE_URL
                )
                resp = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=0.2,
                    max_tokens=512
                )
                
                response = resp.choices[0].message.content.strip()

                start = response.find("{")
                end = response.rfind("}") + 1
                output = response[start:end]

                try:
                    data = json.loads(output)
                    print(data)
                except json.JSONDecodeError:
                    print("JSON parsing failed")
                    data = {"query": query_text, "similar_queries": {}}
            except Exception as e:
                print(f"LLM call failed: {str(e)}")
                return jsonify({"error": "AI call failed"}), 500

            # Save to cache
            try:
                answers_col.insert_one({
                    "query_id": query_id,
                    "user_id": user_id,
                    "result": data,
                    "created_at": datetime.utcnow()
                })
                print(f"Saved result to cache for query_id: {query_id}")
            except Exception as e:
                print(f"Database save error: {str(e)}")

            #Render
            return render_template(
                "findusers.html",
                users=list(data.get("similar_queries", {}).values()),
                query_id=query_id,
                query=query_text
            )

        except Exception as e:
            print(f"Unexpected error in answer_query: {str(e)}")
            return jsonify({"error": "An unexpected error occurred"}), 500
