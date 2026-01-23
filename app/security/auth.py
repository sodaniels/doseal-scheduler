from functools import wraps
from flask import Blueprint, request, jsonify
from app.models.admin_model import Client, Token
from datetime import datetime, timedelta

import jwt
import os

blp = Blueprint("OAuth2", __name__, url_prefix="/token", description="Authentication management")

SECRET_KEY = os.getenv("SECRET_KEY") 

def generate_token():
    data = request.json
    client_id = data.get('client_id')
    client_secret = data.get('client_secret')

    # Validate client credentials
    client = Client.get_client(client_id, client_secret)
    if not client:
        return jsonify({'error': 'Invalid client credentials'}), 401

    # Generate access token
    expires_in = datetime.now() + timedelta(hours=1)
    token = jwt.encode(
        {'client_id': client_id, 'exp': expires_in},
        SECRET_KEY,
        algorithm="HS256"
    )

    # Save token in MongoDB
    Token.create_token(client_id, token, expires_in)

    return jsonify({'access_token': token, 'token_type': 'Bearer', 'expires_in': 3600})

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({'error': 'Unauthorized'}), 401

        token = auth_header.split()[1]
        try:
            decoded_token = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token'}), 401

        # Check if token exists in MongoDB
        stored_token = Token.get_token(token)
        if not stored_token:
            return jsonify({'error': 'Invalid token'}), 401

        return f(*args, **kwargs)
    return decorated