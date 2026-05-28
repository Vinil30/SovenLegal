from datetime import datetime, timedelta

from bson import ObjectId
from dateutil import parser
from flask import jsonify, redirect, render_template, request, session, url_for

from utils.generate_deadlines import GenerateDeadlines
from utils.generate_req_docs import Generate_Documents
from utils.query_analysis import Query_Analysis


def register_routes(app, context):
    db = context["db"]
    users = context["users"]
    deadlines_col = context["deadlines_col"]
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
