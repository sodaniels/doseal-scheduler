# app/models/church/integration_model.py

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict
from bson import ObjectId
import uuid

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


# ═══════════════════════════════════════════════════════════════
# INTEGRATION
# ═══════════════════════════════════════════════════════════════

class Integration(BaseModel):
    """
    Third-party integration configuration.
    Stores credentials (encrypted), connection status, and provider-specific settings.
    """

    collection_name = "integrations"
    _permission_module = "integrations"

    CAT_PAYMENT = "Payment Gateway"
    CAT_EMAIL = "Email Marketing"
    CAT_SMS = "SMS Provider"
    CAT_WHATSAPP = "WhatsApp"
    CAT_CALENDAR = "Calendar Sync"
    CAT_ACCOUNTING = "Accounting Export"
    CAT_AUTOMATION = "Automation"
    CAT_CUSTOM = "Custom"

    CATEGORIES = [CAT_PAYMENT, CAT_EMAIL, CAT_SMS, CAT_WHATSAPP, CAT_CALENDAR, CAT_ACCOUNTING, CAT_AUTOMATION, CAT_CUSTOM]

    PROVIDERS = {
        "stripe": {"category": CAT_PAYMENT, "label": "Stripe", "requires": ["api_key", "secret_key"], "optional": ["webhook_secret"], "supports_webhooks": True},
        "paypal": {"category": CAT_PAYMENT, "label": "PayPal", "requires": ["client_id", "client_secret"], "optional": ["webhook_id"], "supports_webhooks": True},
        "paystack": {"category": CAT_PAYMENT, "label": "Paystack", "requires": ["public_key", "secret_key"], "optional": ["webhook_secret"], "supports_webhooks": True},
        "flutterwave": {"category": CAT_PAYMENT, "label": "Flutterwave", "requires": ["public_key", "secret_key"], "optional": ["encryption_key"], "supports_webhooks": True},
        "mpesa": {"category": CAT_PAYMENT, "label": "M-Pesa", "requires": ["consumer_key", "consumer_secret", "shortcode", "passkey"], "optional": ["callback_url"], "supports_webhooks": True},
        "smsglobal": { "category": CAT_SMS, "label": "SMSGlobal", "requires": ["api_key", "secret_key"], "optional": ["from_name", "timeout_seconds"], "supports_webhooks": False, },
        "hubtel": {"category": CAT_PAYMENT, "label": "Hubtel", "requires": ["client_id", "client_secret", "merchant_account"], "optional": [], "supports_webhooks": True},
        "mailchimp": {"category": CAT_EMAIL, "label": "Mailchimp", "requires": ["api_key"], "optional": ["server_prefix", "list_id"], "supports_webhooks": True},
        "sendgrid": {"category": CAT_EMAIL, "label": "SendGrid", "requires": ["api_key"], "optional": ["from_email", "from_name"], "supports_webhooks": True},
        "twilio": {"category": CAT_SMS, "label": "Twilio", "requires": ["account_sid", "auth_token", "from_number"], "optional": ["messaging_service_sid"], "supports_webhooks": True},
        "infobip": { "category": CAT_SMS, "label": "Infobip", "requires": ["base_url", "api_key", "sender_id"], "optional": ["timeout_seconds"], "supports_webhooks": True, },
        "asoriba": { "category": CAT_PAYMENT, "label": "Asoriba", "requires": ["public_key"], "optional": ["callback_url", "post_url", "return_url"], "supports_webhooks": True, },
        "smsglobal": {"category": CAT_SMS, "label": "SMSGlobal", "requires": ["api_key", "secret_key"], "optional": ["from_name"], "supports_webhooks": False},
        "clickatell": {"category": CAT_SMS, "label": "Clickatell", "requires": ["api_key"], "optional": ["from_number"], "supports_webhooks": True},
        "hubtel_sms": {"category": CAT_SMS, "label": "Hubtel SMS", "requires": ["client_id", "client_secret", "sender_id"], "optional": ["callback_url"], "supports_webhooks": True},
        "whatsapp_business": {"category": CAT_WHATSAPP, "label": "WhatsApp Business API", "requires": ["access_token", "phone_number_id", "business_account_id"], "optional": ["webhook_verify_token"], "supports_webhooks": True},
        "google_calendar": {"category": CAT_CALENDAR, "label": "Google Calendar", "requires": ["client_id", "client_secret"], "optional": ["calendar_id", "refresh_token"], "supports_webhooks": False},
        "outlook_calendar": {"category": CAT_CALENDAR, "label": "Outlook Calendar", "requires": ["client_id", "client_secret", "tenant_id"], "optional": ["calendar_id", "refresh_token"], "supports_webhooks": False},
        "quickbooks": {"category": CAT_ACCOUNTING, "label": "QuickBooks", "requires": ["client_id", "client_secret"], "optional": ["realm_id", "refresh_token"], "supports_webhooks": True},
        "xero": {"category": CAT_ACCOUNTING, "label": "Xero", "requires": ["client_id", "client_secret"], "optional": ["tenant_id", "refresh_token"], "supports_webhooks": True},
        "csv_export": {"category": CAT_ACCOUNTING, "label": "CSV/Excel Export", "requires": [], "optional": ["export_format", "date_format", "delimiter"], "supports_webhooks": False},
        "zapier": {"category": CAT_AUTOMATION, "label": "Zapier", "requires": [], "optional": ["webhook_url"], "supports_webhooks": True},
        "make": {"category": CAT_AUTOMATION, "label": "Make (Integromat)", "requires": [], "optional": ["webhook_url"], "supports_webhooks": True},
        "mailgun_email": { "category": CAT_EMAIL, "label": "Mailgun", "requires": ["api_key", "domain"], "optional": ["from_email", "from_name"], "supports_webhooks": False, },
        "custom_smtp": { "category": CAT_EMAIL, "label": "Custom SMTP", "requires": ["host", "username", "password"], "optional": ["port", "from_email", "from_name", "use_tls"], "supports_webhooks": False, },
        "sendgrid_email": { "category": CAT_EMAIL, "label": "SendGrid", "requires": ["api_key", "from_email"], "optional": ["from_name"], "supports_webhooks": False, },
    }

    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_ERROR = "Error"
    STATUS_PENDING = "Pending"
    STATUSES = [STATUS_ACTIVE, STATUS_INACTIVE, STATUS_ERROR, STATUS_PENDING]

    FIELDS_TO_DECRYPT = ["display_name"]

    def __init__(
        self,
        provider,
        branch_id,
        display_name=None,
        credentials=None,
        settings=None,
        status="Inactive",
        is_live=False,
        webhook_url=None,
        last_connected_at=None,
        last_error=None,
        user_id=None,
        user__id=None,
        business_id=None,
        **kw,
    ):
        super().__init__(user__id=user__id, user_id=user_id, business_id=business_id, **kw)
        self.business_id = ObjectId(business_id) if business_id else None
        self.branch_id = ObjectId(branch_id) if branch_id else None

        self.provider = provider
        provider_info = self.PROVIDERS.get(provider, {})
        self.category = provider_info.get("category", self.CAT_CUSTOM)
        self.provider_label = provider_info.get("label", provider)

        if display_name:
            self.display_name = encrypt_data(display_name)

        self.credentials = {}
        if credentials and isinstance(credentials, dict):
            for k, v in credentials.items():
                if v is not None and v != "":
                    self.credentials[k] = encrypt_data(str(v))

        self.settings = settings or {}
        self.status = status
        self.hashed_status = hash_data(status.strip())
        self.is_live = bool(is_live)

        if webhook_url:
            self.webhook_url = webhook_url
        if last_error:
            self.last_error = last_error

        self.last_connected_at = last_connected_at
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "branch_id": self.branch_id,
            "provider": self.provider,
            "category": self.category,
            "provider_label": self.provider_label,
            "display_name": getattr(self, "display_name", None),
            "credentials": self.credentials,
            "settings": self.settings,
            "status": self.status,
            "hashed_status": self.hashed_status,
            "is_live": self.is_live,
            "webhook_url": getattr(self, "webhook_url", None),
            "last_connected_at": self.last_connected_at,
            "last_error": getattr(self, "last_error", None),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {k: v for k, v in doc.items() if v is not None}

    @staticmethod
    def _safe_decrypt(v):
        if v is None:
            return None
        if not isinstance(v, str):
            return v
        try:
            return decrypt_data(v)
        except Exception:
            return v

    @classmethod
    def _mask_credential(cls, value):
        if not value or len(value) < 8:
            return "****"
        return f"****{value[-4:]}"

    @classmethod
    def _normalise(cls, doc, include_credentials=False):
        if not doc:
            return None

        for f in ["_id", "business_id", "branch_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])

        for f in cls.FIELDS_TO_DECRYPT:
            if f in doc:
                doc[f] = cls._safe_decrypt(doc[f])

        doc.pop("hashed_status", None)

        creds = doc.get("credentials", {})
        if include_credentials:
            doc["credentials"] = {k: cls._safe_decrypt(v) for k, v in creds.items()}
        else:
            doc["credentials_masked"] = {k: cls._mask_credential(cls._safe_decrypt(v)) for k, v in creds.items()}
            doc.pop("credentials", None)

        provider = doc.get("provider", "")
        provider_info = cls.PROVIDERS.get(provider, {})
        doc["required_fields"] = provider_info.get("requires", [])
        doc["optional_fields"] = provider_info.get("optional", [])
        doc["supports_webhooks"] = provider_info.get("supports_webhooks", False)

        return doc

    @classmethod
    def get_by_id(cls, integration_id, business_id=None, include_credentials=False, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"_id": ObjectId(integration_id)}
            if business_id:
                q["business_id"] = ObjectId(business_id)
            return cls._normalise(c.find_one(q), include_credentials=include_credentials)
        except Exception as e:
            Log.error(f"[Integration.get_by_id] {e}")
            return None

    @classmethod
    def get_by_provider(cls, business_id, provider, branch_id=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id), "provider": provider}
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            return cls._normalise(c.find_one(q), include_credentials=True)
        except Exception as e:
            Log.error(f"[Integration.get_by_provider] {e}")
            return None

    @classmethod
    def get_active_by_category(cls, business_id, category, branch_id=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {
                "business_id": ObjectId(business_id),
                "category": category,
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
            }
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            cursor = c.find(q).sort("provider_label", 1)
            return [cls._normalise(d) for d in cursor]
        except Exception as e:
            Log.error(f"[Integration.get_active_by_category] {e}")
            return []

    @classmethod
    def get_all(cls, business_id, branch_id=None, category=None, status=None, page=1, per_page=50, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id)}
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            if category:
                q["category"] = category
            if status:
                q["hashed_status"] = hash_data(status.strip())
            total = c.count_documents(q)
            cursor = c.find(q).sort("category", 1).skip((page - 1) * per_page).limit(per_page)
            return {
                "integrations": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[Integration.get_all] {e}")
            return {"integrations": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def test_connection(cls, integration_id, business_id, processing_callback=False):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            c.update_one(
                {"_id": ObjectId(integration_id), "business_id": ObjectId(business_id)},
                {"$set": {
                    "last_connected_at": datetime.utcnow(),
                    "status": cls.STATUS_ACTIVE,
                    "hashed_status": hash_data(cls.STATUS_ACTIVE),
                    "last_error": None,
                    "updated_at": datetime.utcnow(),
                }},
            )
            return True
        except Exception:
            return False

    @classmethod
    def mark_error(cls, integration_id, business_id, error_message, processing_callback=False):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            c.update_one(
                {"_id": ObjectId(integration_id), "business_id": ObjectId(business_id)},
                {"$set": {
                    "status": cls.STATUS_ERROR,
                    "hashed_status": hash_data(cls.STATUS_ERROR),
                    "last_error": error_message,
                    "updated_at": datetime.utcnow(),
                }},
            )
        except Exception:
            pass

    @classmethod
    def update(cls, integration_id, business_id, processing_callback=False, **updates):
        cls._enforce_permission("update", skip=processing_callback)
        updates["updated_at"] = datetime.utcnow()
        updates = {k: v for k, v in updates.items() if v is not None}
        if "display_name" in updates and updates["display_name"]:
            updates["display_name"] = encrypt_data(updates["display_name"])
        if "status" in updates and updates["status"]:
            updates["hashed_status"] = hash_data(updates["status"].strip())
        if "credentials" in updates and isinstance(updates["credentials"], dict):
            updates["credentials"] = {
                k: encrypt_data(str(v))
                for k, v in updates["credentials"].items()
                if v is not None and v != ""
            }
        for oid in ["branch_id"]:
            if oid in updates and updates[oid]:
                updates[oid] = ObjectId(updates[oid])
        return super().update(integration_id, business_id, **updates)

    @classmethod
    def get_available_providers(cls):
        providers = []
        for key, info in cls.PROVIDERS.items():
            providers.append({
                "provider": key,
                "label": info["label"],
                "category": info["category"],
                "required_fields": info["requires"],
                "optional_fields": info["optional"],
                "supports_webhooks": info["supports_webhooks"],
            })
        return sorted(providers, key=lambda x: (x["category"], x["label"]))

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("business_id", 1), ("branch_id", 1), ("provider", 1)], unique=True)
            c.create_index([("business_id", 1), ("category", 1), ("hashed_status", 1)])
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════
# WEBHOOK
# ═══════════════════════════════════════════════════════════════

class Webhook(BaseModel):
    """
    Outgoing webhook configuration.
    Fires on church events to external URLs.
    """

    collection_name = "webhooks"
    _permission_module = "integrations"

    EVENT_TYPES = [
        "member.created", "member.updated", "member.deleted",
        "donation.created", "donation.refunded",
        "event.created", "event.registration",
        "attendance.recorded",
        "form.submitted",
        "pledge.created", "pledge.payment",
        "volunteer.signup", "volunteer.rsvp",
        "sacrament.created",
        "workflow.submitted", "workflow.approved", "workflow.rejected",
    ]

    def __init__(
        self,
        name,
        target_url,
        event_types,
        branch_id,
        secret=None,
        is_active=True,
        headers=None,
        retry_count=3,
        user_id=None,
        user__id=None,
        business_id=None,
        **kw,
    ):
        super().__init__(user__id=user__id, user_id=user_id, business_id=business_id, **kw)
        self.business_id = ObjectId(business_id) if business_id else None
        self.branch_id = ObjectId(branch_id) if branch_id else None

        self.name = name
        self.target_url = target_url
        self.event_types = event_types or []
        self.secret = encrypt_data(secret or uuid.uuid4().hex)
        self.is_active = bool(is_active)
        self.headers = headers or {}
        self.retry_count = int(retry_count)

        self.total_deliveries = 0
        self.successful_deliveries = 0
        self.failed_deliveries = 0
        self.last_delivery_at = None
        self.last_response_code = None

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "branch_id": self.branch_id,
            "name": self.name,
            "target_url": self.target_url,
            "event_types": self.event_types,
            "secret": self.secret,
            "is_active": self.is_active,
            "headers": self.headers,
            "retry_count": self.retry_count,
            "total_deliveries": self.total_deliveries,
            "successful_deliveries": self.successful_deliveries,
            "failed_deliveries": self.failed_deliveries,
            "last_delivery_at": self.last_delivery_at,
            "last_response_code": self.last_response_code,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {k: v for k, v in doc.items() if v is not None}

    @classmethod
    def _normalise(cls, doc, include_secret=False):
        if not doc:
            return None
        for f in ["_id", "business_id", "branch_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])

        if include_secret:
            secret_enc = doc.get("secret")
            if secret_enc:
                try:
                    doc["secret"] = decrypt_data(secret_enc)
                except Exception:
                    pass
        else:
            doc.pop("secret", None)

        success_rate = 0
        total = doc.get("total_deliveries", 0)
        if total > 0:
            success_rate = round((doc.get("successful_deliveries", 0) / total) * 100, 1)
        doc["success_rate_percent"] = success_rate

        return doc

    @classmethod
    def get_by_id(cls, webhook_id, business_id=None, include_secret=False, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"_id": ObjectId(webhook_id)}
            if business_id:
                q["business_id"] = ObjectId(business_id)
            return cls._normalise(c.find_one(q), include_secret=include_secret)
        except Exception as e:
            Log.error(f"[Webhook.get_by_id] {e}")
            return None

    @classmethod
    def get_all(cls, business_id, branch_id=None, is_active=None, page=1, per_page=50, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id)}
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            if is_active is not None:
                q["is_active"] = is_active
            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            return {
                "webhooks": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[Webhook.get_all] {e}")
            return {"webhooks": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def get_active_for_event(cls, business_id, event_type, branch_id=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id), "is_active": True, "event_types": event_type}
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            cursor = c.find(q)
            return [cls._normalise(d, include_secret=True) for d in cursor]
        except Exception as e:
            Log.error(f"[Webhook.get_active_for_event] {e}")
            return []

    @classmethod
    def record_delivery(cls, webhook_id, business_id, success, response_code=None, processing_callback=False):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            inc = {"total_deliveries": 1}
            if success:
                inc["successful_deliveries"] = 1
            else:
                inc["failed_deliveries"] = 1
            c.update_one(
                {"_id": ObjectId(webhook_id), "business_id": ObjectId(business_id)},
                {"$inc": inc, "$set": {
                    "last_delivery_at": datetime.utcnow(),
                    "last_response_code": response_code,
                    "updated_at": datetime.utcnow(),
                }},
            )
        except Exception:
            pass

    @classmethod
    def update(cls, webhook_id, business_id, processing_callback=False, **updates):
        cls._enforce_permission("update", skip=processing_callback)
        updates["updated_at"] = datetime.utcnow()
        updates = {k: v for k, v in updates.items() if v is not None}
        if "secret" in updates and updates["secret"]:
            updates["secret"] = encrypt_data(updates["secret"])
        for oid in ["branch_id"]:
            if oid in updates and updates[oid]:
                updates[oid] = ObjectId(updates[oid])
        return super().update(webhook_id, business_id, **updates)

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("business_id", 1), ("is_active", 1), ("event_types", 1)])
            c.create_index([("business_id", 1), ("branch_id", 1)])
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════
# EMBED WIDGET
# ═══════════════════════════════════════════════════════════════

class EmbedWidget(BaseModel):
    """
    Embeddable widget configuration for church websites.
    Generates embed codes for calendar, giving, forms, events.
    """

    collection_name = "embed_widgets"
    _permission_module = "integrations"

    WIDGET_TYPES = ["calendar", "giving", "forms", "events", "sermons", "custom"]

    def __init__(
        self,
        widget_type,
        name,
        branch_id,
        settings=None,
        allowed_domains=None,
        is_active=True,
        user_id=None,
        user__id=None,
        business_id=None,
        **kw,
    ):
        super().__init__(user__id=user__id, user_id=user_id, business_id=business_id, **kw)
        self.business_id = ObjectId(business_id) if business_id else None
        self.branch_id = ObjectId(branch_id) if branch_id else None

        self.widget_type = widget_type
        self.name = name
        self.embed_key = uuid.uuid4().hex[:16]
        self.settings = settings or {}
        self.allowed_domains = allowed_domains or []
        self.is_active = bool(is_active)
        self.view_count = 0
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "branch_id": self.branch_id,
            "widget_type": self.widget_type,
            "name": self.name,
            "embed_key": self.embed_key,
            "settings": self.settings,
            "allowed_domains": self.allowed_domains,
            "is_active": self.is_active,
            "view_count": self.view_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        return {k: v for k, v in doc.items() if v is not None}

    @classmethod
    def _normalise(cls, doc):
        if not doc:
            return None

        for f in ["_id", "business_id", "branch_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])

        embed_key = doc.get("embed_key", "")
        widget_type = doc.get("widget_type", "")
        base_url = doc.get("settings", {}).get("base_url", "https://portal.example.com")

        doc["embed_iframe"] = f'<iframe src="{base_url}/embed/{widget_type}/{embed_key}" width="100%" height="600" frameborder="0"></iframe>'
        doc["embed_script"] = f'<script src="{base_url}/embed/js/{embed_key}" async></script><div id="church-{widget_type}-{embed_key}"></div>'

        return doc

    @classmethod
    def get_by_id(cls, widget_id, business_id=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"_id": ObjectId(widget_id)}
            if business_id:
                q["business_id"] = ObjectId(business_id)
            return cls._normalise(c.find_one(q))
        except Exception as e:
            Log.error(f"[EmbedWidget.get_by_id] {e}")
            return None

    @classmethod
    def get_by_embed_key(cls, embed_key, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            return cls._normalise(c.find_one({"embed_key": embed_key, "is_active": True}))
        except Exception as e:
            Log.error(f"[EmbedWidget.get_by_embed_key] {e}")
            return None

    @classmethod
    def get_all(cls, business_id, branch_id=None, widget_type=None, page=1, per_page=50, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id)}
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            if widget_type:
                q["widget_type"] = widget_type
            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            return {
                "widgets": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[EmbedWidget.get_all] {e}")
            return {"widgets": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def increment_view(cls, embed_key, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            c.update_one({"embed_key": embed_key}, {"$inc": {"view_count": 1}})
        except Exception:
            pass

    @classmethod
    def update(cls, widget_id, business_id, processing_callback=False, **updates):
        cls._enforce_permission("update", skip=processing_callback)
        updates["updated_at"] = datetime.utcnow()
        updates = {k: v for k, v in updates.items() if v is not None}
        for oid in ["branch_id"]:
            if oid in updates and updates[oid]:
                updates[oid] = ObjectId(updates[oid])
        return super().update(widget_id, business_id, **updates)

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("embed_key", 1)], unique=True)
            c.create_index([("business_id", 1), ("branch_id", 1), ("widget_type", 1)])
            return True
        except Exception:
            return False