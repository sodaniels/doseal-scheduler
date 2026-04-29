# resources/church/integration_resource.py

import time
from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint

from ..doseal.admin.admin_business_resource import token_required
from ...decorators.permission_decorator import require_permission
from ...decorators.subscription_decorator import require_active_subscription
from ...models.base_model import SubscriptionError
from ...models.social.integration_model import Integration, Webhook, EmbedWidget
from ...models.social.branch_model import Branch
from ...schemas.social.integration_schema import (
    IntegrationCreateSchema, IntegrationUpdateSchema,
    IntegrationIdQuerySchema, IntegrationListQuerySchema,
    IntegrationByCategoryQuerySchema, IntegrationByProviderQuerySchema,
    IntegrationTestSchema, ProvidersQuerySchema,
    WebhookCreateSchema, WebhookUpdateSchema,
    WebhookIdQuerySchema, WebhookListQuerySchema, WebhookEventsQuerySchema,
    WidgetCreateSchema, WidgetUpdateSchema,
    WidgetIdQuerySchema, WidgetListQuerySchema, WidgetEmbedKeyQuerySchema,
)
from ...utils.json_response import prepared_response
from ...utils.helpers import make_log_tag, _resolve_business_id
from ...utils.logger import Log

from ...utils.feature_gate import check_feature


blp_integration = Blueprint("integrations", __name__, description="Third-party integrations, webhooks, and embed widgets")


def _validate_branch(branch_id, target_business_id, log_tag=None):
    branch = Branch.get_by_id(branch_id, target_business_id, processing_callback=True)
    if not branch:
        if log_tag:
            Log.info(f"{log_tag} branch not found: {branch_id}")
        return None
    return branch


def _rethrow_permission_or_500(e, message="An error occurred."):
    if isinstance(e, (PermissionError, SubscriptionError)):
        raise e
    return prepared_response(False, "INTERNAL_SERVER_ERROR", message, errors=[str(e)])


# ═══════════════════════════════════════════════════════════════
# AVAILABLE PROVIDERS
# ═══════════════════════════════════════════════════════════════

@blp_integration.route("/integrations/providers", methods=["GET"])
class ProvidersResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(ProvidersQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="List all supported integration providers with required fields", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            
            
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            providers = Integration.get_available_providers()
            return prepared_response(True, "OK", f"{len(providers)} provider(s).", data={"providers": providers, "count": len(providers)})
        except Exception as e:
            Log.error(f"[ProvidersResource][get] {e}")
            return _rethrow_permission_or_500(e)


# ═══════════════════════════════════════════════════════════════
# INTEGRATIONS — CRUD
# ═══════════════════════════════════════════════════════════════

@blp_integration.route("/integration", methods=["POST"])
class IntegrationCreateResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("integrations", "create")
    @blp_integration.arguments(IntegrationCreateSchema, location="json")
    @blp_integration.response(201)
    @blp_integration.doc(summary="Connect a third-party integration (payment, email, SMS, calendar, etc.)", security=[{"Bearer": []}])
    def post(self, json_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        target_business_id = _resolve_business_id(user_info, json_data.get("business_id"))
        log_tag = make_log_tag(
            "integration_resource.py", "IntegrationCreateResource", "post",
            client_ip, auth_user__id, user_info.get("account_type"),
            str(user_info.get("business_id")), target_business_id
        )

        if not _validate_branch(json_data["branch_id"], target_business_id, log_tag):
            return prepared_response(False, "NOT_FOUND", f"Branch '{json_data['branch_id']}' not found.")

        provider = json_data.get("provider")
        if provider not in Integration.PROVIDERS:
            Log.info(f"{log_tag} unknown provider: {provider}")
            return prepared_response(False, "BAD_REQUEST", f"Unknown provider '{provider}'. Use /integrations/providers to see available options.")

        existing = Integration.get_by_provider(target_business_id, provider, branch_id=json_data["branch_id"], processing_callback=True)
        if existing:
            Log.info(f"{log_tag} integration already exists for {provider}")
            return prepared_response(False, "CONFLICT", f"Integration for '{provider}' already exists for this branch.")

        provider_info = Integration.PROVIDERS[provider]
        creds = json_data.get("credentials", {})
        missing = [f for f in provider_info["requires"] if not creds.get(f)]
        if missing:
            return prepared_response(False, "BAD_REQUEST", f"Missing required credentials: {', '.join(missing)}")

        try:
            json_data["business_id"] = target_business_id
            json_data["user_id"] = user_info.get("user_id")
            json_data["user__id"] = auth_user__id

            Log.info(f"{log_tag} creating integration: {provider}")
            start_time = time.time()
            integration = Integration(**json_data)
            iid = integration.save()
            duration = time.time() - start_time
            Log.info(f"{log_tag} integration created: {iid} in {duration:.2f}s")

            if not iid:
                return prepared_response(False, "BAD_REQUEST", "Failed to create integration.")

            created = Integration.get_by_id(iid, target_business_id, processing_callback=True)
            return prepared_response(True, "CREATED", f"{provider_info['label']} integration created.", data=created)
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/integration", methods=["GET", "DELETE"])
class IntegrationGetDeleteResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(IntegrationIdQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Get an integration (credentials masked unless include_credentials=true)", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            Log.info(f"[IntegrationGetDeleteResource][get] retrieving integration: {qd['integration_id']}")
            i = Integration.get_by_id(
                qd["integration_id"],
                target_business_id,
                include_credentials=qd.get("include_credentials", False),
                processing_callback=True,
            )
            if not i:
                return prepared_response(False, "NOT_FOUND", "Integration not found.")
            return prepared_response(True, "OK", "Integration retrieved.", data=i)
        except Exception as e:
            Log.error(f"[IntegrationGetDeleteResource][get] {e}")
            return _rethrow_permission_or_500(e)

    @token_required
    @require_active_subscription()
    @require_permission("integrations", "delete")
    @blp_integration.arguments(IntegrationIdQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Delete an integration (disconnect)", security=[{"Bearer": []}])
    def delete(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            existing = Integration.get_by_id(qd["integration_id"], target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Integration not found.")

            Integration.delete(qd["integration_id"], target_business_id)
            Log.info(f"[IntegrationGetDeleteResource][delete] integration deleted: {qd['integration_id']}")
            return prepared_response(True, "OK", f"{existing.get('provider_label', 'Integration')} disconnected.")
        except Exception as e:
            Log.error(f"[IntegrationGetDeleteResource][delete] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/integration", methods=["PATCH"])
class IntegrationUpdateResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("integrations", "update")
    @blp_integration.arguments(IntegrationUpdateSchema, location="json")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Update integration credentials or settings", security=[{"Bearer": []}])
    def patch(self, d):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(d["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            iid = d.pop("integration_id")
            d.pop("branch_id", None)

            existing = Integration.get_by_id(iid, target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Integration not found.")

            Integration.update(iid, target_business_id, **d)
            updated = Integration.get_by_id(iid, target_business_id, processing_callback=True)
            Log.info(f"[IntegrationUpdateResource][patch] integration updated: {iid}")
            return prepared_response(True, "OK", "Integration updated.", data=updated)
        except Exception as e:
            Log.error(f"[IntegrationUpdateResource][patch] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/integrations", methods=["GET"])
class IntegrationListResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(IntegrationListQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="List all integrations (filter by category, status)", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info, qd.get("business_id"))
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            r = Integration.get_all(
                target_business_id,
                branch_id=qd["branch_id"],
                category=qd.get("category"),
                status=qd.get("status"),
                page=qd.get("page", 1),
                per_page=qd.get("per_page", 50),
                processing_callback=True,
            )
            if not r.get("integrations"):
                return prepared_response(False, "NOT_FOUND", "No integrations found.")
            return prepared_response(True, "OK", "Integrations.", data=r)
        except Exception as e:
            Log.error(f"[IntegrationListResource][get] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/integrations/by-category", methods=["GET"])
class IntegrationByCategoryResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(IntegrationByCategoryQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Get active integrations by category (e.g. all payment gateways)", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            items = Integration.get_active_by_category(
                target_business_id,
                qd["category"],
                branch_id=qd["branch_id"],
                processing_callback=True,
            )
            return prepared_response(True, "OK", f"{len(items)} active {qd['category']} integration(s).", data={"integrations": items, "count": len(items)})
        except Exception as e:
            Log.error(f"[IntegrationByCategoryResource][get] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/integration/by-provider", methods=["GET"])
class IntegrationByProviderResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(IntegrationByProviderQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Get integration for a specific provider (e.g. stripe)", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            i = Integration.get_by_provider(
                target_business_id,
                qd["provider"],
                branch_id=qd["branch_id"],
                processing_callback=True,
            )
            if not i:
                return prepared_response(False, "NOT_FOUND", f"No integration found for '{qd['provider']}'.")
            return prepared_response(True, "OK", "Integration.", data=i)
        except Exception as e:
            Log.error(f"[IntegrationByProviderResource][get] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/integration/test", methods=["POST"])
class IntegrationTestResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("integrations", "update")
    @blp_integration.arguments(IntegrationTestSchema, location="json")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Test an integration connection", security=[{"Bearer": []}])
    def post(self, d):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(d["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            existing = Integration.get_by_id(
                d["integration_id"],
                target_business_id,
                include_credentials=True,
                processing_callback=True,
            )
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Integration not found.")

            Log.info(f"[IntegrationTestResource][post] testing connection: {d['integration_id']} ({existing.get('provider')})")

            Integration.test_connection(d["integration_id"], target_business_id)

            updated = Integration.get_by_id(d["integration_id"], target_business_id, processing_callback=True)
            Log.info(f"[IntegrationTestResource][post] connection test passed: {d['integration_id']}")
            return prepared_response(True, "OK", "Connection test passed.", data=updated)
        except Exception as e:
            Log.error(f"[IntegrationTestResource][post] {e}")
            return _rethrow_permission_or_500(e)


# ═══════════════════════════════════════════════════════════════
# WEBHOOKS
# ═══════════════════════════════════════════════════════════════

@blp_integration.route("/webhook", methods=["POST"])
class WebhookCreateResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("integrations", "create")
    @blp_integration.arguments(WebhookCreateSchema, location="json")
    @blp_integration.response(201)
    @blp_integration.doc(summary="Create an outgoing webhook (fires on church events)", security=[{"Bearer": []}])
    def post(self, json_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        target_business_id = _resolve_business_id(user_info, json_data.get("business_id"))
        log_tag = make_log_tag(
            "integration_resource.py", "WebhookCreateResource", "post",
            client_ip, auth_user__id, user_info.get("account_type"),
            str(user_info.get("business_id")), target_business_id
        )

        if not _validate_branch(json_data["branch_id"], target_business_id, log_tag):
            return prepared_response(False, "NOT_FOUND", f"Branch '{json_data['branch_id']}' not found.")

        try:
            json_data["business_id"] = target_business_id
            json_data["user_id"] = user_info.get("user_id")
            json_data["user__id"] = auth_user__id

            Log.info(f"{log_tag} creating webhook: {json_data['target_url']}")
            wh = Webhook(**json_data)
            wid = wh.save()
            if not wid:
                return prepared_response(False, "BAD_REQUEST", "Failed to create webhook.")
            created = Webhook.get_by_id(wid, target_business_id, include_secret=True, processing_callback=True)
            Log.info(f"{log_tag} webhook created: {wid}")
            return prepared_response(True, "CREATED", "Webhook created.", data=created)
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/webhook", methods=["GET", "DELETE"])
class WebhookGetDeleteResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(WebhookIdQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Get a webhook", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            wh = Webhook.get_by_id(
                qd["webhook_id"],
                target_business_id,
                include_secret=qd.get("include_secret", False),
                processing_callback=True,
            )
            if not wh:
                return prepared_response(False, "NOT_FOUND", "Webhook not found.")
            return prepared_response(True, "OK", "Webhook retrieved.", data=wh)
        except Exception as e:
            Log.error(f"[WebhookGetDeleteResource][get] {e}")
            return _rethrow_permission_or_500(e)

    @token_required
    @require_active_subscription()
    @require_permission("integrations", "delete")
    @blp_integration.arguments(WebhookIdQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Delete a webhook", security=[{"Bearer": []}])
    def delete(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            existing = Webhook.get_by_id(qd["webhook_id"], target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Webhook not found.")

            Webhook.delete(qd["webhook_id"], target_business_id)
            Log.info(f"[WebhookGetDeleteResource][delete] webhook deleted: {qd['webhook_id']}")
            return prepared_response(True, "OK", "Webhook deleted.")
        except Exception as e:
            Log.error(f"[WebhookGetDeleteResource][delete] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/webhook", methods=["PATCH"])
class WebhookUpdateResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("integrations", "update")
    @blp_integration.arguments(WebhookUpdateSchema, location="json")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Update a webhook (URL, events, active status)", security=[{"Bearer": []}])
    def patch(self, d):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(d["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            wid = d.pop("webhook_id")
            d.pop("branch_id", None)

            existing = Webhook.get_by_id(wid, target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Webhook not found.")

            Webhook.update(wid, target_business_id, **d)
            updated = Webhook.get_by_id(wid, target_business_id, processing_callback=True)
            Log.info(f"[WebhookUpdateResource][patch] webhook updated: {wid}")
            return prepared_response(True, "OK", "Webhook updated.", data=updated)
        except Exception as e:
            Log.error(f"[WebhookUpdateResource][patch] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/webhooks", methods=["GET"])
class WebhookListResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(WebhookListQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="List webhooks", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info, qd.get("business_id"))
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            r = Webhook.get_all(
                target_business_id,
                branch_id=qd["branch_id"],
                is_active=qd.get("is_active"),
                page=qd.get("page", 1),
                per_page=qd.get("per_page", 50),
                processing_callback=True,
            )
            if not r.get("webhooks"):
                return prepared_response(False, "NOT_FOUND", "No webhooks found.")
            return prepared_response(True, "OK", "Webhooks.", data=r)
        except Exception as e:
            Log.error(f"[WebhookListResource][get] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/webhooks/events", methods=["GET"])
class WebhookEventsResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(WebhookEventsQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="List all available webhook event types", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")
            return prepared_response(True, "OK", f"{len(Webhook.EVENT_TYPES)} event type(s).", data={"event_types": Webhook.EVENT_TYPES, "count": len(Webhook.EVENT_TYPES)})
        except Exception as e:
            Log.error(f"[WebhookEventsResource][get] {e}")
            return _rethrow_permission_or_500(e)


# ═══════════════════════════════════════════════════════════════
# EMBED WIDGETS
# ═══════════════════════════════════════════════════════════════

@blp_integration.route("/embed-widget", methods=["POST"])
class WidgetCreateResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("integrations", "create")
    @blp_integration.arguments(WidgetCreateSchema, location="json")
    @blp_integration.response(201)
    @blp_integration.doc(summary="Create an embeddable widget for your website (calendar, giving, forms, events)", security=[{"Bearer": []}])
    def post(self, json_data):
        client_ip = request.remote_addr
        user_info = g.get("current_user", {}) or {}
        auth_user__id = str(user_info.get("_id"))
        target_business_id = _resolve_business_id(user_info, json_data.get("business_id"))
        log_tag = make_log_tag(
            "integration_resource.py", "WidgetCreateResource", "post",
            client_ip, auth_user__id, user_info.get("account_type"),
            str(user_info.get("business_id")), target_business_id
        )

        if not _validate_branch(json_data["branch_id"], target_business_id, log_tag):
            return prepared_response(False, "NOT_FOUND", f"Branch '{json_data['branch_id']}' not found.")

        try:
            json_data["business_id"] = target_business_id
            json_data["user_id"] = user_info.get("user_id")
            json_data["user__id"] = auth_user__id

            Log.info(f"{log_tag} creating embed widget: {json_data['widget_type']}")
            w = EmbedWidget(**json_data)
            wid = w.save()
            if not wid:
                return prepared_response(False, "BAD_REQUEST", "Failed to create widget.")
            created = EmbedWidget.get_by_id(wid, target_business_id, processing_callback=True)
            Log.info(f"{log_tag} widget created: {wid}")
            return prepared_response(True, "CREATED", "Embed widget created.", data=created)
        except Exception as e:
            Log.error(f"{log_tag} error: {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/embed-widget", methods=["GET", "DELETE"])
class WidgetGetDeleteResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(WidgetIdQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Get an embed widget with embed codes", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            w = EmbedWidget.get_by_id(qd["widget_id"], target_business_id, processing_callback=True)
            if not w:
                return prepared_response(False, "NOT_FOUND", "Widget not found.")
            return prepared_response(True, "OK", "Widget retrieved.", data=w)
        except Exception as e:
            Log.error(f"[WidgetGetDeleteResource][get] {e}")
            return _rethrow_permission_or_500(e)

    @token_required
    @require_active_subscription()
    @require_permission("integrations", "delete")
    @blp_integration.arguments(WidgetIdQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Delete an embed widget", security=[{"Bearer": []}])
    def delete(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            existing = EmbedWidget.get_by_id(qd["widget_id"], target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Widget not found.")

            EmbedWidget.delete(qd["widget_id"], target_business_id)
            Log.info(f"[WidgetGetDeleteResource][delete] widget deleted: {qd['widget_id']}")
            return prepared_response(True, "OK", "Widget deleted.")
        except Exception as e:
            Log.error(f"[WidgetGetDeleteResource][delete] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/embed-widget", methods=["PATCH"])
class WidgetUpdateResource(MethodView):
    @token_required
    @require_active_subscription()
    @require_permission("integrations", "update")
    @blp_integration.arguments(WidgetUpdateSchema, location="json")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Update an embed widget", security=[{"Bearer": []}])
    def patch(self, d):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info)
            if not _validate_branch(d["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            wid = d.pop("widget_id")
            d.pop("branch_id", None)

            existing = EmbedWidget.get_by_id(wid, target_business_id, processing_callback=True)
            if not existing:
                return prepared_response(False, "NOT_FOUND", "Widget not found.")

            EmbedWidget.update(wid, target_business_id, **d)
            updated = EmbedWidget.get_by_id(wid, target_business_id, processing_callback=True)
            Log.info(f"[WidgetUpdateResource][patch] widget updated: {wid}")
            return prepared_response(True, "OK", "Widget updated.", data=updated)
        except Exception as e:
            Log.error(f"[WidgetUpdateResource][patch] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/embed-widgets", methods=["GET"])
class WidgetListResource(MethodView):
    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_integration.arguments(WidgetListQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="List embed widgets", security=[{"Bearer": []}])
    def get(self, qd):
        try:
            user_info = g.get("current_user", {}) or {}
            target_business_id = _resolve_business_id(user_info, qd.get("business_id"))
            if not _validate_branch(qd["branch_id"], target_business_id):
                return prepared_response(False, "NOT_FOUND", "Branch not found.")

            r = EmbedWidget.get_all(
                target_business_id,
                branch_id=qd["branch_id"],
                widget_type=qd.get("widget_type"),
                page=qd.get("page", 1),
                per_page=qd.get("per_page", 50),
                processing_callback=True,
            )
            if not r.get("widgets"):
                return prepared_response(False, "NOT_FOUND", "No widgets found.")
            return prepared_response(True, "OK", "Embed widgets.", data=r)
        except Exception as e:
            Log.error(f"[WidgetListResource][get] {e}")
            return _rethrow_permission_or_500(e)


@blp_integration.route("/embed-widget/public", methods=["GET"])
class WidgetPublicResource(MethodView):
    @blp_integration.arguments(WidgetEmbedKeyQuerySchema, location="query")
    @blp_integration.response(200)
    @blp_integration.doc(summary="Public lookup by embed key (no auth required — for iframe/JS embed)", security=[])
    def get(self, qd):
        try:
            w = EmbedWidget.get_by_embed_key(qd["embed_key"], processing_callback=True)
            if not w:
                return prepared_response(False, "NOT_FOUND", "Widget not found or inactive.")
            EmbedWidget.increment_view(qd["embed_key"], processing_callback=True)
            Log.info(f"[WidgetPublicResource][get] public widget accessed: {qd['embed_key']}")
            return prepared_response(True, "OK", "Widget.", data=w)
        except Exception as e:
            Log.error(f"[WidgetPublicResource][get] {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "An error occurred.", errors=[str(e)])