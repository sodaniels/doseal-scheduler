from flask import jsonify, request
import os
from app.utils.logger import Log  # Assuming logger is imported
from app.constants.service_code import HTTP_STATUS_CODES


def delete_model(model, model_id, image_path=None):
    """
    Generic function to delete a model based on model_id.
    Optionally, delete the associated image if the image_path is provided.

    Args:
    - model: The model (e.g., Brand, SubCategory) class
    - model_id: The ID of the model to be deleted
    - image_path: The path to the image to be deleted (optional)

    Returns:
    - dict: A response message indicating success or failure
    """
    client_ip = request.remote_addr
    Log.info(f"[setup_resource.py][{model.__name__}Resource][delete][{client_ip}][{model_id}] initiated delete")

    # Check if model_id is provided
    if not model_id:
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["BAD_REQUEST"],
            "message": f"{model.__name__} id must be provided."
        }), HTTP_STATUS_CODES["BAD_REQUEST"]

    try:
        # Attempt to retrieve the model instance by model_id
        instance = model.get_by_id(model_id)
        if not instance:
            return jsonify({
                "success": False,
                "status_code": HTTP_STATUS_CODES["NOT_FOUND"],
                "message": f"{model.__name__} not found"
            }), HTTP_STATUS_CODES["NOT_FOUND"]

        # Optionally delete the image if provided
        if image_path:
            try:
                os.remove(image_path)
                Log.info(f"[setup_resource.py][{model.__name__}Resource][delete][{client_ip}][{model_id}] old image removed successfully")
            except Exception as e:
                Log.error(f"[setup_resource.py][{model.__name__}Resource][delete][{client_ip}][{model_id}] error removing old image: {e}")

        # Call the delete method to remove the model instance
        result = model.delete(model_id)

        if result and result.get("success"):
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "message": f"{model.__name__} deleted successfully"
            }), HTTP_STATUS_CODES["OK"]

        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
            "message": f"Failed to delete {model.__name__}"
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

    except Exception as e:
        return jsonify({
            "success": False,
            "status_code": HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"],
            "message": f"An unexpected error occurred while deleting the {model.__name__}.",
            "error": str(e)
        }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]
