import bcrypt
import jwt
import os
from redis import Redis
from functools import wraps

from flask import current_app, g
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
from flask_jwt_extended import jwt_required
from rq import Queue
from bson import ObjectId

from datetime import datetime, timedelta
from app.models.business_model import Client, Token, Business
from app.models.user_model import User
from app.utils.logger import Log # import logging
from app.utils.generators import generate_client_id, generate_client_secret


from app.schemas.business_schema import OAuthCredentialsSchema

SECRET_KEY = os.getenv("SECRET_KEY") 

REDIS_HOST = os.getenv("REDIS_HOST")
connection = Redis(host=REDIS_HOST, port=6379)
queue = Queue("emails", connection=connection)


blp = Blueprint("OAuth2", __name__, url_prefix="/auth", description="Oauth2 management")

@blp.route("/token", methods=["POST"])
@blp.arguments(OAuthCredentialsSchema)
@blp.doc(
    summary="Generate an OAuth token",
    description="This endpoint authenticates a client using `client_id` and `client_secret`. "
                "If authentication is successful, it returns a Bearer token valid for 24 hours.",
    responses={
        200: {
            "description": "Successful authentication",
            "content": {
                "application/json": {
                    "example": {
                        "access_token": "eyJhbGciOiJIUzI1...",
                        "token_type": "Bearer",
                        "expires_in": 86400
                    }
                }
            }
        },
        401: {
            "description": "Invalid credentials or access revoked",
            "content": {
                "application/json": {
                    "example": {
                        "message": "Invalid client credentials"
                    }
                }
            }
        },
        422:{
           "description": "Validation error: Missing required fields",
            "content": {
            "application/json": {
                "example": {
                    "code": 422,
                    "errors": {
                        "json": {
                            "client_id": [
                                "Client ID is required"
                            ],
                            "client_secret": [
                                "Client secret is required"
                            ]
                        }
                    },
                    "status": "Unprocessable Entity"
                }
              }
            }
        }
    }
)
def post(self):
        client_ip = request.remote_addr
        data = request.json
        client_id = data.get('client_id')
        client_secret = data.get('client_secret')
        
        truncated_client_id = client_id[:7] + "..." if client_id else None
        
        
        Log.info(f"[business_oauth_resource.py][auth/token][{truncated_client_id}] request from IP: {client_ip}")
        Log.info(f"[business_oauth_resource.py][auth/token][{truncated_client_id}][{client_ip}]")

        # Validate client credentials
        client = Client.get_client(client_id, client_secret)
        if not client:
            abort(401, message="Invalid client credentials")
            
        business = Business.get_business(client_id)
        if not business:
            abort(401, message="Your access has been revoked")
        
        
        # Generate access token
        expires_in = datetime.now() + timedelta(hours=24)
        token = jwt.encode(
            {
                'admin_id': str(business["user_id"]), 
                'exp': expires_in
            },
            SECRET_KEY,
            algorithm="HS256"
        )

        # Save token in MongoDB
        Token.create_token(client_id, token, expires_in)

        # Token is for 24 hours
        return jsonify({'access_token': token, 'token_type': 'Bearer', 'expires_in': 86400})
