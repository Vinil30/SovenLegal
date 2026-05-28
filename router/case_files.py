from datetime import datetime

from bson import ObjectId
from flask import jsonify, redirect, render_template, request, session, url_for

from utils.doc_reference_generator import handle_document_reference_request


def register_routes(app, context):
    db = context["db"]
    users = context["users"]
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
