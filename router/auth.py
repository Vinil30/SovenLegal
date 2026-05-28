from datetime import datetime

from flask import flash, jsonify, redirect, render_template, request, session, url_for


def register_routes(app, context):
    users = context["users"]
    bcrypt = context["bcrypt"]

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
