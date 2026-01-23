from datetime import datetime
from app.extensions.db import db

class Login:
    def __init__(self, email, password):
        self.email = email
        self.password = password

    def to_dict(self):
        return {
            "email": self.email,
            "password": self.password,
        }