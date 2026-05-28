from datetime import datetime

from bson import ObjectId
from flask import jsonify, redirect, render_template, request, session, url_for


def register_routes(app, context):
    db = context["db"]
    users = context["users"]
    chats = db["chats"]

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
