# app/utils/feature_gate.py

from flask import g
from ..extensions.db import db
from ..utils.crypt import hash_data, decrypt_data
from ..utils.logger import Log
from bson import ObjectId


class FeatureNotAvailableError(Exception):
    """Raised when a feature is not available on the current plan."""

    def __init__(self, feature_key, current_tier, upgrade_tier=None):
        self.feature_key = feature_key
        self.current_tier = current_tier
        self.upgrade_tier = upgrade_tier
        self.message = f"'{self._humanise(feature_key)}' is not available on your {current_tier} plan."
        if upgrade_tier:
            self.message += f" Upgrade to {upgrade_tier} to unlock this feature."
        self.meta = {
            "feature": feature_key,
            "current_tier": current_tier,
            "available_on": upgrade_tier,
            "action_required": "upgrade",
        }
        super().__init__(self.message)

    @staticmethod
    def _humanise(key):
        return key.replace("_", " ").title()


# Feature → minimum tier required (for upgrade messaging)
FEATURE_TIER_MAP = {
    # Starter unlocks
    "paid_events": "Starter",
    "child_check_in_with_nametags": "Starter",
    "service_planning": "Starter",
    "pledges": "Starter",
    "email_designer": "Starter",
    "scheduled_communications": "Starter",
    "appointments": "Starter",
    "accounting": "Starter",
    "automated_tasks": "Starter",
    "workflow_approvals": "Starter",
    "sermon_management": "Starter",
    "worship_song_library": "Starter",
    "sacrament_records": "Starter",
    "data_import_export": "Starter",
    "custom_member_registration": "Starter",
    "profile_attachments": "Starter",

    # Small unlocks
    "sms_messaging": "Small",
    "push_notifications": "Small",
    "branch_management": "Small",
    "blog": "Small",
    "member_portal_builder": "Small",
    "conditional_profile_fields": "Small",
    "people_map": "Small",
    "audit_logs": "Small",
    "webhooks": "Small",
    "embed_widgets": "Small",
    "zapier": "Small",
    "mailchimp": "Small",
    "custom_reports_export": "Small",

    # Medium unlocks
    "api_access": "Medium",
    "advanced_reports": "Medium",
    "podcast_feed": "Medium",

    # Large unlocks
    "allow_custom_domain": "Large",
    "allow_multi_language": "Large",

    # Unlimited unlocks
    "allow_white_label_mobile_app": "Unlimited",
}


def _is_exempt_user() -> bool:
    """SYSTEM_OWNER bypasses all feature gates."""
    try:
        from ..constants.service_code import SYSTEM_USERS

        user_info = g.get("current_user", {}) or {}
        account_type = user_info.get("account_type", "")

        if account_type and isinstance(account_type, str) and len(account_type) > 30:
            try:
                account_type = decrypt_data(account_type)
            except Exception:
                pass

        result = (account_type or "").strip().lower() == SYSTEM_USERS["SYSTEM_OWNER"].strip().lower()

        Log.info(f"[_is_exempt_user] account_type='{account_type}', "
                 f"SYSTEM_OWNER='{SYSTEM_USERS['SYSTEM_OWNER']}', exempt={result}")

        return result

    except Exception as e:
        Log.error(f"[_is_exempt_user] EXCEPTION (returning False): {e}")
        return False


def get_business_package(business_id):
    """Get the active package for a business via its subscription."""
    try:
        from ..models.admin.subscription_model import Subscription
        from ..models.admin.package_model import Package

        sub = Subscription.get_active_by_business(str(business_id))
        if not sub:
            return None

        package_id = sub.get("package_id")
        if not package_id:
            return None

        return Package.get_by_id(package_id)
    except Exception as e:
        Log.error(f"[get_business_package] {e}")
        return None


def check_feature(business_id, feature_key):
    """
    Check if a feature is enabled for the business's current package.

    Args:
        business_id: The business ID
        feature_key: The feature key from the package features dict

    Returns:
        True if feature is enabled

    Raises:
        FeatureNotAvailableError if feature is disabled on current plan
    """
    # Exempt users bypass all feature gates
    if _is_exempt_user():
        return True

    package = get_business_package(business_id)

    if not package:
        # No package = no features (shouldn't happen if subscription check passed)
        raise FeatureNotAvailableError(
            feature_key, "Free",
            FEATURE_TIER_MAP.get(feature_key, "Starter"),
        )

    features = package.get("features", {})
    current_tier = package.get("tier", "Free")

    # Check in features dict
    if feature_key in features:
        if features[feature_key]:
            return True
        upgrade_tier = FEATURE_TIER_MAP.get(feature_key, "a higher")
        raise FeatureNotAvailableError(feature_key, current_tier, upgrade_tier)

    # Check in boolean flags (allow_custom_domain, etc.)
    flag_value = package.get(feature_key)
    if flag_value is not None:
        if flag_value:
            return True
        upgrade_tier = FEATURE_TIER_MAP.get(feature_key, "a higher")
        raise FeatureNotAvailableError(feature_key, current_tier, upgrade_tier)

    # Feature key not found in package — allow by default
    return True


def get_enabled_features(business_id):
    """Get all enabled features for a business (for the frontend to show/hide UI)."""
    package = get_business_package(business_id)

    if not package:
        return {"features": {}, "tier": "Free", "flags": {}}

    features = package.get("features", {})
    flags = {
        k: package.get(k, False)
        for k in [
            "allow_custom_domain",
            "allow_white_label_mobile_app",
            "allow_multi_language",
            "allow_sandbox_api_keys",
            "allow_live_api_keys",
        ]
    }

    return {
        "tier": package.get("tier", "Free"),
        "features": features,
        "flags": flags,
        "package_name": package.get("name"),
        "package_id": package.get("_id"),
    }


def get_disabled_features_with_upgrade_info(business_id):
    """Get all disabled features with which tier unlocks them (for upsell UI)."""
    package = get_business_package(business_id)

    if not package:
        return {"disabled": list(FEATURE_TIER_MAP.keys()), "tier": "Free"}

    features = package.get("features", {})
    current_tier = package.get("tier", "Free")

    disabled = []
    for key, required_tier in FEATURE_TIER_MAP.items():
        # Check features dict
        if key in features and not features[key]:
            disabled.append({
                "feature": key,
                "label": key.replace("_", " ").title(),
                "available_on": required_tier,
            })
        # Check boolean flags
        elif key.startswith("allow_") and not package.get(key, False):
            disabled.append({
                "feature": key,
                "label": key.replace("allow_", "").replace("_", " ").title(),
                "available_on": required_tier,
            })

    return {
        "disabled": disabled,
        "tier": current_tier,
        "count": len(disabled),
    }
