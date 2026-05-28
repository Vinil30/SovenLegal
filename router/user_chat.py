from datetime import datetime

from bson import ObjectId
from flask import jsonify, redirect, render_template, request, session, url_for


def register_routes(app, context):
    db = context["db"]
    users = context["users"]
    documents = context["documents"]
    deadlines = db["deadlines"]
    queries = db["queries"]
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
