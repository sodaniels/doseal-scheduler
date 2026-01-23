import bcrypt
import os
from flask import jsonify, request, g
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from marshmallow import ValidationError
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    get_jwt,
    jwt_required,
)

from ...utils.logger import Log # import logging
from ...extensions.db import db
from ...schemas.login_schema import LoginSchema
from ...utils.helpers import Helper
from ...constants.service_code import (
    HTTP_STATUS_CODES,
)

blp = Blueprint("Authentication", __name__, url_prefix="/auth", description="Authentication management")
   
#login users   
@blp.route("/login", methods=["POST"])
class LoginResource(MethodView, Helper):
    def __init__(self):
        self.users = db.get_collection("users")
        
    @blp.arguments(LoginSchema)
    @blp.response(200, LoginSchema)

    def post(self, login_data):
        # Check if the user does not exist
        if not self.userExists(self.users, "email", login_data["email"]):
            abort(404, message="User do not exists")

        try:
             # retrieve the user information     
            user = self.users.find_one({"email": login_data["email"]})
            
            if user and self.verifyPwd(login_data["email"], login_data["password"]):
                access_token = create_access_token(identity = str(user["_id"]), fresh=True)
                referes_token = create_refresh_token(identity = str(user["_id"]))
                return jsonify({"access_token": access_token, "refresh_token": referes_token}),200
            abort(401, message ="Unauthorized")  
        except Exception as e:
           abort(401, message ="Unauthorized")
           
     # Verify login credentials
    def verifyPwd(self, email, password):
        # Fetch the user document from the database
        user = self.users.find_one({"email": email})
        
        if not user:
            return False  # User not found

        # Retrieve the stored hashed password
        hashed_pw = user["password"]

        # Use bcrypt.checkpw to compare the hashed password with the plaintext password
        if bcrypt.checkpw(password.encode('utf-8'), hashed_pw.encode('utf-8')):
            return True
        return False
 
    #check if user exist
    @staticmethod
    def userExists(tableObject, tableField, fieldValue):
        if Helper.isItemExists(tableObject, tableField, fieldValue):
            return True
        return False


@blp.route("/logout", methods=["POST"])
class LogoutResource(MethodView):
    @jwt_required()
    def post(self):
        jti = get_jwt()["jti"]  # Get the unique JWT ID (JTI)
        # Store the token in Redis, effectively blocking it
        store_token_in_redis(jti)
    
        return jsonify({"message": "Successfully logged out"}), 200
    
    
@blp.route("/refresh")
class TokenRefresh(MethodView):
    @jwt_required(refresh=True)
    def post(self):
        current_user = get_jwt_identity()
        new_token = create_access_token(identity=current_user, fresh=False)
        return jsonify({"access_token": new_token}), 200
    
    
@staticmethod  
def store_token_in_redis(jti, ttl=3600):
    # Store JWT with a TTL (e.g., 3600 seconds = 1 hour)
    redis_client.setex(f"blocked_{jti}", ttl, 1)   