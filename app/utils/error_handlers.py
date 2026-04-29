# app/utils/error_handlers.py

from flask import jsonify
from marshmallow import ValidationError
from ..models.base_model import SubscriptionError
from ..utils.json_response import prepared_response
from ..utils.feature_gate import FeatureNotAvailableError
from ..utils.social.api_rate_limiter import ApiRateLimitError

def register_error_handlers(app):

    @app.errorhandler(PermissionError)
    def handle_permission_error(error):
        return jsonify({
            "success": False,
            "status_code": 403,
            "message": str(error),
        }), 403

    @app.errorhandler(SubscriptionError)
    def handle_subscription_error(error):
        return jsonify({
            "success": False,
            "status_code": 402,
            "message": error.message,
            "errors": error.details,
        }), 402

    @app.errorhandler(FeatureNotAvailableError)
    def handle_feature_not_available(error):
        return jsonify({
            "success": False,
            "status_code": 403,
            "message": error.message,
            "errors": error.meta,
        }), 403

    @app.errorhandler(ValidationError)
    def handle_validation_error(error):
        return jsonify({
            "success": False,
            "status_code": 400,
            "message": "Validation error.",
            "errors": error.messages if hasattr(error, "messages") else [str(error)],
        }), 400

    @app.errorhandler(TypeError)
    def handle_type_error(error):
        return jsonify({
            "success": False,
            "status_code": 400,
            "message": str(error),
        }), 400

    @app.errorhandler(429)
    def handle_rate_limit(error):
        return jsonify({
            "success": False,
            "status_code": 429,
            "message": error.description or "Too many requests, please try again later.",
        }), 429

    @app.errorhandler(404)
    def handle_not_found(error):
        return jsonify({
            "success": False,
            "status_code": 404,
            "message": "The requested resource was not found.",
        }), 404

    @app.errorhandler(405)
    def handle_method_not_allowed(error):
        return jsonify({
            "success": False,
            "status_code": 405,
            "message": "This HTTP method is not allowed for this endpoint.",
        }), 405

    @app.errorhandler(Exception)
    def handle_general_error(error):
        from ..utils.logger import Log
        Log.error(f"[Unhandled Exception] {error.__class__.__name__}: {error}")
        return jsonify({
            "success": False,
            "status_code": 500,
            "message": "An unexpected error occurred.",
            "errors": [str(error)],
        }), 500


def _rethrow_permission_or_500(e, message="Error."):
    if isinstance(e, (PermissionError, SubscriptionError, FeatureNotAvailableError, ApiRateLimitError)):
        raise e
    return prepared_response(
        False, "INTERNAL_SERVER_ERROR",
        message,
        errors=[str(e)],
    )