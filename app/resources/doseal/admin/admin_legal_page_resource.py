# app/resources/doseal/admin/admin_legal_page_resource.py

from flask.views import MethodView
from flask_smorest import Blueprint
from flask import g, jsonify, request
from pymongo.errors import PyMongoError
import time

from ....models.social.legal_page_model import LegalPage
from ....schemas.social.legal_page_schema import (
    LegalPageCreateSchema,
    LegalPageUpdateSchema,
    LegalPageListSchema,
)
from ....constants.service_code import HTTP_STATUS_CODES
from ....utils.json_response import prepared_response
from ....utils.logger import Log
from .admin_business_resource import token_required
from ....utils.helpers import stringify_object_ids

blp_legal_admin = Blueprint(
    "Admin Legal Pages",
    __name__,
    description="Admin Legal Page Management"
)

# ---------------------------------------------------------------------
# CREATE / UPDATE / LIST LEGAL PAGES
# ---------------------------------------------------------------------
@blp_legal_admin.route("/admin/legal-pages")
class AdminLegalPagesResource(MethodView):

    # -------------------- CREATE --------------------
    @token_required
    @blp_legal_admin.arguments(LegalPageCreateSchema, location="form")
    def post(self, data):
        log_tag = "[admin_legal_page_resource.py][AdminLegalPagesResource][post]"
        client_ip = request.remote_addr

        try:
            user = g.get("current_user")
            business_id = user["business_id"]

            Log.info(f"{log_tag}[{client_ip}] creating legal page")

            page = LegalPage(
                business_id=business_id,
                page_type=data["page_type"],
                title=data["title"],
                content=data["content"],
                version=data.get("version", "1.0"),
                created_by=user["_id"]
            )

            start_time = time.time()
            page_id = page.save()
            duration = time.time() - start_time

            Log.info(
                f"{log_tag}[{client_ip}][{page_id}] "
                f"legal page created in {duration:.2f}s"
            )

            return prepared_response(
                True,
                "OK",
                "Legal page created successfully",
                {"page_id": str(page_id)}
            )

        except PyMongoError as e:
            Log.error(f"{log_tag}[{client_ip}] database error: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Database error while creating legal page"
            )

        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}] unexpected error: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred"
            )

    # -------------------- UPDATE --------------------
    @token_required
    @blp_legal_admin.arguments(LegalPageUpdateSchema, location="form")
    def patch(self, data):
        log_tag = "[admin_legal_page_resource.py][AdminLegalPagesResource][patch]"
        client_ip = request.remote_addr

        try:
            business_id = g.current_user["business_id"]
            page_id = data.pop("page_id")

            Log.info(
                f"{log_tag}[{client_ip}][{page_id}] updating legal page"
            )

            start_time = time.time()
            updated = LegalPage.update(page_id, business_id, **data)
            duration = time.time() - start_time

            if not updated:
                Log.info(
                    f"{log_tag}[{client_ip}][{page_id}] legal page not found"
                )
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Legal page not found"
                )

            Log.info(
                f"{log_tag}[{client_ip}][{page_id}] "
                f"legal page updated in {duration:.2f}s"
            )

            return prepared_response(
                True,
                "OK",
                "Legal page updated successfully"
            )

        except PyMongoError as e:
            Log.error(
                f"{log_tag}[{client_ip}][{page_id}] database error: {e}"
            )
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Database error while updating legal page"
            )

        except Exception as e:
            Log.error(
                f"{log_tag}[{client_ip}][{page_id}] unexpected error: {e}"
            )
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred"
            )

    # -------------------- LIST --------------------
    @token_required
    def get(self):
        log_tag = "[admin_legal_page_resource.py][AdminLegalPagesResource][get]"
        client_ip = request.remote_addr

        try:
            business_id = g.current_user["business_id"]

            Log.info(
                f"{log_tag}[{client_ip}] retrieving legal pages"
            )

            start_time = time.time()
            pages = LegalPage.list_pages(business_id)
            duration = time.time() - start_time

            pages = [stringify_object_ids(p) for p in pages]

            Log.info(
                f"{log_tag}[{client_ip}] "
                f"retrieved {len(pages)} legal pages in {duration:.2f}s"
            )

            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": pages
            })

        except PyMongoError as e:
            Log.error(f"{log_tag}[{client_ip}] database error: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Database error while retrieving legal pages"
            )

        except Exception as e:
            Log.error(f"{log_tag}[{client_ip}] unexpected error: {e}")
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred"
            )

# ---------------------------------------------------------------------
# PUBLISH LEGAL PAGE (VERSION-SAFE)
# ---------------------------------------------------------------------
@blp_legal_admin.route("/admin/legal-pages/<page_id>/publish")
class PublishLegalPageResource(MethodView):

    @token_required
    def post(self, page_id):
        log_tag = "[admin_legal_page_resource.py][PublishLegalPageResource][post]"
        client_ip = request.remote_addr

        try:
            business_id = g.current_user["business_id"]

            Log.info(
                f"{log_tag}[{client_ip}][{page_id}] publishing legal page"
            )

            start_time = time.time()
            published = LegalPage.publish(page_id, business_id)
            duration = time.time() - start_time

            if not published:
                Log.info(
                    f"{log_tag}[{client_ip}][{page_id}] legal page not found"
                )
                return prepared_response(
                    False,
                    "NOT_FOUND",
                    "Legal page not found"
                )

            Log.info(
                f"{log_tag}[{client_ip}][{page_id}] "
                f"legal page published in {duration:.2f}s"
            )

            return prepared_response(
                True,
                "OK",
                "Legal page published successfully"
            )

        except PyMongoError as e:
            Log.error(
                f"{log_tag}[{client_ip}][{page_id}] database error: {e}"
            )
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "Database error while publishing legal page"
            )

        except Exception as e:
            Log.error(
                f"{log_tag}[{client_ip}][{page_id}] unexpected error: {e}"
            )
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An unexpected error occurred"
            )