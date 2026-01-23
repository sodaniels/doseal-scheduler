import bcrypt
import os
from redis import Redis

from flask import current_app
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from flask_jwt_extended import jwt_required
from rq import Queue


from app.extensions.db import db
# from app import queue
from app.utils.logger import Log # import logging
from app.models.user_model import User
from app.schemas.user_schema import UserSchema
from tasks import send_user_registration_email

REDIS_HOST = os.getenv("REDIS_HOST")
connection = Redis(host=REDIS_HOST, port=6379)
queue = Queue("emails", connection=connection)


blp = Blueprint("User", __name__, url_prefix="/auth", description="User management")

   
@blp.route("/register", methods=["POST"])

class RegisterResource(MethodView):
    # @jwt_required()
    @blp.arguments(UserSchema)
    @blp.response(201, UserSchema)
    def post(self, user_data):
        client_ip = request.remote_addr
        email = user_data["email"]
        Log.info(f"[admin_oauth_resource.py][auth/token][{email}] request from IP: {client_ip}")
        Log.info(f"[admin_oauth_resource.py][auth/token][{email}][{client_ip}]")
        # Check if the user already exists based on email
        if db.get_collection("users").find_one({"email": user_data["email"]}):
            abort(409, message="User already exists")
            
        user_data["password"] = bcrypt.hashpw(
            user_data["password"].encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        # Create a new user instance
        user = User(**user_data)

        # Try saving the user to MongoDB and handle any errors
        try:
            user_id = user.save()
            
            # send email after successful signup
            send_user_registration_email(user_data["email"], user_data['first_name'])
            
            # queue.enqueue(send_user_registration_email, user_data["email"], user_data['first_name'])
            
            return jsonify({
                "success": True,
                "statusCode": 201,
                "message": "User created successfully",
                "user_id": str(user_id),  # Return the MongoDB generated user ID
            })
        except PyMongoError as e:
            return jsonify({
                "success": False,
                "statusCode": 500,
                "message": "Error saving user to the database",
                "error": str(e)
            })
        except Exception as e:
            return jsonify({
                "success": False,
                "statusCode": 500,
                "message": "An unexpected error occurred",
                "error": str(e)
            })

    

