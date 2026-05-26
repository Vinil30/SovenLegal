import os
import json
from dotenv import load_dotenv
from flask import Flask, render_template, request, jsonify, url_for, flash, session, redirect
from pymongo import MongoClient
from bson import ObjectId
from datetime import datetime, timedelta
from flask_bcrypt import Bcrypt
from utils.doc_scan import Image_Analyser
from dateutil import parser
from utils.query_analysis import Query_Analysis
from utils.generate_deadlines import GenerateDeadlines
from utils.generate_req_docs import Generate_Documents
import glob
from dotenv import load_dotenv
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from openai import OpenAI
from utils.doc_reference_generator import handle_document_reference_request
from utils.lawyer_deadlines import GenerateMilestones
from utils.verify_strategy import run_ai_verification
import ssl
import re
FAISS_INDEX_PATH = os.getenv("FAISS_INDEX_PATH", "faiss_index")
# Load environment variables
load_dotenv()

app = Flask(__name__)
app.secret_key = "supersecretkey123"

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
client = MongoClient(
    MONGO_URI,
    tls=True,
    tlsCAFile=ssl.get_default_verify_paths().cafile
)
db = client["soven_legal"]

# Collections
users = db["users"]
documents = db["documents"]
deadlines_col = db["deadlines"]
answers_col = db["find_users"]
lawyers = db["lawyers"]
bcrypt = Bcrypt(app)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
OPENAI_MODEL = os.getenv("OPENAI_MODEL")


#ROUTES

@app.route('/')
def home():
    return render_template("index.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        user = users.find_one({"email": email})
        if user:
            stored_password = user.get("password_hash")

            if stored_password and bcrypt.check_password_hash(stored_password, password):
                session["user"] = str(user["_id"])
                flash("Login successful!", "success")
                return redirect(url_for("user_dashboard"))

            flash("Invalid password", "danger")
            return redirect(url_for("login"))

        flash("Invalid email", "danger")
        return redirect(url_for("login"))

    return render_template("login.html")


@app.route('/signup')
def signup():
    return render_template("signup.html")


@app.route('/api/signup', methods=["POST"])
def api_signup():
    data = request.get_json()

    firstName = data.get("firstName")
    lastName = data.get("lastName")
    full_name = f"{firstName} {lastName}"
    email = data.get("email")
    password = data.get("password")
    phone = data.get("phone", None)

    if users.find_one({"email": email}):
        return jsonify({"success": False, "message": "Email already registered"})

    hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
    new_user = {
        "name": full_name,
        "email": email,
        "password_hash": hashed_pw,
        "phone": phone,
        "role": "user",
        "cases": [],
        "documents": [],
        "created_at": datetime.utcnow()
    }

    users.insert_one(new_user)
    return jsonify({"success": True, "redirect": "/dashboard"})


@app.route("/documents")
def documents_list():
    if "user" not in session:
        return redirect(url_for("login"))

    user_id = session["user"]
    docs = list(documents.find({"user_id": user_id}))
    for doc in docs:
        doc["id"] = str(doc["_id"])
        doc["scan_status"] = doc.get("scan_status", "pending")
        doc["scan_result"] = doc.get("scan_result", "Not scanned yet")


    user = users.find_one({"_id": ObjectId(user_id)})
    return render_template("documents.html",
        user={
            "name": user.get("name", "User"),
            "initials": user.get("name", "U")[0].upper()
        },
        uploaded_docs=docs,
        saved_queries=list(queries.find({"user_id": user_id}))
    )   


@app.route("/document/upload", methods=["POST"])
def upload_document():
    data = request.get_json()
    user_id = session.get("user")

    if not user_id:
        return jsonify({"error": "Unauthorized"}), 401

    doc = {
        "user_id": user_id,
        "name": data["name"],
        "base64_format": data["file"],
        "api_status": "not scanned yet",
        "scan_status": "pending",
        "uploaded_at": datetime.utcnow()
    }

    result = documents.insert_one(doc)
    return jsonify({
    "status": "success",
    "message": "Document uploaded",
    "id": str(result.inserted_id)
})


from utils.doc_scan import Image_Analyser
@app.route("/document/scan/<doc_id>", methods=["POST"])
def scan_document(doc_id):
    # Fetch document
    doc = documents.find_one({"_id": ObjectId(doc_id)})
    if not doc or "base64_format" not in doc:
        return jsonify({"error": "No image found for this document"}), 400

    base64_data = doc["base64_format"]
    query = doc.get("query", "General legal validation")
    doc_type = doc.get("doc_type", doc.get("name", "unknown"))
    
    user_id = doc.get("user_id")
    required_elements = []
    visual_reference = {}
    
    # Try to find the document requirements from user's queries
    if user_id:
        user_queries = queries.find({"user_id": user_id, "documents": {"$exists": True}})
        for user_query in user_queries:
            if "documents" in user_query:
                for doc_info in user_query["documents"]:
                    if isinstance(doc_info, dict) and doc_info.get("name", "").lower() in doc_type.lower():
                        required_elements = doc_info.get("required_elements", [])
                        visual_reference = doc_info.get("visual_reference", {})
                        break
                if required_elements:  # Found matching document requirements
                    break

    try:
        analyzer = Image_Analyser(
            query=query,
            doc_type=doc_type,
            base64_data=base64_data,
            required_elements=required_elements,
            visual_reference=visual_reference
        )
        result = analyzer.analyze_legal_doc()

        update_data = {
            "api_status": "scanned",
            "scan_status": "completed",
            "scan_result": result,
            "scanned_at": datetime.utcnow()
        }
        
        if result.get("overall_validity") == "valid":
            update_data["scan_summary"] = f"Document is valid. All required elements present."
        elif result.get("overall_validity") == "invalid":
            missing = result.get("required_elements_check", {}).get("missing_elements", [])
            update_data["scan_summary"] = f"Document is invalid. Missing: {', '.join(missing)}"
        else:
            update_data["scan_summary"] = result.get("detailed_analysis", "Analysis completed with issues.")

        documents.update_one(
            {"_id": ObjectId(doc_id)},
            {"$set": update_data}
        )

        return jsonify({
            "message": "Document scanned successfully!",
            "result": result,
            "summary": update_data["scan_summary"]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500
@app.route("/user/<user_id>/document_status", methods=["GET"])
def get_user_document_status(user_id):
    """
    Get comprehensive document status for a user including compliance
    """
    try:
        user_docs = documents.find({"user_id": user_id})
        doc_status = []
        
        for doc in user_docs:
            doc_info = {
                "id": str(doc["_id"]),
                "name": doc.get("name", "Unknown"),
                "uploaded_at": doc.get("uploaded_at"),
                "scan_status": doc.get("scan_status", "pending"),
                "overall_validity": "unknown"
            }
            
            if "scan_result" in doc and isinstance(doc["scan_result"], dict):
                scan_result = doc["scan_result"]
                doc_info.update({
                    "overall_validity": scan_result.get("overall_validity", "unknown"),
                    "authenticity_score": scan_result.get("authenticity_score", 0),
                    "required_elements_status": scan_result.get("required_elements_check", {}),
                    "quality_issues": scan_result.get("quality_assessment", {})
                })
            
            doc_status.append(doc_info)
        
        return jsonify({
            "status": "success",
            "documents": doc_status
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/document/requirements/<doc_name>", methods=["GET"])
def get_document_requirements(doc_name):
    """
    New endpoint to get document requirements and visual reference
    """
    try:
        temp_query = f"What are the requirements for {doc_name}?"
        generator = Generate_Documents(temp_query)
        doc_info = generator.call_api()
        
        for doc in doc_info.get("documents", []):
            if isinstance(doc, dict) and doc_name.lower() in doc.get("name", "").lower():
                return jsonify({
                    "status": "success",
                    "document": doc
                })
        
        return jsonify({
            "status": "error", 
            "message": "Document requirements not found"
        }), 404
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
    

    


@app.route("/document/delete/<doc_id>", methods=["DELETE"])
def delete_document(doc_id):
    documents.delete_one({"_id": ObjectId(doc_id)})
    return jsonify({"message": "Document deleted successfully!"})

deadlines = db["deadlines"]
queries = db["queries"]

# Dashboard route
@app.route("/dashboard")
def user_dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    user = users.find_one({"_id": ObjectId(session["user"])})
    user_id = str(user["_id"])

    # Manual Deadlines from deadlines collection
    user_deadlines = list(deadlines.find({"user_id": user_id}))
    manual_completed_tasks = sum(1 for d in user_deadlines if d.get("completed"))
    manual_pending_tasks = sum(1 for d in user_deadlines if not d.get("completed"))

    # AI-generated Deadlines from queries collection
    user_queries = list(queries.find({"user_id": user_id}))
    ai_completed_tasks = 0
    ai_pending_tasks = 0
    
    for query in user_queries:
        ai_deadlines = query.get("deadlines", [])
        for deadline in ai_deadlines:
            if deadline.get("completed"):
                ai_completed_tasks += 1
            else:
                ai_pending_tasks += 1

    # Total counts
    total_completed_tasks = manual_completed_tasks + ai_completed_tasks
    total_pending_tasks = manual_pending_tasks + ai_pending_tasks

    def format_date(val):
        if isinstance(val, datetime):
            return val.strftime("%Y-%m-%d")
        try:
            return parser.parse(val).strftime("%Y-%m-%d") 
        except Exception:
            return datetime.utcnow().strftime("%Y-%m-%d")

    return render_template(
        "dashboard.html",
        user={
            "name": user.get("name", "User"),
            "initials": user.get("name", "U")[0].upper()
        },
        completed_tasks=total_completed_tasks,
        pending_tasks=total_pending_tasks,
        
        manual_completed=manual_completed_tasks,
        manual_pending=manual_pending_tasks,
        ai_completed=ai_completed_tasks,
        ai_pending=ai_pending_tasks,

        # Manual Deadlines for frontend
        deadlines=[
            {
                "id": str(d["_id"]),
                "title": d.get("title") or d.get("task", "Untitled Task"),
                "date": format_date(d.get("date") or d.get("due_date")),
                "completed": d.get("completed", False),
                "type": "manual" 
            }
            for d in user_deadlines
        ],

        # Queries with AI deadlines for frontend
        saved_queries=[
            {
                "id": str(q["_id"]),
                "text": q["text"],
                "scan_status": q.get("scan_status", False),
                "scan_result": q.get("scan_result"),
                "date": format_date(q.get("created_at")),
                "documents": q.get("documents", []),
                "deadlines": [
                    {
                        **dl,
                        "type": "ai"  
                    }
                    for dl in q.get("deadlines", [])
                ]
            }
            for q in user_queries
        ],
    )


# DEADLINE ROUTES 
# Route to toggle AI deadline completion status
@app.route("/toggle_ai_deadline/<query_id>/<deadline_id>", methods=["POST"])
def toggle_ai_deadline(query_id, deadline_id):
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 403

    user_id = session["user"]
    completed = request.json.get("completed", False)

    try:
        result = queries.update_one(
            {
                "_id": ObjectId(query_id), 
                "user_id": user_id, 
                "deadlines.id": deadline_id
            },
            {
                "$set": {"deadlines.$.completed": completed}
            }
        )

        if result.matched_count == 0:
            return jsonify({
                "success": False, 
                "message": "Query or deadline not found"
            }), 404

        return jsonify({
            "success": True, 
            "message": f"Deadline marked as {'completed' if completed else 'pending'}"
        })

    except Exception as e:
        return jsonify({
            "success": False, 
            "message": f"Error updating deadline: {str(e)}"
        }), 500


# Route to get AI deadlines for a specific query (for debugging)
@app.route("/get_ai_deadlines/<query_id>", methods=["GET"])
def get_ai_deadlines(query_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 403

    user_id = session["user"]
    
    try:
        query = queries.find_one({
            "_id": ObjectId(query_id), 
            "user_id": user_id
        })
        
        if not query:
            return jsonify({"error": "Query not found"}), 404

        deadlines = query.get("deadlines", [])
        return jsonify({
            "success": True,
            "query_text": query.get("text"),
            "deadlines": deadlines
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/deadline/add", methods=["POST"])
def add_deadline():
    if "user" not in session: return jsonify({"error": "Unauthorized"}), 401
    data = request.json
    new_deadline = {
        "user_id": session["user"],
        "title": data["title"],
        "date": data["date"],
        "completed": False
    }
    deadlines.insert_one(new_deadline)
    return jsonify({"message": "Deadline added!"})

@app.route("/deadline/update/<id>", methods=["POST"])
def update_deadline(id):
    data = request.json
    deadlines.update_one({"_id": ObjectId(id)}, {"$set": {"completed": data["completed"]}})
    return jsonify({"message": "Deadline updated!"})

@app.route("/deadline/edit/<id>", methods=["POST"])
def edit_deadline(id):
    data = request.json
    deadlines.update_one({"_id": ObjectId(id)}, {"$set": {"title": data["title"]}})
    return jsonify({"message": "Deadline edited!"})

@app.route("/deadline/delete/<id>", methods=["DELETE"])
def delete_deadline(id):
    deadlines.delete_one({"_id": ObjectId(id)})
    return jsonify({"message": "Deadline deleted!"})

#  QUERY ROUTES 
@app.route("/save_query", methods=["POST"])
def save_query():
    if "user" not in session: 
        return jsonify({"error": "Unauthorized"}), 401

    query_text = request.json.get("query", "").strip()
    if not query_text:
        return jsonify({"error": "Query cannot be empty"}), 400

    query_doc = {
        "user_id": session["user"],
        "text": query_text,
        "scan_status": False,
        "scan_result": None,
        "created_at": datetime.utcnow(),
        "deadlines": [],  
        "documents": []  
    }

    queries.insert_one(query_doc)
    return jsonify({"message": "Query saved!"}), 201



@app.route("/analyse_query", methods=["POST"])
def analyse_query():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    try:
        data = request.get_json()
        query_text = data.get("query")

        if not query_text:
            return jsonify({"error": "No query provided"}), 400

        qa = Query_Analysis(query_text)
        result = qa.call_api()

        if "status" not in result:
            return jsonify({"error": "Analysis failed"}), 500

        user_id = session["user"]

        update_data = {
            "scan_status": True,
            "scan_result": result.get("message", "Unknown"),
            "deadlines": result.get("deadlines", []),
            "documents": result.get("documents", [])
        }

        queries.update_one(
            {"user_id": user_id, "text": query_text},
            {"$set": update_data}
        )

        return jsonify({"message": "Analysis complete", "result": result})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    
    
@app.route("/generate_deadlines/<query_id>", methods=["POST"])
def generate_deadlines(query_id):
    print(f"=== GENERATE DEADLINES DEBUG ===")
    print(f"Query ID received: {query_id}")
    
    try:
        #Find query
        query = queries.find_one({"_id": ObjectId(query_id)})
        if not query:
            print("ERROR: Query not found in database")
            return jsonify({"status": "error", "message": "Query not found"}), 404
        
        query_text = query.get("text", "")
        print(f"Query found: {query_text}")
        
        # Call AI deadline generator
        print("Calling GenerateDeadlines API...")
        deadlines_generator = GenerateDeadlines(query_text)
        deadlines_data = deadlines_generator.call_api()
        print(f"AI Response: {deadlines_data}")
        
        # Check for AI failure and provide fallback
        ai_deadlines = deadlines_data.get("deadlines", [])
        
        if not ai_deadlines:
            print("AI failed to generate deadlines, using fallback...")
            fallback_deadlines = generate_fallback_deadlines(query_text)
            deadlines_data = {"deadlines": fallback_deadlines}
            print(f"Fallback deadlines: {fallback_deadlines}")
        
        # Process deadlines
        processed_deadlines = []
        raw_deadlines = deadlines_data.get("deadlines", [])
        
        for dl in raw_deadlines:
            print(f"Processing deadline: {dl}")
            
            task = dl.get("task", "").strip()
            due_date = dl.get("due_date", "").strip()
            
            if not task or not due_date:
                print(f"Skipping invalid deadline: task='{task}', due_date='{due_date}'")
                continue

            deadline_obj = {
                "id": str(ObjectId()),
                "task": task,
                "due_date": due_date,
                "completed": dl.get("completed", False)
            }
            processed_deadlines.append(deadline_obj)
            print(f"Added processed deadline: {deadline_obj}")
        
        print(f"Total processed deadlines: {len(processed_deadlines)}")
        
        #Update database
        if processed_deadlines:
            update_result = queries.update_one(
                {"_id": ObjectId(query_id)},
                {"$set": {"deadlines": processed_deadlines}}
            )
            print(f"Database update - matched: {update_result.matched_count}, modified: {update_result.modified_count}")
            
            # Verify the update
            updated_query = queries.find_one({"_id": ObjectId(query_id)})
            saved_deadlines = updated_query.get("deadlines", [])
            print(f"Verification - deadlines in DB: {len(saved_deadlines)}")
            
            return jsonify({"status": "success", "deadlines": processed_deadlines})
        else:
            print("No valid deadlines generated")
            return jsonify({"status": "error", "message": "Could not generate any valid deadlines"})
        
    except Exception as e:
        print(f"EXCEPTION in generate_deadlines: {str(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        return jsonify({"status": "error", "message": str(e)}), 500


def generate_fallback_deadlines(query_text):
    """Generate fallback deadlines when AI fails"""
    from datetime import datetime, timedelta
    
    query_lower = query_text.lower()

    base_date = datetime.now() + timedelta(days=14)
    
    if any(keyword in query_lower for keyword in ['dispute', 'conflict', 'disagreement', 'land', 'property']):
        return [
            {"task": "File initial petition", "due_date": (base_date).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Gather supporting documents", "due_date": (base_date + timedelta(days=7)).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Schedule mediation", "due_date": (base_date + timedelta(days=21)).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Prepare for court hearing", "due_date": (base_date + timedelta(days=45)).strftime("%Y-%m-%d"), "completed": False}
        ]
    elif any(keyword in query_lower for keyword in ['contract', 'agreement', 'breach']):
        return [
            {"task": "Review contract terms", "due_date": (base_date).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Send legal notice", "due_date": (base_date + timedelta(days=10)).strftime("%Y-%m-%d"), "completed": False},
            {"task": "File breach of contract suit", "due_date": (base_date + timedelta(days=30)).strftime("%Y-%m-%d"), "completed": False}
        ]
    elif any(keyword in query_lower for keyword in ['divorce', 'custody', 'marriage', 'family']):
        return [
            {"task": "File divorce petition", "due_date": (base_date).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Financial disclosure", "due_date": (base_date + timedelta(days=21)).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Child custody arrangement", "due_date": (base_date + timedelta(days=35)).strftime("%Y-%m-%d"), "completed": False}
        ]
    else:
        return [
            {"task": "Initial consultation with lawyer", "due_date": (base_date).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Collect relevant documents", "due_date": (base_date + timedelta(days=7)).strftime("%Y-%m-%d"), "completed": False},
            {"task": "File preliminary application", "due_date": (base_date + timedelta(days=21)).strftime("%Y-%m-%d"), "completed": False},
            {"task": "Prepare for next legal step", "due_date": (base_date + timedelta(days=30)).strftime("%Y-%m-%d"), "completed": False}
        ]

@app.route('/api/queries', methods=['GET'])
def get_queries():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user"]
    
    try:
        user_queries = list(queries.find({"user_id": user_id}))
        
        formatted_queries = []
        for query in user_queries:
            formatted_queries.append({
                "id": str(query["_id"]),
                "title": query.get("text", "")[:50] + "..." if len(query.get("text", "")) > 50 else query.get("text", ""),
                "query": query.get("text", ""),
                "scan_status": query.get("scan_status", False),
                "documents": query.get("documents", []),
                "deadlines": query.get("deadlines", []),
                "created_at": query.get("created_at")
            })
        
        return jsonify({"queries": formatted_queries})
        
    except Exception as e:
        print(f"Error getting queries: {str(e)}")
        return jsonify({"error": "Failed to retrieve queries"}), 500

#route to get a specific query
@app.route('/api/query/<query_id>', methods=['GET'])
def get_single_query(query_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user"]
    
    try:
        query = queries.find_one({"_id": ObjectId(query_id), "user_id": user_id})
        
        if not query:
            return jsonify({"error": "Query not found"}), 404
        
        return jsonify({
            "id": str(query["_id"]),
            "text": query.get("text", ""),
            "documents": query.get("documents", []),
            "deadlines": query.get("deadlines", []),
            "scan_status": query.get("scan_status", False),
            "scan_result": query.get("scan_result")
        })
        
    except Exception as e:
        print(f"Error getting query: {str(e)}")
        return jsonify({"error": "Failed to retrieve query"}), 500

@app.route("/generate_documents/<query_id>", methods=["POST"])
def generate_documents(query_id):
    query = queries.find_one({"_id": ObjectId(query_id)})
    if not query:
        return jsonify({"status": "error", "message": "Query not found"}), 404

    try:
        generator = Generate_Documents(query["text"])
        documents_data = generator.call_api()

        if "error" in str(documents_data):
            return jsonify({"status": "error", "message": "Failed to generate documents"}), 400

        queries.update_one(
            {"_id": ObjectId(query_id)},
            {"$set": {
                "documents": documents_data.get("documents", []),
                "documents_generated_at": datetime.utcnow()
            }}
        )

        return jsonify({
            "status": "success", 
            "documents": documents_data.get("documents", [])
        })
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


# Serve Lawyers Page (HTML)
@app.route("/lawyers")
def lawyers_page():
    user = None
    if "user" in session:
        user = users.find_one({"_id": ObjectId(session["user"])})
        user = {"name": user.get("name", "User")}
    return render_template("lawyer-page.html", user=user)

@app.route("/api/lawyer/<lawyer_id>")
def lawyer_detail_api(lawyer_id):
    lawyer = None
    try:
        lawyer = db.lawyers.find_one({"_id": ObjectId(lawyer_id)})
    except Exception:
        lawyer = db.lawyers.find_one({"_id": lawyer_id})

    if not lawyer:
        return jsonify({"error": "Lawyer not found"}), 404

    lawyer["_id"] = str(lawyer["_id"])
    return jsonify(lawyer)

@app.route("/api/lawyers")
def get_lawyers():
    lawyers = list(db.lawyers.find({}))
    for lawyer in lawyers:
        lawyer["_id"] = str(lawyer["_id"])  
    return jsonify(lawyers)


from bson.json_util import dumps

# Route to serve legal aid page
@app.route("/legal-aid")
def legal_aid():
    non_profits = list(db.non_profits.find({}))
    return render_template("legal_aid.html", non_profits=non_profits)

# API endpoint to get non-profits 
@app.route("/api/non-profits")
def api_non_profits():
    non_profits = list(db.non_profits.find({}))
    for org in non_profits:
        org["_id"] = str(org["_id"])
    return jsonify(non_profits)

chats = db["chats"]

#route for chat with lawyer
@app.route("/chatwithlawyer/<lawyer_id>")
def chat_with_lawyer(lawyer_id):
    if "user" not in session:
        return redirect(url_for("login"))

    user_id = session["user"]

    chat = chats.find_one({"user_id": user_id, "lawyer_id": lawyer_id})

    if not chat:
        chat = {
            "user_id": user_id,
            "lawyer_id": lawyer_id,
            "created_at": datetime.utcnow(),
            "messages": []
        }
        result = chats.insert_one(chat)
        chat["_id"] = str(result.inserted_id)
    else:
        chat["_id"] = str(chat["_id"])

   
    lawyer = db.lawyers.find_one({"_id": ObjectId(lawyer_id)})
    if not lawyer:
        return "Lawyer not found", 404
    lawyer["_id"] = str(lawyer["_id"])

    user = users.find_one({"_id": ObjectId(user_id)})
    user["_id"] = str(user["_id"])

    return render_template("chat_interface.html", chat=chat, lawyer=lawyer, user=user)


@app.route("/chat/start", methods=["POST"])
def start_chat():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.json
    lawyer_id = data.get("lawyer_id")

    chat = chats.find_one({"user_id": session["user"], "lawyer_id": lawyer_id})
    if chat:
        return jsonify({"chat_id": str(chat["_id"])})  

    chat = {
        "user_id": session["user"],
        "lawyer_id": lawyer_id,
        "created_at": datetime.utcnow(),
        "messages": []
    }
    result = chats.insert_one(chat)
    return jsonify({"chat_id": str(result.inserted_id)})


# Fetching chat history
@app.route("/chat/<chat_id>")
def get_chat(chat_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    chat = chats.find_one({"_id": ObjectId(chat_id)})
    if not chat:
        return jsonify({"error": "Chat not found"}), 404
    
    chat["_id"] = str(chat["_id"])
    return jsonify(chat)

# Route to get all chats for a user
@app.route("/api/chats")
def get_user_chats():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user"]
    user_chats = list(chats.find({"user_id": user_id}))
    
    chat_list = []
    for chat in user_chats:
        lawyer_id = chat["lawyer_id"]
        lawyer = db.lawyers.find_one({"_id": ObjectId(lawyer_id)})
        
        if lawyer:
            last_message = chat["messages"][-1] if chat["messages"] else None
            
            chat_list.append({
                "chat_id": str(chat["_id"]),
                "lawyer_id": lawyer_id,
                "lawyer_name": lawyer.get("name", "Lawyer"),
                "lawyer_specialization": lawyer.get("specialization", "General"),
                "last_message": last_message["message"] if last_message else "No messages yet",
                "last_message_time": last_message["timestamp"] if last_message else chat["created_at"],
                "unread_count": sum(1 for msg in chat["messages"] if msg.get("sender") == "lawyer" and not msg.get("read", False))
            })
    
    chat_list.sort(key=lambda x: x["last_message_time"], reverse=True)
    
    return jsonify({"chats": chat_list})


@app.route("/chat/<chat_id>/read", methods=["POST"])
def mark_messages_as_read(chat_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"messages.$[elem].read": True}},
        array_filters=[{"elem.sender": "lawyer", "elem.read": {"$ne": True}}]
    )
    
    return jsonify({"status": "ok"})



from utils.chat_with_lawyer import ChatWithLawyer

#route to get user progress data
@app.route("/api/user-progress/<user_id>")
def get_user_progress(user_id):
    if "user" not in session or session["user"] != user_id:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        user_queries = list(queries.find({"user_id": user_id}))
        user_docs = list(documents.find({"user_id": user_id}))
        user_deadlines = list(deadlines.find({"user_id": user_id}))
        
        progress_data = {
            "queries_analyzed": len([q for q in user_queries if q.get("scan_status")]),
            "total_queries": len(user_queries),
            "documents_scanned": len([d for d in user_docs if d.get("scan_status") == "completed"]),
            "total_documents": len(user_docs),
            "deadlines_completed": len([d for d in user_deadlines if d.get("completed")]),
            "total_deadlines": len(user_deadlines),
            "ai_deadlines_completed": 0,
            "total_ai_deadlines": 0
        }
        
        for query in user_queries:
            ai_deadlines = query.get("deadlines", [])
            progress_data["total_ai_deadlines"] += len(ai_deadlines)
            progress_data["ai_deadlines_completed"] += len([d for d in ai_deadlines if d.get("completed")])
        
        # Calculate overall completion percentage
        total_tasks = (progress_data["total_queries"] + progress_data["total_documents"] + 
                      progress_data["total_deadlines"] + progress_data["total_ai_deadlines"])
        completed_tasks = (progress_data["queries_analyzed"] + progress_data["documents_scanned"] + 
                          progress_data["deadlines_completed"] + progress_data["ai_deadlines_completed"])
        
        progress_data["overall_completion"] = (completed_tasks / total_tasks * 100) if total_tasks > 0 else 0
        
        return jsonify({"success": True, "progress": progress_data})
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# route to generate AI assistance for chat
@app.route("/chat/<chat_id>/ai-assist", methods=["POST"])
def generate_chat_assistance(chat_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        user_id = session["user"]
        print(f"=== [DEBUG] User ID: {user_id}, Chat ID: {chat_id} ===")

        # Get chat history
        chat = chats.find_one({"_id": ObjectId(chat_id), "user_id": user_id})
        if not chat:
            print("=== [DEBUG] Chat not found ===")
            return jsonify({"error": "Chat not found"}), 404
        print(f"=== [DEBUG] Loaded Chat with {len(chat.get('messages', []))} messages ===")

        # Get user's main legal query
        user_queries = list(
            queries.find({"user_id": user_id, "scan_status": True}).sort("created_at", -1)
        )
        main_query = user_queries[0]["text"] if user_queries else "General legal consultation"
        print(f"=== [DEBUG] Main Query: {main_query[:100]} ===")

        # Get user progress
        progress_response = get_user_progress(user_id)
        print(f"=== [DEBUG] Progress Response Status: {progress_response.status_code} ===")
        progress_data = (
            progress_response.get_json().get("progress", {})
            if progress_response.status_code == 200
            else {}
        )
        print(f"=== [DEBUG] Progress Data: {progress_data} ===")

        # Format chat history
        chat_history = []
        for msg in chat.get("messages", []):
            sender = "User" if msg["sender"] == "user" else "Lawyer"
            chat_history.append(f"{sender}: {msg['message']}")
        chat_till_now = "\n".join(chat_history[-10:])
        print("=== [DEBUG] Last 10 Messages for Context ===")
        print(chat_till_now)

        overall_completion = progress_data.get('overall_completion', 0)
        try:
            overall_completion = float(overall_completion)
        except (ValueError, TypeError):
            overall_completion = 0.0

        user_progress = f"""
        Query Analysis: {progress_data.get('queries_analyzed', 0)}/{progress_data.get('total_queries', 0)} completed
        Documents Processed: {progress_data.get('documents_scanned', 0)}/{progress_data.get('total_documents', 0)} completed
        Deadlines Managed: {progress_data.get('deadlines_completed', 0)}/{progress_data.get('total_deadlines', 0)} completed
        AI Tasks Completed: {progress_data.get('ai_deadlines_completed', 0)}/{progress_data.get('total_ai_deadlines', 0)} completed
        Overall Progress: {overall_completion:.1f}% complete
        """

        print("=== [DEBUG] User Progress String Built ===")

        # Generate AI assistance
        chat_assistant = ChatWithLawyer(
            query=main_query,
            user_progress=user_progress,
            chat_till_now=chat_till_now
        )
        print("=== [DEBUG] ChatWithLawyer Initialized ===")

        response = chat_assistant.generate_response()
        print(f"=== [DEBUG] AI Response: {response} ===")

        return jsonify({
            "success": True,
            "suggested_message": response.get("assistant_reply", ""),
            "context": {
                "main_query": main_query,
                "progress_percentage": progress_data.get('overall_completion', 0),
                "recent_messages": len(chat.get("messages", []))
            }
        })

    except Exception as e:
        import traceback
        print("=== [ERROR] Exception in /chat/<chat_id>/ai-assist ===")
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/chat/<chat_id>/send", methods=["POST"])
def send_message(chat_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    sender = request.json.get("sender", "user")
    message = request.json.get("message")
    is_ai_assisted = request.json.get("ai_assisted", False)

    if not message:
        return jsonify({"error": "Empty message"}), 400

    message_data = {
        "sender": sender,
        "message": message,
        "timestamp": datetime.utcnow(),
        "ai_assisted": is_ai_assisted 
    }

    chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$push": {"messages": message_data}}
    )
    
    return jsonify({"status": "ok"})


@app.route("/chat-interface")
def chat_interface():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user = users.find_one({"_id": ObjectId(session["user"])})
    return render_template("chat_interface.html", user=user)


embedding_model = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")
vectorstore = FAISS.load_local("faiss_index", embedding_model, allow_dangerous_deserialization=True)
retriever = FAISS.load_local("faiss_index", embedding_model, allow_dangerous_deserialization=True).as_retriever(search_kwargs={"k": 6})


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

@app.route('/lawyer-signup')
def lawyer_signup():
    """Render the lawyer signup page"""
    return render_template("lawyer_signup.html")

@app.route('/api/lawyer-signup', methods=["POST"])
def api_lawyer_signup():
    """Handle lawyer registration form submission"""
    try:
        data = request.get_json()
        
        name = data.get("name")
        email = data.get("email")
        password = data.get("password")
        phone = data.get("phone")
        
       
        specialization = data.get("specialization", []) 
        if isinstance(specialization, str):
            specialization = [specialization] 
        
        experience = data.get("experience")
        bar_number = data.get("barNumber")
        location = data.get("location")
     
        fee = data.get("fee")
        currency = data.get("currency", "USD")
        bio = data.get("bio")
        
        previous_works = []
        
       
        work_title_1 = data.get("work_title_1")
        work_desc_1 = data.get("work_desc_1")
        if work_title_1 and work_desc_1:
            previous_works.append({
                "title": work_title_1,
                "description": work_desc_1
            })
        
        work_title_2 = data.get("work_title_2")
        work_desc_2 = data.get("work_desc_2")
        if work_title_2 and work_desc_2:
            previous_works.append({
                "title": work_title_2,
                "description": work_desc_2
            })
        
        
        required_fields = [name, email, password, phone, experience, bar_number, location, fee, bio]
        if not all(required_fields):
            return jsonify({
                "success": False, 
                "message": "All required fields must be filled"
            }), 400
        
        if not specialization:
            return jsonify({
                "success": False, 
                "message": "At least one specialization must be selected"
            }), 400
        
        if db.lawyers.find_one({"email": email}):
            return jsonify({
                "success": False, 
                "message": "Email already registered as a lawyer"
            }), 409
        
        if users.find_one({"email": email}):
            return jsonify({
                "success": False, 
                "message": "Email already registered in the system"
            }), 409
        
        # Hash password
        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")
        
     
        new_lawyer = {
            "name": name,
            "email": email,
            "password_hash": password_hash,
            "phone": phone,
            "role": "lawyer",
            "specialization": specialization,
            "experience": int(experience),
            "bar_number": bar_number,
            "location": location,
            "fee": int(fee),
            "currency": currency,
            "bio": bio,
            "previous_works": previous_works,
            "created_at": datetime.utcnow(),
            "status": "pending", 
            "verified": False
        }
        
     
        result = db.lawyers.insert_one(new_lawyer)
        print("Inserted lawyer:", result.inserted_id)

        
        return jsonify({
            "success": True,
            "message": "Lawyer registration submitted successfully! Your account is under review.",
            "lawyer_id": str(result.inserted_id)
        })
        
    except ValueError as e:
        return jsonify({
            "success": False,
            "message": "Invalid input format. Please check your data."
        }), 400
        
    except Exception as e:
        print(f"Error in lawyer signup: {str(e)}")
        return jsonify({
            "success": False,
            "message": "An error occurred during registration. Please try again."
        }), 500


@app.route('/lawyer-login', methods=["POST"])
def lawyer_login_post():
    """Handle lawyer login"""
    try:
        data = request.get_json() if request.is_json else request.form
        
        email = data.get("email")
        password = data.get("password")
        
        if not email or not password:
            return jsonify({
                "success": False,
                "message": "Email and password are required"
            }), 400
        
        # Find lawyer by email
        lawyer = db.lawyers.find_one({"email": email})
        
        if not lawyer:
            return jsonify({
                "success": False,
                "message": "Invalid email or password"
            }), 401
        
        # Check password
        if not bcrypt.check_password_hash(lawyer.get("password_hash", ""), password):
            return jsonify({
                "success": False,
                "message": "Invalid email or password"
            }), 401
        
        # Check if lawyer is approved
        if lawyer.get("status") != "approved":
            return jsonify({
                "success": False,
                "message": "Your account is still under review. Please wait for approval."
            }), 403
        
        # Create session
        session["lawyer"] = str(lawyer["_id"])
        session["user_type"] = "lawyer"
        
        return jsonify({
            "success": True,
            "message": "Login successful",
            "redirect": "/lawyer-dashboard"
        })
        
    except Exception as e:
        print(f"Error in lawyer login: {str(e)}")
        return jsonify({
            "success": False,
            "message": "An error occurred during login. Please try again."
        }), 500



@app.route('/lawyer-login')
def lawyer_login():
    """Render the lawyer login page"""
    return render_template("lawyer_login.html")

@app.route('/api/lawyer-login', methods=["POST"])
def api_lawyer_login():
    """Handle lawyer login form submission"""
    try:
        data = request.get_json()
        
        email = data.get("email")
        password = data.get("password")
        remember_me = data.get("remember", False)
        
        # Validation
        if not email or not password:
            return jsonify({
                "success": False,
                "message": "Email and password are required"
            }), 400
        
        # Find lawyer by email
        lawyer = db.lawyers.find_one({"email": email})
        
        if not lawyer:
            return jsonify({
                "success": False,
                "message": "Invalid email or password"
            }), 401
        
        # Check password
        if not bcrypt.check_password_hash(lawyer.get("password_hash", ""), password):
            return jsonify({
                "success": False,
                "message": "Invalid email or password"
            }), 401
        
        # Check if lawyer account is approved
        if lawyer.get("status", "pending") != "approved":
            status = lawyer.get("status", "pending")
            if status == "pending":
                message = "Your account is still under review. Please wait for approval."
            elif status == "rejected":
                message = "Your account has been rejected. Please contact support."
            else:
                message = "Your account is not active. Please contact support."
                
            return jsonify({
                "success": False,
                "message": message
            }), 403
        
        # Create session
        session["lawyer"] = str(lawyer["_id"])
        session["user_type"] = "lawyer"
        session["lawyer_name"] = lawyer.get("name", "Lawyer")
        
        if remember_me:
            session.permanent = True
        
        # Update last login
        db.lawyers.update_one(
            {"_id": lawyer["_id"]},
            {"$set": {"last_login": datetime.utcnow()}}
        )
        
        return jsonify({
            "success": True,
            "message": "Login successful",
            "redirect": "/lawyer-dashboard",
            "lawyer": {
                "name": lawyer.get("name"),
                "email": lawyer.get("email"),
                "specialization": lawyer.get("specialization", [])
            }
        })
        
    except Exception as e:
        print(f"Error in lawyer login: {str(e)}")
        return jsonify({
            "success": False,
            "message": "An error occurred during login. Please try again."
        }), 500

@app.route("/lawyer-dashboard")
def lawyer_dashboard():
    if "lawyer" not in session:
        return redirect(url_for("login"))
    
    lawyer_id = session["lawyer"]

    # Get lawyer info
    lawyer = db.lawyers.find_one({"_id": ObjectId(lawyer_id)})
    if not lawyer:
        flash("Lawyer not found", "error")
        return redirect(url_for("login"))

    # Get all hires for this lawyer
    hires = list(hired_lawyers.find({"lawyer_id": lawyer_id}))

    # Stats
    active_cases = len([h for h in hires if h.get("status") == "active"])
    completed_cases = len([h for h in hires if h.get("status") == "completed"])
    total_earnings = sum(h.get("agreed_fee", 0) for h in hires)
    avg_rating = round(sum(h.get("rating", 0) for h in hires) / len(hires), 2) if hires else 0

    stats = {
        "active_cases": active_cases,
        "completed_cases": completed_cases,
        "total_earnings": total_earnings,
        "avg_rating": avg_rating
    }

    recent_cases = []
    for h in hires[-5:]:
        user = db.users.find_one({"_id": ObjectId(h["user_id"])})
        recent_cases.append({
            "_id": str(h["_id"]),
            "client_name": user.get("name", "Unknown Client"),
            "case_title": h.get("case_title", ""),
            "progress": h.get("progress", 0)
        })

    milestone_ids = [h["_id"] for h in hires]
    upcoming_milestones = list(case_milestones.find({
        "hired_lawyer_id": {"$in": milestone_ids},
        "status": {"$ne": "completed"}
    }).sort("due_date", 1).limit(5))


    for m in upcoming_milestones:
        hired_case = hired_lawyers.find_one({"_id": m["hired_lawyer_id"]})
        if hired_case:
            user = db.users.find_one({"_id": ObjectId(hired_case["user_id"])})
            m["client_name"] = user.get("name", "Unknown Client")

    return render_template("lawyer_dashboard.html",
                           lawyer=lawyer,
                           stats=stats,
                           recent_cases=recent_cases,
                           upcoming_milestones=upcoming_milestones)


@app.route('/lawyer-logout')
def lawyer_logout():
    """Logout lawyer"""
    session.pop("lawyer", None)
    session.pop("user_type", None)
    session.pop("lawyer_name", None)
    
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("lawyer_login"))

@app.route('/api/lawyer-profile')
def get_lawyer_profile():
    """Get current logged-in lawyer's profile"""
    if "lawyer" not in session or session.get("user_type") != "lawyer":
        return jsonify({"error": "Unauthorized"}), 401
    
    lawyer_id = session["lawyer"]
    
    try:
        lawyer = db.lawyers.find_one({"_id": ObjectId(lawyer_id)})
        
        if not lawyer:
            return jsonify({"error": "Lawyer not found"}), 404
        
        # Remove sensitive information
        lawyer_profile = {
            "id": str(lawyer["_id"]),
            "name": lawyer.get("name"),
            "email": lawyer.get("email"),
            "phone": lawyer.get("phone"),
            "specialization": lawyer.get("specialization", []),
            "experience": lawyer.get("experience", 0),
            "bar_number": lawyer.get("bar_number"),
            "location": lawyer.get("location"),
            "fee": lawyer.get("fee", 0),
            "currency": lawyer.get("currency", "USD"),
            "bio": lawyer.get("bio"),
            "previous_works": lawyer.get("previous_works", []),
            "status": lawyer.get("status"),
            "verified": lawyer.get("verified", False),
            "created_at": lawyer.get("created_at"),
            "last_login": lawyer.get("last_login")
        }
        
        return jsonify({
            "success": True,
            "profile": lawyer_profile
        })
        
    except Exception as e:
        print(f"Error getting lawyer profile: {str(e)}")
        return jsonify({"error": "Failed to retrieve profile"}), 500

@app.route('/api/lawyer-stats')
def get_lawyer_stats():
    """Get lawyer dashboard statistics"""
    if "lawyer" not in session or session.get("user_type") != "lawyer":
        return jsonify({"error": "Unauthorized"}), 401
    
    lawyer_id = session["lawyer"]
    
    try:
        lawyer_chats = list(chats.find({"lawyer_id": lawyer_id}))
        
        # Calculate statistics
        stats = {
            "total_chats": len(lawyer_chats),
            "active_chats": len([chat for chat in lawyer_chats if chat.get("messages")]),
            "total_messages": sum(len(chat.get("messages", [])) for chat in lawyer_chats),
            "unread_messages": 0
        }
        
        for chat in lawyer_chats:
            for message in chat.get("messages", []):
                if message.get("sender") == "user" and not message.get("read", False):
                    stats["unread_messages"] += 1
        
        return jsonify({
            "success": True,
            "stats": stats
        })
        
    except Exception as e:
        print(f"Error getting lawyer stats: {str(e)}")
        return jsonify({"error": "Failed to retrieve statistics"}), 500
    
   
import base64
import mimetypes
case_files = db["case_files"]

@app.route("/upload-case-file")
def upload_case_file_page():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user = users.find_one({"_id": ObjectId(session["user"])})
    return render_template("upload_case_file.html", 
                         user={"name": user.get("name", "User")})

@app.route("/api/upload-case-file", methods=["POST"])
def upload_case_file():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    try:
        data = request.get_json()
        user_id = session["user"]
        
        # Validate required fields
        required_fields = ['file_name', 'original_name', 'file_type', 'file_size', 'base64_data', 'file_category']
        for field in required_fields:
            if not data.get(field):
                return jsonify({"success": False, "message": f"Missing {field}"}), 400
        
        max_size = 10 * 1024 * 1024  
        if data['file_size'] > max_size:
            return jsonify({"success": False, "message": "File size too large. Maximum 10MB allowed."}), 400
        
        # Validate file type
        allowed_extensions = ['pdf', 'doc', 'docx', 'jpg', 'jpeg', 'png', 'txt', 'xls', 'xlsx']
        if data['file_type'].lower() not in allowed_extensions:
            return jsonify({"success": False, "message": "File type not allowed"}), 400
        
        # Create file document
        file_doc = {
            "user_id": user_id,
            "file_name": data['file_name'],
            "original_name": data['original_name'],
            "file_type": data['file_type'].lower(),
            "file_size": data['file_size'],
            "mime_type": data.get('mime_type', ''),
            "base64_data": data['base64_data'],
            "file_category": data['file_category'],
            "description": data.get('description', data['file_name']),
            "uploaded_at": datetime.utcnow(),
            "status": "active"
        }
        
        # Insert into database
        result = case_files.insert_one(file_doc)
        
        return jsonify({
            "success": True, 
            "message": "File uploaded successfully!",
            "file_id": str(result.inserted_id)
        })
        
    except Exception as e:
        print(f"Error uploading case file: {str(e)}")
        return jsonify({"success": False, "message": "Upload failed. Please try again."}), 500


@app.route("/api/case-files")
def get_case_files():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user"]
    files = list(case_files.find({"user_id": user_id, "status": "active"}))
    
    for file in files:
        file["_id"] = str(file["_id"])
        file["file_size_mb"] = round(file["file_size"] / (1024 * 1024), 2)
        file.pop("base64_data", None)
    
    return jsonify({"success": True, "files": files})

@app.route("/api/case-file/<file_id>")
def get_case_file(file_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user"]
    
    try:
        file_doc = case_files.find_one({
            "_id": ObjectId(file_id), 
            "user_id": user_id,
            "status": "active"
        })
        
        if not file_doc:
            return jsonify({"error": "File not found"}), 404
        
        file_doc["_id"] = str(file_doc["_id"])
        file_doc["file_size_mb"] = round(file_doc["file_size"] / (1024 * 1024), 2)
        
        return jsonify({"success": True, "file": file_doc})
        
    except Exception as e:
        print(f"Error getting case file: {str(e)}")
        return jsonify({"error": "Failed to retrieve file"}), 500

# Route to delete a case file
@app.route("/api/case-file/<file_id>", methods=["DELETE"])
def delete_case_file(file_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    user_id = session["user"]
    
    try:
        result = case_files.update_one(
            {"_id": ObjectId(file_id), "user_id": user_id},
            {"$set": {"status": "deleted", "deleted_at": datetime.utcnow()}}
        )
        
        if result.matched_count == 0:
            return jsonify({"error": "File not found"}), 404
        
        return jsonify({"success": True, "message": "File deleted successfully"})
        
    except Exception as e:
        print(f"Error deleting case file: {str(e)}")
        return jsonify({"error": "Failed to delete file"}), 500

# Route to view case files page
@app.route("/case-files")
def case_files_page():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user = users.find_one({"_id": ObjectId(session["user"])})
    return render_template("case_files.html", 
                         user={"name": user.get("name", "User")})

@app.route("/generate_doc_reference", methods=["POST"])
def generate_doc_reference():
    """
    Flask route to generate and save document reference
    """
    try:
        data = request.get_json()
        doc_name = data.get("doc_name")
        query_data = data.get("query_data", {})

        if not doc_name:
            return jsonify({"success": False, "message": "Missing doc_name"}), 400

        # Call utility function
        result = handle_document_reference_request(doc_name, query_data)

        if result["success"]:
            return jsonify(result), 200
        else:
            return jsonify(result), 500

    except Exception as e:
        return jsonify({"success": False, "message": "Unexpected error", "error": str(e)}), 500


@app.route("/see_reference")
def see_reference():
    """
    Serve the generated reference HTML
    """
    return render_template("doc_reference.html")

# ------------------NEW UPDATE --------------------

# New collections
hired_lawyers = db["hired_lawyers"]
case_milestones = db["case_milestones"]

@app.route("/hired-lawyers")
def hired_lawyers_page():
    if "user" not in session:
        return redirect(url_for("login"))
    
    user_id = session["user"]
    hired_list = list(hired_lawyers.find({"user_id": user_id}))

    for hired in hired_list:
        lawyer = db.lawyers.find_one({"_id": ObjectId(hired["lawyer_id"])})
        hired["lawyer_info"] = {
            "name": lawyer.get("name", "Unknown Lawyer"),
            "specialization": lawyer.get("specialization", []),
            "email": lawyer.get("email", "")
        }

        milestones = list(case_milestones.find({"hired_lawyer_id": hired["_id"]}))
        if milestones:
            total = len(milestones)
            completed = sum(1 for m in milestones if m.get("status") == "completed")
            progress = round((completed / total) * 100)
        else:
            progress = 0
        hired["progress"] = progress

    return render_template(
        "hired_lawyers.html", 
        hired_lawyers=hired_list,
        user=users.find_one({"_id": ObjectId(user_id)})
    )

@app.route("/hired-lawyer-details/<hired_id>")
def hired_lawyer_details(hired_id):
    if "user" not in session:
        return redirect(url_for("login"))
    
    user_id = session["user"]
    hired = hired_lawyers.find_one({"_id": ObjectId(hired_id), "user_id": user_id})
    
    if not hired:
        flash("Case not found", "error")
        return redirect(url_for("hired_lawyers_page"))
    
    # Get milestones
    milestones = list(case_milestones.find({"hired_lawyer_id": ObjectId(hired_id)}))
    completed_milestones = len([m for m in milestones if m.get("status") == "completed"])
    
    # Get lawyer info
    lawyer = db.lawyers.find_one({"_id": ObjectId(hired["lawyer_id"])})
    hired["lawyer_info"] = {
        "name": lawyer.get("name", "Unknown Lawyer"),
        "specialization": lawyer.get("specialization", []),
        "experience": lawyer.get("experience", 0)
    }
    
    hired["strategy"] = hired.get("case_strategy", "")
    documents = []  
    
    return render_template("hired_lawyer_details.html",
                         hired_lawyer=hired,
                         milestones=milestones,
                         completed_milestones=completed_milestones,
                         documents=documents,
                         user=users.find_one({"_id": ObjectId(user_id)}))


@app.route("/api/verify-case-progress/<hired_id>", methods=["POST"])
def verify_case_progress(hired_id):
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    try:
        hired = hired_lawyers.find_one({"_id": ObjectId(hired_id), "user_id": session["user"]})
        if not hired:
            return jsonify({"success": False, "message": "Case not found"}), 404
        
        milestones = list(case_milestones.find({"hired_lawyer_id": ObjectId(hired_id)}))
        
        verification_result = {
            "progress": hired.get("progress", 0),
            "expected_progress": calculate_expected_progress(milestones),
            "milestone_status": analyze_milestone_completion(milestones),
            "suggestions": generate_progress_suggestions(milestones, hired)
        }
        
        return jsonify({
            "success": True,
            "message": "Progress verification completed",
            "result": verification_result
        })
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

def calculate_expected_progress(milestones):
    return 50  

def analyze_milestone_completion(milestones):
    return {"completed": len([m for m in milestones if m.get("status") == "completed"])}

def generate_progress_suggestions(milestones, hired_case):
    return "Continue with current pace. Next milestone due soon."
import traceback

@app.route("/api/hire-lawyer", methods=["POST"])
def hire_lawyer():
    if "user" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    try:
        data = request.get_json()
        lawyer_id = data.get("lawyer_id")
        query_id = data.get("query_id")
        case_title = data.get("case_title")
        
        if not all([lawyer_id, query_id, case_title]):
            return jsonify({"success": False, "message": "Missing required fields"}), 400
        
        user_id = session["user"]
        
        lawyer = db.lawyers.find_one({"_id": ObjectId(lawyer_id)})
        if not lawyer:
            return jsonify({"success": False, "message": "Lawyer not found"}), 404
        
        existing_hire = hired_lawyers.find_one({
            "user_id": user_id,
            "lawyer_id": lawyer_id,
            "query_id": query_id
        })
        
        if existing_hire:
            return jsonify({"success": False, "message": "You have already hired this lawyer for this case"}), 400
        
        new_hire = {
            "user_id": user_id,
            "lawyer_id": lawyer_id,
            "query_id": query_id,
            "case_title": case_title,
            "status": "active",
            "hired_date": datetime.utcnow(),
            "agreed_fee": lawyer.get("fee", 0),
            "currency": lawyer.get("currency", "USD"),
            "progress": 0,
            "last_updated": datetime.utcnow()
        }
        
        result = hired_lawyers.insert_one(new_hire)
        hire_id = str(result.inserted_id)
        
        initial_milestones = [
            {
                "hired_lawyer_id": ObjectId(hire_id),
                "milestone_name": "Initial Consultation",
                "description": "First meeting to discuss case details",
                "due_date": datetime.utcnow() + timedelta(days=7),
                "status": "not_started",
                "percentage_value": 10,
                "created_date": datetime.utcnow()
            },
            {
                "hired_lawyer_id": ObjectId(hire_id),
                "milestone_name": "Case Analysis",
                "description": "Detailed analysis of legal aspects",
                "due_date": datetime.utcnow() + timedelta(days=14),
                "status": "not_started",
                "percentage_value": 20,
                "created_date": datetime.utcnow()
            }
        ]
        
        case_milestones.insert_many(initial_milestones)
        
        return jsonify({
            "success": True,
            "message": "Lawyer hired successfully",
            "hire_id": hire_id
        })
        
    except Exception as e:
        print("❌ Error hiring lawyer:", str(e))
        traceback.print_exc()   
        return jsonify({"success": False, "message": str(e)}), 500
@app.route("/lawyer-cases")
def lawyer_cases():
    if "lawyer" not in session:
        return redirect(url_for("login"))

    lawyer_id = session["lawyer"]  

    pipeline = [
        {"$match": {"lawyer_id": lawyer_id}}, 

        {"$lookup": {
            "from": "users",
            "localField": "user_id",  
            "foreignField": "_id",    
            "as": "client"
        }},
        {"$set": {"user_obj_id": {"$toObjectId": "$user_id"}}},
        {"$lookup": {
            "from": "users",
            "localField": "user_obj_id",
            "foreignField": "_id",
            "as": "client"
        }},
        {"$unwind": {"path": "$client", "preserveNullAndEmptyArrays": True}},

        {"$lookup": {
            "from": "case_milestones",
            "localField": "_id",
            "foreignField": "hired_lawyer_id",
            "as": "milestones"
        }},

        {"$addFields": {
            "milestone_completed": {
                "$size": {
                    "$filter": {
                        "input": "$milestones",
                        "cond": {"$eq": ["$$this.status", "completed"]}
                    }
                }
            },
            "milestone_total": {"$size": "$milestones"},
            "next_due": {"$min": "$milestones.due_date"}
        }},

        {"$project": {
            "case_title": 1,
            "status": 1,
            "progress": {
    "$cond": [
        {"$eq": ["$milestone_total", 0]}, 
        0, 
        {"$round": [{"$multiply": [{"$divide": ["$milestone_completed", "$milestone_total"]}, 100]}, 0]}
    ]
},

            "agreed_fee": 1,
            "currency": 1,
            "client.name": 1,
            "client.email": 1,
            "milestone_completed": 1,
            "milestone_total": 1,
            "next_due": 1
        }}
    ]

    cases = list(hired_lawyers.aggregate(pipeline))
    lawyer = db.lawyers.find_one({"_id": ObjectId(lawyer_id)}) if ObjectId.is_valid(lawyer_id) else {"name": "Unknown"}

    return render_template("lawyer_cases.html", cases=cases, lawyer=lawyer)


@app.route("/lawyer-case-details/<case_id>")
def lawyer_case_details(case_id):
    case = hired_lawyers.find_one({"_id": ObjectId(case_id)})
    if not case:
        abort(404, "Case not found")

    client = users.find_one({"_id": ObjectId(case["user_id"])})
    lawyer = lawyers.find_one({"_id": ObjectId(case["lawyer_id"])})
    milestones = list(case_milestones.find({"hired_lawyer_id": ObjectId(case_id)}).sort("due_date", 1))
    uploaded_documents = list(documents.find({"user_id": str(case["user_id"])}))

    return render_template(
        "lawyer_case_details.html",
        case=case,  
        client=client,
        lawyer=lawyer,
        milestones=milestones,
        documents=uploaded_documents
    )


@app.route("/save-strategy/<case_id>", methods=["POST"])
def save_strategy(case_id):
    if "lawyer" not in session:
        return jsonify({"success": False, "message": "Unauthorized"}), 401
    
    data = request.get_json()
    strategy = data.get("strategy", "").strip()

    try:
        result = hired_lawyers.update_one(
            {"_id": ObjectId(case_id)},
            {"$set": {"case_strategy": strategy, "last_updated": datetime.utcnow()}}
        )
        if result.modified_count > 0:
            return jsonify({"success": True, "message": "Strategy saved"})
        else:
            return jsonify({"success": True, "message": "No change"})  
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/lawyer/chat-interface")
def lawyer_chat_interface():
    if "lawyer" not in session:
        return redirect(url_for("lawyer_login"))
    
    lawyer = db.lawyers.find_one({"_id": ObjectId(session["lawyer"])})
    return render_template("lawyer_chat_interface.html", lawyer=lawyer)


@app.route("/api/lawyer/chats")
def get_lawyer_chats():
    if "lawyer" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    lawyer_id = session["lawyer"]
    lawyer_chats = list(chats.find({"lawyer_id": lawyer_id}))
    
    chat_list = []
    for chat in lawyer_chats:
        user_id = chat["user_id"]
        user = users.find_one({"_id": ObjectId(user_id)})
        
        if user:
            last_message = chat["messages"][-1] if chat["messages"] else None
            
            chat_list.append({
                "chat_id": str(chat["_id"]),
                "user_id": user_id,
                "user_name": user.get("name", "User"),
                "last_message": last_message["message"] if last_message else "No messages yet",
                "last_message_time": last_message["timestamp"] if last_message else chat["created_at"],
                "unread_count": sum(1 for msg in chat["messages"] if msg.get("sender") == "user" and not msg.get("read", False))
            })
    
    chat_list.sort(key=lambda x: x["last_message_time"], reverse=True)
    return jsonify({"chats": chat_list})


@app.route("/lawyer/chat/<chat_id>")
def get_lawyer_chat(chat_id):
    if "lawyer" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    chat = chats.find_one({"_id": ObjectId(chat_id)})
    if not chat or chat["lawyer_id"] != session["lawyer"]:
        return jsonify({"error": "Chat not found"}), 404
    
    chat["_id"] = str(chat["_id"])
    return jsonify(chat)


@app.route("/lawyer/chat/<chat_id>/read", methods=["POST"])
def lawyer_mark_messages_as_read(chat_id):
    if "lawyer" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$set": {"messages.$[elem].read": True}},
        array_filters=[{"elem.sender": "user", "elem.read": {"$ne": True}}]
    )
    return jsonify({"status": "ok"})

@app.route("/lawyer/chat/<chat_id>/send", methods=["POST"])
def lawyer_send_message(chat_id):
    if "lawyer" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    message = request.json.get("message")
    if not message:
        return jsonify({"error": "Empty message"}), 400
    
    message_data = {
        "sender": "lawyer",
        "message": message,
        "timestamp": datetime.utcnow(),
        "read": False
    }
    
    chats.update_one(
        {"_id": ObjectId(chat_id)},
        {"$push": {"messages": message_data}}
    )
    
    return jsonify({"status": "ok"})
@app.route("/generate-milestones/<case_id>", methods=["POST"])
def generate_milestones(case_id):
    case = hired_lawyers.find_one({"_id": ObjectId(case_id)})
    if not case:
        return jsonify({"status": "error", "message": "Case not found"}), 404

    query = case.get("case_query", "Legal case")
    strategy = case.get("case_strategy", "")

    generator = GenerateMilestones(query, strategy)
    result = generator.call_api()

    if "deadlines" in result and result["deadlines"]:
        case_milestones.delete_many({"hired_lawyer_id": ObjectId(case_id)})

        milestones = []
        for d in result["deadlines"]:
            milestone = {
                "hired_lawyer_id": ObjectId(case_id),
                "milestone_name": d["task"],
                "description": d.get("description", ""),
                "due_date": datetime.strptime(d["due_date"], "%Y-%m-%d"),
                "status": "not_started",
                "percentage_value": 0,
                "created_date": datetime.utcnow(),
                "completed_date": None,
                "lawyer_notes": ""
            }
            milestones.append(milestone)

        case_milestones.insert_many(milestones)

        return jsonify({"status": "success"}), 200

    return jsonify({"status": "error", "message": "No milestones generated"}), 500



@app.route("/update-milestone/<milestone_id>", methods=["POST"])
def update_milestone(milestone_id):
    data = request.get_json()
    new_status = data.get("status")

    if new_status not in ["not_started", "completed"]:
        return jsonify({"status": "error", "message": "Invalid status"}), 400

    update_data = {"status": new_status}
    if new_status == "completed":
        update_data["completed_date"] = datetime.utcnow()  
    else:
        update_data["completed_date"] = None

    result = case_milestones.update_one(
        {"_id": ObjectId(milestone_id)},
        {"$set": update_data}
    )

    if result.modified_count > 0:
        return jsonify({"status": "success"})
    else:
        return jsonify({"status": "error", "message": "Milestone not found"}), 404


@app.route("/api/verify-strategy/<case_id>", methods=["GET"])
def verify_strategy(case_id):
    try:
        force_refresh = request.args.get('force', 'false').lower() == 'true'

        pipeline = [
            {"$match": {"_id": ObjectId(case_id)}},
            {"$lookup": {
                "from": "case_milestones",
                "localField": "_id",
                "foreignField": "hired_lawyer_id",
                "as": "milestones"
            }},
            {"$project": {
                "user_id": 1,
                "lawyer_id": 1,
                "case_title": 1,
                "case_strategy": 1,
                "milestones": 1
            }}
        ]

        case_data = list(db.hired_lawyers.aggregate(pipeline))
        if not case_data:
            return jsonify({"success": False, "message": "Case not found"}), 404

        case = case_data[0]
        case_title = case.get("case_title", "Untitled Case")
        strategy = case.get("case_strategy", "No strategy provided.")
        milestones = case.get("milestones", [])

        if not force_refresh:
            recent_verification = db.strategy_verifications.find_one(
                {
                    "case_id": ObjectId(case_id),
                    "verified_at": {"$gte": datetime.utcnow() - timedelta(hours=24)}
                },
                sort=[("verified_at", -1)]
            )

            if recent_verification:
                return jsonify({
                    "success": True,
                    "case_title": case_title,
                    "strategy": strategy,
                    "analysis": recent_verification.get("analysis", "No analysis available"),
                    "strengths": recent_verification.get("strengths", []),
                    "weaknesses": recent_verification.get("weaknesses", []),
                    "improvements": recent_verification.get("improvements", []),
                    "deadlines": recent_verification.get("suggested_deadlines", []),
                    "verified_at": recent_verification["verified_at"].strftime("%d %b %Y at %I:%M %p"),
                    "from_cache": True
                })

        for m in milestones:
            if isinstance(m.get("due_date"), str):
                try:
                    m["due_date"] = datetime.fromisoformat(m["due_date"])
                except:
                    m["due_date"] = None

        ai_feedback = run_ai_verification(case_title, strategy, milestones)
        print("AI Feedback:", ai_feedback)

        verification_record = {
            "case_id": ObjectId(case_id),
            "user_id": case.get("user_id"),
            "lawyer_id": case.get("lawyer_id"),
            "case_title": case_title,
            "case_strategy": strategy,
            "verified_at": datetime.utcnow(),
            "milestones_count": len(milestones),
            "analysis": ai_feedback.get("analysis", ""),
            "strengths": ai_feedback.get("strengths", []),
            "weaknesses": ai_feedback.get("weaknesses", []),
            "improvements": ai_feedback.get("improvements", []),
            "suggested_deadlines": ai_feedback.get("suggested_deadlines", [])
        }

        db.strategy_verifications.insert_one(verification_record)

        return jsonify({
            "success": True,
            "case_title": case_title,
            "strategy": strategy,
            "analysis": ai_feedback.get("analysis", "No analysis available"),
            "strengths": ai_feedback.get("strengths", []),
            "weaknesses": ai_feedback.get("weaknesses", []),
            "improvements": ai_feedback.get("improvements", []),
            "deadlines": ai_feedback.get("suggested_deadlines", []),
            "verified_at": verification_record["verified_at"].strftime("%d %b %Y at %I:%M %p"),
            "from_cache": False
        })

    except Exception as e:
        print(f"Error in verify_strategy: {str(e)}")
        return jsonify({"success": False, "message": str(e)}), 500

@app.route("/api/verification-history/<case_id>", methods=["GET"])
def get_verification_history(case_id):
    """Get verification history from strategy_verifications collection"""
    try:
        limit = int(request.args.get('limit', 5))
        
        verifications = list(db.strategy_verifications.find(
            {"case_id": ObjectId(case_id)},
            {
                "verified_at": 1,
                "analysis": 1,
                "strengths": 1,
                "weaknesses": 1,
                "milestones_count": 1
            }
        ).sort("verified_at", -1).limit(limit))
        
        for v in verifications:
            v["_id"] = str(v["_id"])
            v["verified_at"] = v["verified_at"].strftime("%d %b %Y at %I:%M %p")
            v["analysis_preview"] = v.get("analysis", "")[:100] + "..." if len(v.get("analysis", "")) > 100 else v.get("analysis", "")
        
        return jsonify({
            "success": True,
            "verifications": verifications,
            "total_count": len(verifications)
        })
        
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500
    
@app.route("/api/latest-verification/<case_id>", methods=["GET"])
def get_latest_verification(case_id):
    try:
        latest = db.strategy_verifications.find_one(
            {"case_id": ObjectId(case_id)},
            sort=[("verified_at", -1)]
        )
        if not latest:
            return jsonify({"success": False, "message": "No verification found"})
        
        latest["_id"] = str(latest["_id"])
        return jsonify({
            "success": True,
            "analysis": latest.get("analysis", ""),
            "strengths": latest.get("strengths", []),
            "weaknesses": latest.get("weaknesses", []),
            "improvements": latest.get("improvements", []),
            "deadlines": latest.get("suggested_deadlines", []),
            "verified_at": latest["verified_at"].strftime("%d %b %Y at %I:%M %p"),
            "from_cache": True
        })
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True, host="localhost", port=5000)
