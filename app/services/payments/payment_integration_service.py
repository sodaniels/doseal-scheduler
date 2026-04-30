from __future__ import annotations

from typing import Optional, Dict, Any

from ...models.social.integration_model import Integration
from ...models.social.provider_setting_model import ProviderSetting
from ...utils.logger import Log


class PaymentIntegrationService:
    """
    Resolve active payment gateway integrations configured from the portal.
    """

    SUPPORTED_PAYMENT_PROVIDERS = [
        "paystack",
        "hubtel",
        "asoriba",
        "flutterwave",
        "mpesa",
        "stripe",
        "paypal",
    ]

    @classmethod
    def get_provider_credentials(cls, business_id, branch_id=None, preferred_provider=None):
        """
        Resolution order:
        1. explicit preferred_provider from request
        2. branch-level default provider from provider_settings
        3. business-level default provider from provider_settings
        4. first active payment integration
        """
        log_tag = "[PaymentIntegrationService][get_provider_credentials]"

        try:
            business_id = str(business_id)
            branch_id = str(branch_id) if branch_id else None
            preferred_provider = str(preferred_provider).strip().lower() if preferred_provider else None

            Log.info(
                f"{log_tag} start "
                f"business_id={business_id}, branch_id={branch_id}, preferred_provider={preferred_provider}"
            )

            provider_to_use = None

            if preferred_provider:
                provider_to_use = preferred_provider
                Log.info(f"{log_tag} using explicit provider={provider_to_use}")

            if not provider_to_use and branch_id:
                branch_setting = ProviderSetting.get_for_business(
                    business_id=business_id,
                    branch_id=branch_id,
                    processing_callback=True,
                )
                Log.info(f"{log_tag} branch_setting={branch_setting}")

                if branch_setting and branch_setting.get("default_payment_provider"):
                    provider_to_use = str(
                        branch_setting.get("default_payment_provider")
                    ).strip().lower()
                    Log.info(f"{log_tag} using branch default provider={provider_to_use}")

            if not provider_to_use:
                business_setting = ProviderSetting.get_for_business(
                    business_id=business_id,
                    branch_id=None,
                    processing_callback=True,
                )
                Log.info(f"{log_tag} business_setting={business_setting}")

                if business_setting and business_setting.get("default_payment_provider"):
                    provider_to_use = str(
                        business_setting.get("default_payment_provider")
                    ).strip().lower()
                    Log.info(f"{log_tag} using business default provider={provider_to_use}")

            if not provider_to_use:
                for candidate in cls.SUPPORTED_PAYMENT_PROVIDERS:
                    integration = Integration.get_by_provider(
                        business_id=business_id,
                        provider=candidate,
                        branch_id=branch_id,
                        processing_callback=True,
                    )
                    if integration and integration.get("status") == Integration.STATUS_ACTIVE:
                        provider_to_use = candidate
                        Log.info(f"{log_tag} fallback first active provider={provider_to_use}")
                        break

                if not provider_to_use and branch_id:
                    for candidate in cls.SUPPORTED_PAYMENT_PROVIDERS:
                        integration = Integration.get_by_provider(
                            business_id=business_id,
                            provider=candidate,
                            branch_id=None,
                            processing_callback=True,
                        )
                        if integration and integration.get("status") == Integration.STATUS_ACTIVE:
                            provider_to_use = candidate
                            Log.info(f"{log_tag} fallback business-wide active provider={provider_to_use}")
                            break

            if not provider_to_use:
                Log.warning(f"{log_tag} no provider resolved")
                return None, {}, {}, "No active payment integration found"

            if provider_to_use not in cls.SUPPORTED_PAYMENT_PROVIDERS:
                Log.warning(f"{log_tag} unsupported provider selected={provider_to_use}")
                return None, {}, {}, f"Unsupported payment provider '{provider_to_use}'"

            integration = Integration.get_by_provider(
                business_id=business_id,
                provider=provider_to_use,
                branch_id=branch_id,
                processing_callback=True,
            )
            Log.info(f"{log_tag} branch integration={integration}")

            if not integration and branch_id:
                integration = Integration.get_by_provider(
                    business_id=business_id,
                    provider=provider_to_use,
                    branch_id=None,
                    processing_callback=True,
                )
                Log.info(f"{log_tag} business integration fallback={integration}")

            if not integration:
                return None, {}, {}, (
                    f"Provider '{provider_to_use}' is selected in provider settings "
                    f"but no integration exists"
                )

            if integration.get("status") != Integration.STATUS_ACTIVE:
                return None, {}, {}, f"Provider '{provider_to_use}' exists but is not active"

            credentials = integration.get("credentials", {}) or {}
            settings = integration.get("settings", {}) or {}

            Log.info(
                f"{log_tag} resolved provider={provider_to_use}, "
                f"has_credentials={bool(credentials)}, has_settings={bool(settings)}"
            )

            return provider_to_use, credentials, settings, None

        except Exception as e:
            Log.error(f"{log_tag} Error: {e}", exc_info=True)
            return None, {}, {}, str(e)