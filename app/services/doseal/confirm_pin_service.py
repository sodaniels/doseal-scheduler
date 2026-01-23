from flask import jsonify
from bson import ObjectId
from bson.errors import InvalidId
from ...models.user_model import User
from ...utils.json_response import prepared_response



def confirm_pin(user__id, pin, account_type=None):
    
    # Validate user__id exists
    if user__id is None:
        return prepared_response(False, "NOT_FOUND", "User Id is required")

    # Ensure user__id is a valid ObjectId
    try:
        # Convert string to ObjectId only if needed
        if not isinstance(user__id, ObjectId):
            user__id = ObjectId(user__id)
    except (InvalidId, TypeError):
        return prepared_response(False, "BAD_REQUEST", "Invalid User Id")

    # Validate PIN is present
    if pin is None:
        return prepared_response(False, "NOT_FOUND", "PIN is required")

    # confirming PIN
    is_pin_confirmed = User.confirm_user_pin(user__id, pin, account_type)
    
    if is_pin_confirmed:
       return prepared_response(True, "OK", "PIN confirmed successfully")
    else:
        return prepared_response(False, "BAD_REQUEST", "Wrong PIN entered.")
    
    
    