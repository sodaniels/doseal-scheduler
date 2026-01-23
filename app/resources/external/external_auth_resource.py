from flask import jsonify, request
from flask_smorest import Blueprint
from flask.views import MethodView

from app.services.api_service import ApiService
from app.utils.logger import Log

blp = Blueprint("Sessions", __name__, url_prefix="/auth", description="Authentication management")
   
@blp.route("/sessions", methods=["POST"])

class SessionsInit(MethodView, ApiService):
    def post():
        """
        Route to create a session.
        """
        endpoint = "resource"
        payload = request.get_json() 
        
        try:
            Log.info("example_function executed successfully.")
            response = ApiService.post(endpoint, payload, timeout=10)
            return jsonify({"status": "success", "data": response})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e), "statusCode": 500}), 500
    
#login users   
# @blp.route("/sessions", methods=["POST"])
# def post():
#     """
#     Route to create a session.
#     """
#     endpoint = "resource"
#     payload = request.get_json() 
    
#     try:
#         response = ApiService.api_service.post(endpoint, payload, timeout=10)
#     except Exception as e:
#          return jsonify({"status": "error", "message": str(e), "statusCode": 500}), 500