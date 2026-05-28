from datetime import datetime

from bson import ObjectId
from flask import jsonify, redirect, render_template, request, session, url_for

from utils.doc_scan import Image_Analyser
from utils.generate_req_docs import Generate_Documents


def register_routes(app, context):
    users = context["users"]
    documents = context["documents"]
    queries = context["db"]["queries"]

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
            "mime_type": data.get("mime_type", "image/jpeg"),
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


    @app.route("/document/scan/<doc_id>", methods=["POST"])
    def scan_document(doc_id):
        # Fetch document
        doc = documents.find_one({"_id": ObjectId(doc_id)})
        if not doc or "base64_format" not in doc:
            return jsonify({"error": "No image found for this document"}), 400

        base64_data = doc["base64_format"]
        mime_type = doc.get("mime_type")
        if not mime_type:
            if base64_data.startswith("/9j/"):
                mime_type = "image/jpeg"
            elif base64_data.startswith("iVBORw0KGgo"):
                mime_type = "image/png"
            elif base64_data.startswith("R0lGOD"):
                mime_type = "image/gif"
            elif base64_data.startswith("JVBER"):
                mime_type = "application/pdf"
            else:
                mime_type = "image/jpeg"

        if mime_type == "application/pdf":
            try:
                import base64
                import fitz

                pdf_bytes = base64.b64decode(base64_data)
                pdf_doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                if pdf_doc.page_count == 0:
                    return jsonify({"error": "PDF has no pages to scan"}), 400

                page = pdf_doc.load_page(0)
                pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                base64_data = base64.b64encode(pix.tobytes("png")).decode("utf-8")
                mime_type = "image/png"
                pdf_doc.close()
            except Exception as e:
                return jsonify({
                    "error": f"Could not convert PDF to image for scanning: {str(e)}"
                }), 400

        if not mime_type.startswith("image/"):
            return jsonify({
                "error": "Document scanning supports image files and PDFs only."
            }), 400

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
                mime_type=mime_type,
                required_elements=required_elements,
                visual_reference=visual_reference
            )
            result = analyzer.analyze_legal_doc()

            if result.get("error"):
                return jsonify({
                    "error": result.get(
                        "detailed_analysis",
                        "Document scan failed"
                    )
                }), 500

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
