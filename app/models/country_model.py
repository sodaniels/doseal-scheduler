from flask import request, jsonify
from datetime import datetime
from ..utils.logger import Log # import logging
from app.extensions.db import db

from app.constants.service_code import (
    HTTP_STATUS_CODES,
)

class Country:
    @classmethod
    def get_country():
        """
        Retrieve a countries (MongoDB's default identifier).
        """
        try:
            client_ip = request.remote_addr
            Log.info(f"[country_model.py][get_country][{client_ip}] retrieving countries")
            # Query countries  (which is MongoDB's default unique identifier) 
            data = db.get_collection("countries").find({})
            if not data:
                return jsonify({
                        "success": False,
                        "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
                        "message": "Could not retreive countries"
                    }), HTTP_STATUS_CODES["BAD_REQUEST"]
            data["_id"] = str(data["_id"])
            response = {
                "success": True,
                "status_code": 200,
                "data": data
            }
            return jsonify(response)
        except Exception as e:
            
               return jsonify({
                    "success": False,
                    "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
                    "message": "Failed to create customer group"
                }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

       
