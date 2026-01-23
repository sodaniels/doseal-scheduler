import os
from flask import jsonify
from flask_jwt_extended import JWTManager

def jwt_manager_configuration(app):
    jwt = JWTManager(app)
    '''
    1. JWT Block token checking
    2. JWT Exipire token checking
    3. JWT Invalid token checking
    4. JWT Unauthorized token checking
    5. JWT Fresh token checking
    6. JWT revoke token
    '''
    # @jwt.additional_claims_loader
    # def add_claims_to_jwt(identity):
    #     # TODO: Read from a config file instead of hard-coding
    #     if identity == 1:
    #         return {"is_admin": True}
    #     return {"is_admin": False}

    @jwt.token_in_blocklist_loader
    def check_if_token_in_blocklist(jwt_header, jwt_payload):
        jti = jwt_payload["jti"]
        # Check if the 'jti' exists in Redis (if blocked)
        return redis_client.get(f"blocked_{jti}") is not None

    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        return (
            jsonify(
                {
                    "code": "401",
                    "status": "Unauthorized",
                    "message": "The token has expired.", 
                    "error": "token_expired"
                    }
                ),
            401,
        )

    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        return (
            jsonify(
                {
                    "code": "401",
                    "status": "Unauthorized",
                    "message": "Signature verification failed.", 
                    "error": "invalid_token"}
            ),
            401,
        )

    @jwt.unauthorized_loader
    def missing_token_callback(error):
        return (
            jsonify(
                {
                    "code": "401",
                    "status": "Unauthorized",
                    "description": "Request does not contain an access token.",
                    "error": "authorization_required",
                }
            ),
            401,
        )

    @jwt.needs_fresh_token_loader
    def token_not_fresh_callback(jwt_header, jwt_payload):
        return (
            jsonify(
                {
                    "code": "401",
                    "status": "Unauthorized",
                    "description": "The token is not fresh.",
                    "error": "fresh_token_required",
                }
            ),
            401,
        )

    @jwt.revoked_token_loader
    def revoked_token_callback(jwt_header, jwt_payload):
        return (
            jsonify(
                {
                    "code": "401",
                    "status": "Unauthorized",
                    "description": "The token has been revoked.", 
                    "error": "token_revoked"
                    }
            ),
            401,
        )
