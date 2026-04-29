from flask import g
from flask.views import MethodView
from flask_smorest import Blueprint

from ..doseal.admin.admin_business_resource import token_required
from ...decorators.permission_decorator import require_permission
from ...decorators.subscription_decorator import require_active_subscription
from ...models.social.integration_model import Integration
from ...models.social.provider_setting_model import ProviderSetting
from ...schemas.social.provider_setting_schema import (
    ProviderSettingUpsertSchema,
    ProviderSettingQuerySchema,
    ProviderSettingResponseSchema,
    EligibleProviderListQuerySchema,
)
from ...utils.helpers import _resolve_business_id
from ...utils.json_response import prepared_response
from ...utils.logger import Log


blp_provider_setting = Blueprint(
    "provider_settings",
    __name__,
    description="Default payment, SMS, email and WhatsApp provider settings",
)


def _validate_default_provider(business_id, provider, expected_category, branch_id=None):
    """
    Validate that:
      1. provider exists in Integration.PROVIDERS
      2. provider belongs to the correct category
      3. provider integration has been added for the business/branch
      4. integration is active
      5. required credentials are present
    """
    if not provider:
        return False, "Provider is required"

    provider_info = Integration.PROVIDERS.get(provider)
    if not provider_info:
        return False, f"Unknown provider '{provider}'"

    if provider_info.get("category") != expected_category:
        return False, (
            f"Provider '{provider}' is not a valid {expected_category.lower()} provider"
        )

    integration = Integration.get_by_provider(
        business_id=business_id,
        provider=provider,
        branch_id=branch_id,
        processing_callback=True,
    )

    if not integration:
        scope = "branch" if branch_id else "business"
        return False, f"Provider '{provider}' has not been added for this {scope}"

    if integration.get("status") != Integration.STATUS_ACTIVE:
        return False, f"Provider '{provider}' exists but is not active"

    credentials = integration.get("credentials", {}) or {}
    required_fields = provider_info.get("requires", []) or []

    missing = [field for field in required_fields if not credentials.get(field)]
    if missing:
        return False, (
            f"Provider '{provider}' is missing required credentials: "
            f"{', '.join(missing)}"
        )

    return True, None


def _get_eligible_providers_by_category(business_id, category, branch_id=None):
    """
    Returns only providers that:
      - belong to the category
      - have been added as integrations
      - are active
      - have required credentials
    """
    eligible = []

    for provider_key, provider_info in Integration.PROVIDERS.items():
        if provider_info.get("category") != category:
            continue

        integration = Integration.get_by_provider(
            business_id=business_id,
            provider=provider_key,
            branch_id=branch_id,
            processing_callback=True,
        )

        if not integration:
            continue

        if integration.get("status") != Integration.STATUS_ACTIVE:
            continue

        credentials = integration.get("credentials", {}) or {}
        required_fields = provider_info.get("requires", []) or []
        missing = [field for field in required_fields if not credentials.get(field)]

        if missing:
            continue

        eligible.append({
            "provider": provider_key,
            "label": provider_info.get("label", provider_key),
            "category": provider_info.get("category"),
        })

    return sorted(eligible, key=lambda x: x["label"])


@blp_provider_setting.route("/provider-settings", methods=["GET", "PUT", "PATCH"])
class ProviderSettingResource(MethodView):

    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_provider_setting.arguments(ProviderSettingQuerySchema, location="query")
    @blp_provider_setting.response(200, ProviderSettingResponseSchema)
    @blp_provider_setting.doc(
        summary="Get default providers for a business or branch",
        security=[{"Bearer": []}],
    )
    def get(self, query_data):
        try:
            user_info = g.get("current_user", {}) or {}
            business_id = _resolve_business_id(user_info)
            branch_id = query_data.get("branch_id")

            result = ProviderSetting.get_for_business(
                business_id=business_id,
                branch_id=branch_id,
                processing_callback=True,
            )

            if not result:
                return prepared_response(
                    True,
                    "OK",
                    "Provider settings not yet configured.",
                    data={},
                )

            return prepared_response(
                True,
                "OK",
                "Provider settings retrieved successfully.",
                data=result,
            )

        except Exception as e:
            Log.error(f"[ProviderSettingResource][get] {e}", exc_info=True)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred.",
                errors=[str(e)],
            )

    @token_required
    @require_active_subscription()
    @require_permission("integrations", "update")
    @blp_provider_setting.arguments(ProviderSettingUpsertSchema, location="json")
    @blp_provider_setting.response(200, ProviderSettingResponseSchema)
    @blp_provider_setting.doc(
        summary="Create or update default providers for a business or branch",
        security=[{"Bearer": []}],
    )
    def put(self, json_data):
        return self._upsert(json_data)

    @token_required
    @require_active_subscription()
    @require_permission("integrations", "update")
    @blp_provider_setting.arguments(ProviderSettingUpsertSchema, location="json")
    @blp_provider_setting.response(200, ProviderSettingResponseSchema)
    @blp_provider_setting.doc(
        summary="Partially update default providers for a business or branch",
        security=[{"Bearer": []}],
    )
    def patch(self, json_data):
        return self._upsert(json_data)

    def _upsert(self, json_data):
        try:
            user_info = g.get("current_user", {}) or {}
            business_id = _resolve_business_id(user_info)
            branch_id = json_data.get("branch_id")

            payment_provider = json_data.get("default_payment_provider")
            if payment_provider:
                ok, error = _validate_default_provider(
                    business_id=business_id,
                    provider=payment_provider,
                    expected_category=Integration.CAT_PAYMENT,
                    branch_id=branch_id,
                )
                if not ok:
                    return prepared_response(False, "BAD_REQUEST", error)

            sms_provider = json_data.get("default_sms_provider")
            if sms_provider:
                ok, error = _validate_default_provider(
                    business_id=business_id,
                    provider=sms_provider,
                    expected_category=Integration.CAT_SMS,
                    branch_id=branch_id,
                )
                if not ok:
                    return prepared_response(False, "BAD_REQUEST", error)

            email_provider = json_data.get("default_email_provider")
            if email_provider:
                ok, error = _validate_default_provider(
                    business_id=business_id,
                    provider=email_provider,
                    expected_category=Integration.CAT_EMAIL,
                    branch_id=branch_id,
                )
                if not ok:
                    return prepared_response(False, "BAD_REQUEST", error)

            whatsapp_provider = json_data.get("default_whatsapp_provider")
            if whatsapp_provider:
                ok, error = _validate_default_provider(
                    business_id=business_id,
                    provider=whatsapp_provider,
                    expected_category=Integration.CAT_WHATSAPP,
                    branch_id=branch_id,
                )
                if not ok:
                    return prepared_response(False, "BAD_REQUEST", error)

            updated = ProviderSetting.upsert_for_business(
                business_id=business_id,
                branch_id=branch_id,
                user_id=user_info.get("user_id"),
                user__id=str(user_info.get("_id")),
                default_payment_provider=json_data.get("default_payment_provider"),
                default_sms_provider=json_data.get("default_sms_provider"),
                default_email_provider=json_data.get("default_email_provider"),
                default_whatsapp_provider=json_data.get("default_whatsapp_provider"),
                processing_callback=True,
            )

            return prepared_response(
                True,
                "OK",
                "Provider settings saved successfully.",
                data=updated,
            )

        except Exception as e:
            Log.error(f"[ProviderSettingResource][_upsert] {e}", exc_info=True)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred.",
                errors=[str(e)],
            )


@blp_provider_setting.route("/provider-settings/eligible", methods=["GET"])
class EligibleProviderResource(MethodView):

    @token_required
    @require_active_subscription(allow_read=True)
    @require_permission("integrations", "read")
    @blp_provider_setting.arguments(EligibleProviderListQuerySchema, location="query")
    @blp_provider_setting.response(200)
    @blp_provider_setting.doc(
        summary="List providers that are eligible to be set as defaults",
        security=[{"Bearer": []}],
    )
    def get(self, query_data):
        try:
            user_info = g.get("current_user", {}) or {}
            business_id = _resolve_business_id(user_info)
            branch_id = query_data.get("branch_id")

            payment_providers = _get_eligible_providers_by_category(
                business_id=business_id,
                category=Integration.CAT_PAYMENT,
                branch_id=branch_id,
            )

            sms_providers = _get_eligible_providers_by_category(
                business_id=business_id,
                category=Integration.CAT_SMS,
                branch_id=branch_id,
            )

            email_providers = _get_eligible_providers_by_category(
                business_id=business_id,
                category=Integration.CAT_EMAIL,
                branch_id=branch_id,
            )

            whatsapp_providers = _get_eligible_providers_by_category(
                business_id=business_id,
                category=Integration.CAT_WHATSAPP,
                branch_id=branch_id,
            )

            return prepared_response(
                True,
                "OK",
                "Eligible providers retrieved successfully.",
                data={
                    "payment_providers": payment_providers,
                    "sms_providers": sms_providers,
                    "email_providers": email_providers,
                    "whatsapp_providers": whatsapp_providers,
                },
            )

        except Exception as e:
            Log.error(f"[EligibleProviderResource][get] {e}", exc_info=True)
            return prepared_response(
                False,
                "INTERNAL_SERVER_ERROR",
                "An error occurred.",
                errors=[str(e)],
            )