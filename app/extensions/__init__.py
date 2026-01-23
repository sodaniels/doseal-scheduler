# app/extensions/__init__.py

from flask_jwt_extended import JWTManager
from flask_cors import CORS
from .db import db, redis_connection

# Only app-aware extensions should be global
jwt = JWTManager()
cors = CORS()

__all__ = [
    "jwt",
    "cors",
    "db",
    "redis_connection"
]
