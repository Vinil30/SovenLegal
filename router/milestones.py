from datetime import datetime, timedelta

from bson import ObjectId
from flask import jsonify, request

from utils.lawyer_deadlines import GenerateMilestones
from utils.verify_strategy import run_ai_verification


def register_routes(app, context):
    db = context["db"]
    hired_lawyers = db["hired_lawyers"]
    case_milestones = db["case_milestones"]

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
