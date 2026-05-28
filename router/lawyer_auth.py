from datetime import datetime

from bson import ObjectId
from flask import flash, jsonify, redirect, render_template, request, session, url_for


def register_routes(app, context):
    db = context["db"]
    users = context["users"]
    lawyers = context["lawyers"]
    bcrypt = context["bcrypt"]
    chats = db["chats"]
    hired_lawyers = db["hired_lawyers"]
    case_milestones = db["case_milestones"]

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
