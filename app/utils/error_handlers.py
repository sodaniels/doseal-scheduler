from flask import jsonify
from marshmallow import ValidationError

# Handle PermissionError
def handle_permission_error(error):
    response = {
        "error": "PermissionError",
        "message": str(error),
        "status_code": 403  # Forbidden
    }
    return jsonify(response), 403

# Handle ValidationError
def handle_validation_error(error):
    error_messages = error.messages
    response = {
        "error": "Validation Error",
        "message": error_messages,
        "status_code": 400  # Bad Request
    }
    return jsonify(response), 400

# Handle TypeError
def handle_type_error(error):
    response = {
        "error": "Type Error",
        "message": str(error),  # Provide the exception message
        "status_code": 400  # Bad Request
    }
    return jsonify(response), 400

def handle_rate_limit(e):
        # e.description contains whatever you passed as error_message=
        return jsonify({
            "success": False,
            "status_code": 429,
            "error": "Too Many Requests",
            "message": e.description or "Too many requests, please try again later."
        }), 429

