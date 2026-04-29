from datetime import datetime, timedelta
import os

import bcrypt
from marshmallow import ValidationError

from ..extensions.db import db
from bson.objectid import ObjectId
from flask import g
from ..constants.service_code import SYSTEM_USERS
from ..constants.social_permissions import (
    has_permission as _church_has_permission,
    is_system_owner as _is_system_owner,
    ROLE_SYSTEM_OWNER,
    ROLE_SUPER_ADMIN,
)
from ..utils.crypt import encrypt_data, hash_data, decrypt_data
from ..utils.logger import Log


class BaseModel:
    """
    Base class for all models providing CRUD, permissions, subscription enforcement, and pagination.

    Enforcement hierarchy (checked in _enforce_permission):
      1. Permission check  → does the user's role allow this action?
      2. Subscription check → does the business have an active subscription?

    Both are centralised here. Individual resources/models don't need decorators
    unless they want custom behaviour (e.g. allow_read for expired subscriptions).
    """

    collection_name = None

    # ── Permission module override (set in subclass) ──
    _permission_module = None
    _permission_exempt = False

    # ── Subscription enforcement config (override in subclass) ──
    _subscription_exempt = False
    _subscription_allow_read = False
    _subscription_grace_days = 0

    # ── Models that never require subscription checks ──
    _SUBSCRIPTION_EXEMPT_MODELS = {
        "subscription", "package", "user", "admin", "token",
        "business", "role", "passwordresettoken", "essensial",
        "tenant", "emailverification", "otp",
    }

    # ── Class name → permission module fallback mapping ──
    _MODEL_TO_MODULE = {
        "member": "members",
        "branch": "branches",
        "household": "households",
        "group": "groups",
        "attendance": "attendance",
        "followup": "followup",
        "carecase": "care",
        "carevisit": "care",
        "carenote": "care",
        "message": "messaging",
        "messagetemplate": "messaging",
        "event": "events",
        "eventregistration": "events",
        "account": "accounting",
        "fund": "accounting",
        "category": "accounting",
        "payee": "accounting",
        "transaction": "accounting",
        "budget": "accounting",
        "reconciliation": "accounting",
        "paymentvoucher": "accounting",
        "bankimportrule": "accounting",
        "donation": "donations",
        "givingcard": "donations",
        "donationlink": "donations",
        "pledgecampaign": "pledges",
        "pledge": "pledges",
        "volunteerprofile": "volunteers",
        "volunteerroster": "volunteers",
        "song": "worship",
        "servicetemplate": "worship",
        "serviceplan": "worship",
        "workflowtemplate": "workflows",
        "workflowrequest": "workflows",
        "dashboardconfig": "dashboards",
        "auditlog": "auditlogs",
        "form": "forms",
        "formsubmission": "forms",
        "storagequota": "storage",
        "portalpage": "pagebuilder",
        "role": "roles",
        "integration": "integrations",
        "webhook": "integrations",
        "embedwidget": "integrations",
        "sacramentrecord": "sacraments",
        "sermon": "sermons",
        "sermonseries": "sermons",
        "preacherschedule": "sermons",
    }

    # ── Operation name → action key mapping ──
    _OPERATION_TO_ACTION = {
        "create": "create",
        "read": "read",
        "update": "update",
        "delete": "delete",
        "add": "create",
        "edit": "update",
        "view": "read",
        "export": "export",
        "import": "import",
        "approve": "approve",
        "reject": "reject",
        "publish": "publish",
        "unpublish": "unpublish",
        "assign": "assign",
        "upload": "upload",
        "send": "send",
        "schedule": "schedule",
        "manage": "manage",
    }

    def __init__(
        self,
        business_id,
        branch_id=None,
        member_id=None,
        user_id=None,
        user__id=None,
        agent_id=None,
        admin_id=None,
        created_by=None,
        **kwargs,
    ):
        self.business_id = ObjectId(business_id)
        self.user_id = user_id
        self.user__id = ObjectId(user__id) if user__id else None

        if member_id:
            self.member_id = ObjectId(member_id)
        if branch_id:
            self.branch_id = ObjectId(branch_id)
        if agent_id:
            self.agent_id = agent_id
        if admin_id:
            self.admin_id = ObjectId(admin_id)
        if created_by:
            self.created_by = ObjectId(created_by)

        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_dict(self):
        return {key: getattr(self, key) for key in self.__dict__}

    # ═══════════════════════════════════════════════════════════════
    # SAFE DECRYPT HELPERS
    # ═══════════════════════════════════════════════════════════════

    @staticmethod
    def _safe_decrypt_field(value):
        if not value or not isinstance(value, str):
            return value
        if len(value) <= 30:
            return value
        try:
            return decrypt_data(value)
        except Exception:
            return value

    @staticmethod
    def _safe_account_type(value):
        if not value or not isinstance(value, str):
            return ""
        if len(value) <= 30:
            return value.upper()
        try:
            decrypted = decrypt_data(value)
            return decrypted.upper() if decrypted else ""
        except Exception:
            return value.upper()

    @staticmethod
    def _is_bcrypt_hash(s: str) -> bool:
        return isinstance(s, str) and (
            s.startswith("$2a$") or s.startswith("$2b$") or s.startswith("$2y$")
        )

    @staticmethod
    def _get_current_user():
        try:
            user_info = getattr(g, "current_user", None)
            if user_info:
                return user_info
        except Exception:
            pass

        try:
            return g.get("current_user", None)
        except Exception:
            return None

    # ═══════════════════════════════════════════════════════════════
    # PERMISSION SYSTEM
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _resolve_module_key(cls, custom_model_name=None):
        if cls._permission_module:
            return cls._permission_module
        model_name = (custom_model_name or cls.__name__).lower()
        return cls._MODEL_TO_MODULE.get(model_name, model_name)

    @classmethod
    def check_permission(cls, operation, custom_model_name=None):
        user_info = cls._get_current_user()
        if not user_info:
            raise PermissionError("No current user found for permission check.")

        account_type = cls._safe_account_type(user_info.get("account_type"))

        if account_type in ("SYSTEM_OWNER", "SUPER_ADMIN", "BUSINESS_OWNER"):
            return True

        module_key = cls._resolve_module_key(custom_model_name)
        action = cls._OPERATION_TO_ACTION.get(operation, operation)
        return _church_has_permission(user_info, module_key, action)

    @classmethod
    def verify_permission(cls, operation, model_name=None):
        resolved = model_name or cls.__name__.lower()
        if not cls.check_permission(operation, resolved):
            raise PermissionError(
                f"User does not have permission to {operation} {resolved}."
            )

    @classmethod
    def check_permission_silent(cls, operation, custom_model_name=None):
        try:
            return cls.check_permission(operation, custom_model_name)
        except PermissionError:
            return False

    # ═══════════════════════════════════════════════════════════════
    # SUBSCRIPTION CHECK
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _is_subscription_exempt(cls):
        if cls._subscription_exempt:
            return True
        return cls.__name__.lower() in cls._SUBSCRIPTION_EXEMPT_MODELS

    @classmethod
    def _check_subscription(cls, action="create"):
        """
        Check if the business has an active subscription.
        Only SYSTEM_OWNER bypasses. All other roles require active subscription.

        Raises SubscriptionError if not active.
        Returns True if active or bypassed.
        """
        if cls._is_subscription_exempt():
            return True

        user_info = cls._get_current_user()
        if not user_info:
            raise SubscriptionError(
                "Unable to verify subscription because no authenticated user context was found.",
                {
                    "subscription_status": "unknown",
                    "action_required": "re_authenticate",
                },
            )

        account_type = cls._safe_account_type(user_info.get("account_type", ""))

        # Only SYSTEM_OWNER bypasses
        if account_type == "SYSTEM_OWNER":
            return True

        # Allow read for models configured to permit reads on expired subscription
        if cls._subscription_allow_read and action == "read":
            return True

        business_id = str(user_info.get("business_id", ""))
        if not business_id:
            raise SubscriptionError(
                "Unable to verify subscription because business_id is missing.",
                {
                    "subscription_status": "unknown",
                    "action_required": "re_authenticate",
                },
            )

        try:
            from ..models.admin.subscription_model import Subscription

            subscription = Subscription.get_active_by_business(business_id)

            if not subscription:
                latest = Subscription.get_latest_by_business(business_id)
                error_info = cls._build_subscription_error(latest)
                raise SubscriptionError(error_info["message"], error_info["details"])

            sub_status = (subscription.get("status") or "").upper()

            if sub_status == "TRIAL":
                trial_end = subscription.get("trial_end_date")
                if trial_end:
                    now = datetime.utcnow()
                    if isinstance(trial_end, str):
                        trial_end = datetime.fromisoformat(trial_end)

                    if isinstance(trial_end, datetime):
                        grace_end = trial_end + timedelta(days=cls._subscription_grace_days)
                        if now > grace_end:
                            days_overdue = (now - trial_end).days
                            raise SubscriptionError(
                                f"Your free trial expired {days_overdue} day(s) ago. Please subscribe to continue.",
                                {
                                    "subscription_status": "trial_expired",
                                    "trial_end_date": trial_end.isoformat(),
                                    "days_overdue": days_overdue,
                                    "action_required": "subscribe",
                                },
                            )

            if sub_status == "ACTIVE":
                end_date = subscription.get("end_date")
                if end_date:
                    now = datetime.utcnow()
                    if isinstance(end_date, str):
                        end_date = datetime.fromisoformat(end_date)

                    if isinstance(end_date, datetime):
                        grace_end = end_date + timedelta(days=cls._subscription_grace_days)
                        if now > grace_end:
                            days_overdue = (now - end_date).days
                            raise SubscriptionError(
                                f"Your subscription expired {days_overdue} day(s) ago. Please renew to continue.",
                                {
                                    "subscription_status": "expired",
                                    "end_date": end_date.isoformat(),
                                    "days_overdue": days_overdue,
                                    "action_required": "renew",
                                },
                            )

            return True

        except SubscriptionError:
            raise
        except Exception as e:
            Log.error(f"[BaseModel._check_subscription] error: {e}", exc_info=True)
            raise SubscriptionError(
                "Unable to verify subscription status at the moment.",
                {
                    "subscription_status": "unknown",
                    "action_required": "retry_or_contact_support",
                    "error": str(e),
                },
            )

    @classmethod
    def _build_subscription_error(cls, latest_subscription):
        if not latest_subscription:
            return {
                "message": "No subscription found. Please subscribe to a plan to continue.",
                "details": {"subscription_status": "none", "action_required": "subscribe"},
            }

        status = (latest_subscription.get("status") or "").upper()

        status_map = {
            "TRIALEXPIRED": ("Your free trial has expired. Please subscribe to continue.", "trial_expired", "subscribe"),
            "CANCELLED": ("Your subscription has been cancelled. Please renew to continue.", "cancelled", "renew"),
            "EXPIRED": ("Your subscription has expired. Please renew to continue.", "expired", "renew"),
            "SUSPENDED": ("Your subscription has been suspended. Please contact support.", "suspended", "contact_support"),
        }

        if status in status_map:
            msg, s, action = status_map[status]
            return {"message": msg, "details": {"subscription_status": s, "action_required": action}}

        return {
            "message": "Your subscription is not active. Please subscribe or renew to continue.",
            "details": {"subscription_status": status.lower(), "action_required": "subscribe"},
        }

    # ═══════════════════════════════════════════════════════════════
    # CENTRALISED ENFORCEMENT (PERMISSION + SUBSCRIPTION)
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _enforce_permission(cls, action, skip=False, model_name=None):
        """
        Central enforcement for all CRUD methods.
        Checks permission THEN subscription in one call.

        Args:
            action: create/read/update/delete/etc.
            skip: bypass all enforcement (processing_callback, login, etc.)
            model_name: explicit model name for permission resolution
        """
        if skip:
            return

        resolved = model_name or cls.__name__.lower()
        
         # Public/exempt models skip both subscription and permission checks

        if cls._permission_exempt or cls._is_subscription_exempt():
            return

        # 1. Subscription check first
        cls._check_subscription(action=action)

        # 2. Permission check second
        if not cls.check_permission(action, resolved):
            raise PermissionError(
                f"User does not have permission to {action} {resolved}."
            )

    # ═══════════════════════════════════════════════════════════════
    # BUSINESS SCOPE
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def is_cross_business_user(cls):
        user_info = cls._get_current_user()
        if not user_info:
            return False
        account_type = cls._safe_account_type(user_info.get("account_type"))
        return account_type in ("SYSTEM_OWNER", ROLE_SYSTEM_OWNER)

    @classmethod
    def resolve_target_business(cls, user_info, requested_business_id=None):
        account_type = cls._safe_account_type(user_info.get("account_type", ""))
        auth_business_id = str(user_info.get("business_id", ""))

        if account_type in ("SYSTEM_OWNER", ROLE_SYSTEM_OWNER, "SUPER_ADMIN", ROLE_SUPER_ADMIN):
            return requested_business_id or auth_business_id

        return auth_business_id

    # ═══════════════════════════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════════════════════════

    def save(self, processing_callback=False):
        self.__class__._enforce_permission(
            "create",
            skip=processing_callback,
            model_name=self.__class__.__name__.lower(),
        )
        collection = db.get_collection(self.collection_name)
        result = collection.insert_one(self.to_dict())
        return str(result.inserted_id)

    @classmethod
    def get_by_id(cls, record_id, business_id, processing_callback=False, is_logging_in=False):
        cls._enforce_permission(
            "read",
            skip=(processing_callback or is_logging_in),
            model_name=cls.__name__.lower(),
        )
        collection = db.get_collection(cls.collection_name)

        if cls.is_cross_business_user() and business_id is None:
            data = collection.find_one({"_id": ObjectId(record_id)})
        else:
            data = collection.find_one({"_id": ObjectId(record_id), "business_id": ObjectId(business_id)})

        return data if data else None

    @classmethod
    def _get_all_base(
        cls, business_id, processing_callback=False,
        query=None, page=None, per_page=None,
        sort=None, sort_by=None, sort_order=None,
        stringify_objectids=False, normalise=False,
    ):
        cls._enforce_permission("read", skip=processing_callback, model_name=cls.__name__.lower())

        final_query = query.copy() if query else {}
        if not (cls.is_cross_business_user() and business_id is None):
            final_query["business_id"] = ObjectId(business_id)

        result = cls.paginate(
            query=final_query, page=page, per_page=per_page,
            sort=sort, sort_by=sort_by, sort_order=sort_order,
            stringify_objectids=stringify_objectids,
        )

        items = result.get("items", [])
        if normalise and hasattr(cls, "_normalise"):
            items = [cls._normalise(doc) for doc in items]
        elif not stringify_objectids:
            items = [cls(**doc) if isinstance(doc, dict) else doc for doc in items]

        return {
            "items": items,
            "total_count": result.get("total_count", 0),
            "total_pages": result.get("total_pages", 0),
            "current_page": result.get("current_page", page or 1),
            "per_page": result.get("per_page", per_page),
        }

    @classmethod
    def get_all(cls, business_id, processing_callback=False):
        return cls._get_all_base(business_id=business_id, processing_callback=processing_callback)

    @classmethod
    def get_all_as(
        cls, business_id, item_key="items", processing_callback=False,
        query=None, page=None, per_page=None,
        sort=None, sort_by=None, sort_order=None,
        stringify_objectids=False, normalise=False,
    ):
        result = cls._get_all_base(
            business_id=business_id, processing_callback=processing_callback,
            query=query, page=page, per_page=per_page,
            sort=sort, sort_by=sort_by, sort_order=sort_order,
            stringify_objectids=stringify_objectids, normalise=normalise,
        )
        return {
            item_key: result["items"],
            "total_count": result["total_count"],
            "total_pages": result["total_pages"],
            "current_page": result["current_page"],
            "per_page": result["per_page"],
        }

    @classmethod
    def get_children(
        cls, business_id, parent_id, parent_field="parent_account_id",
        processing_callback=False, page=1, per_page=1000,
        sort_by="created_at", sort_order=1,
        normalise=False, stringify_objectids=False,
    ):
        return cls._get_all_base(
            business_id=business_id, processing_callback=processing_callback,
            query={parent_field: ObjectId(parent_id)},
            page=page, per_page=per_page,
            sort_by=sort_by, sort_order=sort_order,
            stringify_objectids=stringify_objectids, normalise=normalise,
        )

    @classmethod
    def update(cls, record_id, business_id, processing_callback=False, is_member_self_service=False, **updates):
        cls._enforce_permission(
            "update",
            skip=(processing_callback or is_member_self_service),
            model_name=cls.__name__.lower(),
        )

        collection = db.get_collection(cls.collection_name)
        updates["updated_at"] = datetime.now()

        if business_id is not None:
            result = collection.update_one(
                {"_id": ObjectId(record_id), "business_id": ObjectId(business_id)},
                {"$set": updates},
            )
        else:
            result = collection.update_one({"_id": ObjectId(record_id)}, {"$set": updates})

        return result.modified_count > 0

    @classmethod
    def delete(cls, record_id, business_id, processing_callback=False):
        cls._enforce_permission("delete", skip=processing_callback, model_name=cls.__name__.lower())

        collection = db.get_collection(cls.collection_name)
        if cls.is_cross_business_user() and business_id is None:
            result = collection.delete_one({"_id": ObjectId(record_id)})
        else:
            result = collection.delete_one({"_id": ObjectId(record_id), "business_id": ObjectId(business_id)})

        return result.deleted_count > 0

    # ═══════════════════════════════════════════════════════════════
    # EXISTENCE CHECKS
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def check_item_exists_business_id(cls, business_id, key, value):
        if isinstance(business_id, str):
            business_id = ObjectId(business_id)
        hashed_key = hash_data(value)
        collection = db.get_collection(cls.collection_name)
        return bool(collection.find_one({"business_id": business_id, f"hashed_{key}": hashed_key}))

    @classmethod
    def check_item_exists(cls, agent_id, key, value):
        if isinstance(agent_id, str):
            agent_id = ObjectId(agent_id)
        hashed_key = hash_data(value)
        collection = db.get_collection(cls.collection_name)
        return bool(collection.find_one({"agent_id": agent_id, f"hashed_{key}": hashed_key}))

    @classmethod
    def check_item_admin_id_exists(cls, admin_id, key, value):
        if isinstance(admin_id, str):
            admin_id = ObjectId(admin_id)
        hashed_key = hash_data(value)
        collection = db.get_collection(cls.collection_name)
        return bool(collection.find_one({"admin_id": admin_id, f"hashed_{key}": hashed_key}))

    @classmethod
    def check_multiple_item_exists(cls, business_id, fields: dict):
        try:
            query = {"business_id": ObjectId(business_id)}
            for key, value in fields.items():
                query[f"hashed_{key}"] = hash_data(value)
            collection = db.get_collection(cls.collection_name)
            return collection.find_one(query) is not None
        except Exception as e:
            Log.error(f"[BaseModel.check_multiple_item_exists] {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # PAGINATION
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback, model_name=cls.__name__.lower())
        return cls.paginate(query={"business_id": ObjectId(business_id)}, page=page, per_page=per_page)

    @classmethod
    def get_all_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback, model_name=cls.__name__.lower())

        user_filter = user__id
        if isinstance(user__id, str) and len(user__id) == 24:
            try:
                user_filter = ObjectId(user__id)
            except Exception:
                pass

        return cls.paginate(
            query={"business_id": ObjectId(business_id), "user__id": user_filter},
            page=page, per_page=per_page,
        )

    @classmethod
    def paginate(
        cls, query=None, page=None, per_page=None,
        sort=None, sort_by=None, sort_order=None,
        stringify_objectids=True,
    ):
        log_tag = f"[base_model.py][{cls.__name__}][paginate]"

        if query is None:
            query = {}

        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", 1))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", 50))

        try:
            page_int = int(page) if page is not None else default_page
        except (TypeError, ValueError):
            page_int = default_page

        try:
            per_page_int = int(per_page) if per_page is not None else default_per_page
        except (TypeError, ValueError):
            per_page_int = default_per_page

        if page_int < 1:
            page_int = 1
        if per_page_int <= 0:
            per_page_int = default_per_page

        if sort is not None:
            sort_spec = [sort] if isinstance(sort, tuple) else sort if isinstance(sort, list) else [("created_at", -1)]
        elif sort_by:
            sort_spec = [(sort_by, sort_order if sort_order in (1, -1) else -1)]
        else:
            sort_spec = [("created_at", -1)]

        try:
            collection = db.get_collection(cls.collection_name)
            total_count = collection.count_documents(query)
            cursor = collection.find(query)

            if sort_spec:
                cursor = cursor.sort(sort_spec)

            cursor = cursor.skip((page_int - 1) * per_page_int).limit(per_page_int)
            items = list(cursor)

            if stringify_objectids:
                def _stringify(v):
                    if isinstance(v, ObjectId):
                        return str(v)
                    if isinstance(v, dict):
                        return {kk: _stringify(vv) for kk, vv in v.items()}
                    if isinstance(v, list):
                        return [_stringify(x) for x in v]
                    return v
                items = [_stringify(doc) for doc in items]

            total_pages = (total_count + per_page_int - 1) // per_page_int if per_page_int else 1

            Log.info(
                f"{log_tag} query={query} page={page_int} per_page={per_page_int} "
                f"sort={sort_spec} returned={len(items)} total={total_count}"
            )

            return {
                "items": items,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page_int,
                "per_page": per_page_int,
            }

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return {
                "items": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page_int,
                "per_page": per_page_int,
            }

    # ═══════════════════════════════════════════════════════════════
    # UTILITIES
    # ═══════════════════════════════════════════════════════════════

    @classmethod
    def _hash_password(cls, password: str) -> str:
        if not password:
            raise ValidationError("Password is required.")
        if cls._is_bcrypt_hash(password):
            return password
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ═══════════════════════════════════════════════════════════════
# CUSTOM EXCEPTION
# ═══════════════════════════════════════════════════════════════

class SubscriptionError(Exception):
    """Raised when a business's subscription is not active."""

    def __init__(self, message, details=None):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        





