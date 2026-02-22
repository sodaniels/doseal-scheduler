# app/resources/doseal/admin/admin_legal_page_resource.py

from flask.views import MethodView
from flask_smorest import Blueprint
from flask import g, jsonify
from pymongo.errors import PyMongoError

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

@blp_legal_admin.route("/admin/legal-pages")
class AdminLegalPagesResource(MethodView):

    @token_required
    @blp_legal_admin.arguments(LegalPageCreateSchema)
    def post(self, data):
        user = g.get("current_user")
        business_id = user["business_id"]

        page = LegalPage(
            business_id=business_id,
            page_type=data["page_type"],
            title=data["title"],
            content=data["content"],
            version=data.get("version", "1.0"),
            created_by=user["_id"]
        )

        page_id = page.save()
        return prepared_response(True, "OK", "Legal page created", {"page_id": str(page_id)})

    @token_required
    @blp_legal_admin.arguments(LegalPageUpdateSchema)
    def patch(self, data):
        business_id = g.current_user["business_id"]
        page_id = data.pop("page_id")

        updated = LegalPage.update(page_id, business_id, **data)
        if not updated:
            return prepared_response(False, "NOT_FOUND", "Legal page not found")

        return prepared_response(True, "OK", "Legal page updated")

    @token_required
    def get(self):
        business_id = g.current_user["business_id"]
        pages = LegalPage.list_pages(business_id)

        for p in pages:
            p = stringify_object_ids(p)

        return jsonify({
            "success": True,
            "status_code": HTTP_STATUS_CODES["OK"],
            "data": pages
        })
        
@blp_legal_admin.route("/admin/legal-pages/<page_id>/publish")
class PublishLegalPageResource(MethodView):

    @token_required
    def post(self, page_id):
        business_id = g.current_user["business_id"]

        published = LegalPage.publish(page_id, business_id)
        if not published:
            return prepared_response(False, "NOT_FOUND", "Legal page not found")

        return prepared_response(True, "OK", "Legal page published")
    
