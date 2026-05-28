from datetime import datetime, timedelta

from bson import ObjectId
from flask import abort, flash, jsonify, redirect, render_template, request, session, url_for


def register_routes(app, context):
    db = context["db"]
    users = context["users"]
    documents = context["documents"]
    lawyers = context["lawyers"]
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
