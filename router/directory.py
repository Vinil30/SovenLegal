from bson import ObjectId
from flask import jsonify, render_template, session


def register_routes(app, context):
    db = context["db"]
    users = context["users"]

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
