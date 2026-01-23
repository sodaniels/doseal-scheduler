from flask import jsonify
from ..constants.service_code import HTTP_STATUS_CODES


def prepared_response(status, status_code, message, data=None, errors=None, required_fields=None, agent_id=None):
    # Define mandatory fields that should always appear
    mandatory_fields = ["message", "status_code", "success"]
    
    # Define all possible fields
    all_fields = {
        "message": f"{message}",
        "status_code": HTTP_STATUS_CODES[status_code],
        "success": status,
        "data": data,
        "agent_id": agent_id,
        "required_fields": required_fields,
        "errors": errors,
    }
    
    # Include mandatory fields and optional fields that have values
    response_data = {
        key: value for key, value in all_fields.items() 
        if key in mandatory_fields or value is not None
    }
    
    return jsonify(response_data), HTTP_STATUS_CODES[status_code]
 