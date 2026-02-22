# app/resources/social/legal_page_public_resource.py

import os
from flask.views import MethodView
from flask_smorest import Blueprint
from flask import jsonify, request
from ...models.social.legal_page_model import LegalPage
from ...schemas.social.legal_page_schema import LegalPageQuerySchema
from ...constants.service_code import HTTP_STATUS_CODES
from ...utils.json_response import prepared_response
from ...utils.logger import Log
from ...utils.helpers import stringify_object_ids

blp_legal_public = Blueprint(
    "Public Legal Pages",
    __name__,
    description="Public Legal Pages"
)

@blp_legal_public.route("/legal")
class PublicLegalPageResource(MethodView):

    @blp_legal_public.arguments(LegalPageQuerySchema, location="query")
    def get(self, args):
        client_ip = request.remote_addr
        # Check if x-app-ky header is present and valid
        
        business_id = request.headers.get("X-Business-ID")
        app_key = request.headers.get('x-app-key')
        server_app_key = os.getenv("X_APP_KEY")
        
        log_tag = f"[legal_page_public_resource.py][PublicLegalPageResource][get][{client_ip}]"
        
        if not business_id:
            Log.info(f"{log_tag} Missing X-Business-ID")
            return prepared_response(False, "BAD_REQUEST", "Missing X-Business-ID")
        
        if app_key != server_app_key:
            Log.info(f"{log_tag} invalid x-app-key header")
            
            return prepared_response(False, "UNAUTHORIZED", "Unauthorized")

        try:
            page = LegalPage.get_latest_published_by_type(business_id, args["page_type"])
            if not page:
                Log.info(f"{log_tag} No published legal page found for type: {args['page_type']}")
                return prepared_response(False, "NOT_FOUND", "Legal page not found")

            # Convert ObjectId fields to strings for JSON serialization
            page = stringify_object_ids(page)
            
            page.pop("user_id", None)
            page.pop("user__id", None)
            page.pop("business_id", None) 

            Log.info(f"{log_tag} Successfully retrieved legal page for type: {args['page_type']}")
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": page
            })
        except Exception as e:
            Log.error(f"[PublicLegalPageResource][get] Error retrieving legal page: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "An error occurred while retrieving the legal page")