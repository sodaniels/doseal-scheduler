# app/models/social/form_model.py

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from bson import ObjectId
import uuid

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class StorageQuota(BaseModel):
    """
    Tracks storage usage per business.
    Limits are derived from the active subscription package, not hardcoded.
    Additional storage can be purchased as an addon.
    """

    collection_name = "storage_quotas"
    _permission_module = "storage"

    def __init__(self, storage_limit_bytes=None, addon_storage_bytes=0,
                 user_id=None, user__id=None, business_id=None, **kw):
        super().__init__(user__id=user__id, user_id=user_id, business_id=business_id, **kw)
        self.business_id = ObjectId(business_id) if business_id else None
        self.storage_limit_bytes = storage_limit_bytes or 0       # From package
        self.addon_storage_bytes = int(addon_storage_bytes)        # Purchased addons
        self.storage_used_bytes = 0
        self.file_count = 0
        self.addon_purchases = []  # [{amount_gb, purchased_at, payment_reference, price}]
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "storage_limit_bytes": self.storage_limit_bytes,
            "addon_storage_bytes": self.addon_storage_bytes,
            "storage_used_bytes": self.storage_used_bytes,
            "file_count": self.file_count,
            "addon_purchases": self.addon_purchases,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def _normalise(cls, doc):
        if not doc:
            return None
        for f in ["_id", "business_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])

        base_limit = doc.get("storage_limit_bytes", 0)
        addon = doc.get("addon_storage_bytes", 0)
        total_limit = base_limit + addon
        used = doc.get("storage_used_bytes", 0)

        doc["total_limit_bytes"] = total_limit
        doc["storage_limit_gb"] = round(base_limit / (1024 ** 3), 2) if base_limit > 0 else 0
        doc["addon_storage_gb"] = round(addon / (1024 ** 3), 2) if addon > 0 else 0
        doc["total_limit_gb"] = round(total_limit / (1024 ** 3), 2) if total_limit > 0 else 0
        doc["storage_used_gb"] = round(used / (1024 ** 3), 2) if used > 0 else 0
        doc["storage_used_mb"] = round(used / (1024 ** 2), 2) if used > 0 else 0
        doc["storage_remaining_gb"] = round(max(0, total_limit - used) / (1024 ** 3), 2)
        doc["usage_pct"] = round((used / total_limit * 100), 1) if total_limit > 0 else 0
        doc["is_unlimited"] = base_limit < 0
        doc["is_full"] = used >= total_limit and total_limit > 0

        return doc

    @classmethod
    def _get_limit_from_package(cls, business_id):
        """Read storage_total_gb from the active subscription's package."""
        try:
            from ...services.pos.subscription_service import SubscriptionService
            from ...models.admin.package_model import Package

            sub = SubscriptionService.get_active_subscription(str(business_id))
            if not sub:
                return 2 * (1024 ** 3)  # Default 2GB if no subscription

            package_id = sub.get("package_id")
            if not package_id:
                return 2 * (1024 ** 3)

            package = Package.get_by_id(str(package_id))
            if not package:
                return 2 * (1024 ** 3)

            storage_gb = package.get("storage_total_gb", 2)

            # -1 means unlimited
            if storage_gb == -1:
                return -1

            return int(storage_gb * (1024 ** 3))

        except Exception as e:
            Log.error(f"[StorageQuota._get_limit_from_package] {e}")
            return 2 * (1024 ** 3)

    @classmethod
    def get_or_create(cls, business_id, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            doc = c.find_one({"business_id": ObjectId(business_id)})

            # Sync limit from package every time
            package_limit = cls._get_limit_from_package(business_id)

            if doc:
                # Update base limit if package changed
                if doc.get("storage_limit_bytes") != package_limit:
                    c.update_one(
                        {"_id": doc["_id"]},
                        {"$set": {"storage_limit_bytes": package_limit, "updated_at": datetime.utcnow()}},
                    )
                    doc["storage_limit_bytes"] = package_limit
                return cls._normalise(doc)

            # Create new
            quota = cls(storage_limit_bytes=package_limit, business_id=business_id)
            qid = quota.save(processing_callback=True)
            return cls._normalise(c.find_one({"_id": ObjectId(qid)}))

        except Exception as e:
            Log.error(f"[StorageQuota.get_or_create] {e}")
            return None

    @classmethod
    def check_space(cls, business_id, file_size_bytes, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            quota = cls.get_or_create(business_id, processing_callback=True)
            if not quota:
                return False, None

            # Unlimited
            if quota.get("is_unlimited"):
                return True, quota

            total_limit = quota.get("total_limit_bytes", 0)
            used = quota.get("storage_used_bytes", 0)
            has_space = (used + file_size_bytes) <= total_limit
            return has_space, quota

        except Exception as e:
            Log.error(f"[StorageQuota.check_space] {e}")
            return False, None

    @classmethod
    def consume(cls, business_id, file_size_bytes, processing_callback=False):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            c.update_one(
                {"business_id": ObjectId(business_id)},
                {
                    "$inc": {"storage_used_bytes": int(file_size_bytes), "file_count": 1},
                    "$set": {"updated_at": datetime.utcnow()},
                },
            )
            return True
        except Exception as e:
            Log.error(f"[StorageQuota.consume] {e}")
            return False

    @classmethod
    def release(cls, business_id, file_size_bytes, processing_callback=False):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            c.update_one(
                {"business_id": ObjectId(business_id)},
                {
                    "$inc": {"storage_used_bytes": -int(file_size_bytes), "file_count": -1},
                    "$set": {"updated_at": datetime.utcnow()},
                },
            )
            return True
        except Exception as e:
            Log.error(f"[StorageQuota.release] {e}")
            return False

    @classmethod
    def add_addon_storage(cls, business_id, addon_gb, payment_reference=None, price=None, processing_callback=False):
        """
        Purchase additional storage on top of the package limit.
        Called after successful addon payment.
        """
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            addon_bytes = int(addon_gb * (1024 ** 3))

            purchase_record = {
                "amount_gb": addon_gb,
                "amount_bytes": addon_bytes,
                "purchased_at": datetime.utcnow().isoformat(),
                "payment_reference": payment_reference,
                "price": price,
            }

            # Ensure quota exists first
            cls.get_or_create(business_id, processing_callback=True)

            c.update_one(
                {"business_id": ObjectId(business_id)},
                {
                    "$inc": {"addon_storage_bytes": addon_bytes},
                    "$push": {"addon_purchases": purchase_record},
                    "$set": {"updated_at": datetime.utcnow()},
                },
            )

            Log.info(f"[StorageQuota.add_addon_storage] business={business_id} added {addon_gb}GB")
            return True
        except Exception as e:
            Log.error(f"[StorageQuota.add_addon_storage] {e}")
            return False

    @classmethod
    def sync_with_package(cls, business_id, processing_callback=False):
        """
        Resync storage limit from the active subscription package.
        Call after plan upgrade/downgrade.
        """
        cls._enforce_permission("update", skip=processing_callback)
        try:
            package_limit = cls._get_limit_from_package(business_id)
            c = db.get_collection(cls.collection_name)
            c.update_one(
                {"business_id": ObjectId(business_id)},
                {"$set": {"storage_limit_bytes": package_limit, "updated_at": datetime.utcnow()}},
                upsert=True,
            )
            Log.info(f"[StorageQuota.sync_with_package] business={business_id} limit={package_limit}")
            return True
        except Exception as e:
            Log.error(f"[StorageQuota.sync_with_package] {e}")
            return False

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("business_id", 1)], unique=True)
            return True
        except Exception:
            return False

class Form(BaseModel):
    """
    Custom form definition with fields and settings.
    """

    collection_name = "forms"
    _permission_module = "forms"

    FIELD_TEXT = "text"
    FIELD_TEXTAREA = "textarea"
    FIELD_NUMBER = "number"
    FIELD_EMAIL = "email"
    FIELD_PHONE = "phone"
    FIELD_DROPDOWN = "dropdown"
    FIELD_RADIO = "radio"
    FIELD_CHECKBOX = "checkbox"
    FIELD_DATE = "date"
    FIELD_TIME = "time"
    FIELD_FILE = "file"
    FIELD_RATING = "rating"
    FIELD_SECTION_HEADER = "section_header"
    FIELD_PARAGRAPH = "paragraph"

    FIELD_TYPES = [
        FIELD_TEXT, FIELD_TEXTAREA, FIELD_NUMBER, FIELD_EMAIL, FIELD_PHONE,
        FIELD_DROPDOWN, FIELD_RADIO, FIELD_CHECKBOX, FIELD_DATE, FIELD_TIME,
        FIELD_FILE, FIELD_RATING, FIELD_SECTION_HEADER, FIELD_PARAGRAPH,
    ]

    TEMPLATE_VISITOR = "Visitor Card"
    TEMPLATE_MEMBERSHIP = "Membership Application"
    TEMPLATE_BAPTISM = "Baptism Request"
    TEMPLATE_CHILD_DEDICATION = "Child Dedication"
    TEMPLATE_COUNSELING = "Counseling Request"
    TEMPLATE_EVENT_REGISTRATION = "Event Registration"
    TEMPLATE_VOLUNTEER_APPLICATION = "Volunteer Application"
    TEMPLATE_DEPARTMENT_NOMINATION = "Department Nomination"
    TEMPLATE_PRAYER_REQUEST = "Prayer Request"
    TEMPLATE_FEEDBACK = "Feedback"
    TEMPLATE_CUSTOM = "Custom"

    TEMPLATES = [
        TEMPLATE_VISITOR, TEMPLATE_MEMBERSHIP, TEMPLATE_BAPTISM,
        TEMPLATE_CHILD_DEDICATION, TEMPLATE_COUNSELING, TEMPLATE_EVENT_REGISTRATION,
        TEMPLATE_VOLUNTEER_APPLICATION, TEMPLATE_DEPARTMENT_NOMINATION,
        TEMPLATE_PRAYER_REQUEST, TEMPLATE_FEEDBACK, TEMPLATE_CUSTOM,
    ]

    STATUS_DRAFT = "Draft"
    STATUS_PUBLISHED = "Published"
    STATUS_CLOSED = "Closed"
    STATUS_ARCHIVED = "Archived"
    STATUSES = [STATUS_DRAFT, STATUS_PUBLISHED, STATUS_CLOSED, STATUS_ARCHIVED]

    FIELDS_TO_DECRYPT = ["title", "description"]

    def __init__(
        self,
        title,
        branch_id,
        template_type="Custom",
        description=None,
        slug=None,
        fields_config=None,
        status="Draft",
        allow_anonymous=False,
        require_login=False,
        is_public=False,
        is_embeddable=False,
        max_submissions=None,
        start_date=None,
        end_date=None,
        confirmation_message=None,
        redirect_url=None,
        notification_emails=None,
        auto_update_profile=False,
        max_file_size_mb=5,
        user_id=None,
        user__id=None,
        business_id=None,
        **kw,
    ):
        super().__init__(user__id=user__id, user_id=user_id, business_id=business_id, **kw)
        self.business_id = ObjectId(business_id) if business_id else None
        self.branch_id = ObjectId(branch_id) if branch_id else None

        if title:
            self.title = encrypt_data(title)
            self.hashed_title = hash_data(title.strip().lower())
        if description:
            self.description = encrypt_data(description)

        self.template_type = template_type
        self.slug = slug or str(uuid.uuid4())[:12]

        self.fields_config = fields_config or []
        for idx, f in enumerate(self.fields_config):
            if not f.get("field_id"):
                f["field_id"] = f"field_{idx+1:03d}"
            if "order" not in f:
                f["order"] = idx + 1

        self.status = status
        self.hashed_status = hash_data(status.strip())

        self.allow_anonymous = bool(allow_anonymous)
        self.require_login = bool(require_login)
        self.is_public = bool(is_public)
        self.is_embeddable = bool(is_embeddable)

        if max_submissions is not None:
            self.max_submissions = int(max_submissions)
        if start_date:
            self.start_date = start_date
        if end_date:
            self.end_date = end_date
        if confirmation_message:
            self.confirmation_message = confirmation_message
        if redirect_url:
            self.redirect_url = redirect_url
        if notification_emails:
            self.notification_emails = notification_emails

        self.auto_update_profile = bool(auto_update_profile)
        self.max_file_size_mb = int(max_file_size_mb)

        self.submission_count = 0
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "branch_id": self.branch_id,
            "title": getattr(self, "title", None),
            "hashed_title": getattr(self, "hashed_title", None),
            "description": getattr(self, "description", None),
            "template_type": self.template_type,
            "slug": self.slug,
            "fields_config": self.fields_config,
            "status": self.status,
            "hashed_status": self.hashed_status,
            "allow_anonymous": self.allow_anonymous,
            "require_login": self.require_login,
            "is_public": self.is_public,
            "is_embeddable": self.is_embeddable,
            "max_submissions": getattr(self, "max_submissions", None),
            "start_date": getattr(self, "start_date", None),
            "end_date": getattr(self, "end_date", None),
            "confirmation_message": getattr(self, "confirmation_message", None),
            "redirect_url": getattr(self, "redirect_url", None),
            "notification_emails": getattr(self, "notification_emails", None),
            "auto_update_profile": self.auto_update_profile,
            "max_file_size_mb": self.max_file_size_mb,
            "submission_count": self.submission_count,
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
    def _normalise(cls, doc):
        if not doc:
            return None
        for f in ["_id", "business_id", "branch_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])
        for f in cls.FIELDS_TO_DECRYPT:
            if f in doc:
                doc[f] = cls._safe_decrypt(doc[f])
        doc.pop("hashed_title", None)
        doc.pop("hashed_status", None)
        doc["field_count"] = len(doc.get("fields_config", []))
        doc["required_field_count"] = len([f for f in doc.get("fields_config", []) if f.get("required")])
        return doc

    @classmethod
    def get_by_id(cls, form_id, business_id=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"_id": ObjectId(form_id)}
            if business_id:
                q["business_id"] = ObjectId(business_id)
            return cls._normalise(c.find_one(q))
        except Exception as e:
            Log.error(f"[Form.get_by_id] {e}")
            return None

    @classmethod
    def get_by_slug(cls, business_id, slug, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            return cls._normalise(c.find_one({"business_id": ObjectId(business_id), "slug": slug}))
        except Exception as e:
            Log.error(f"[Form.get_by_slug] {e}")
            return None

    @classmethod
    def get_all(cls, business_id, branch_id=None, template_type=None, status=None, page=1, per_page=50, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id)}
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            if template_type:
                q["template_type"] = template_type
            if status:
                q["hashed_status"] = hash_data(status.strip())

            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            return {
                "forms": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[Form.get_all] {e}")
            return {"forms": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def increment_submission_count(cls, form_id, business_id, processing_callback=False):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            c.update_one(
                {"_id": ObjectId(form_id), "business_id": ObjectId(business_id)},
                {"$inc": {"submission_count": 1}, "$set": {"updated_at": datetime.utcnow()}},
            )
            return True
        except Exception as e:
            Log.error(f"[Form.increment_submission_count] {e}")
            return False

    @classmethod
    def can_accept_submissions(cls, form_id, business_id, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            form = cls.get_by_id(form_id, business_id, processing_callback=True)
            if not form:
                return False, "Form not found."
            if form.get("status") != cls.STATUS_PUBLISHED:
                return False, "Form is not published."
            now = datetime.utcnow().strftime("%Y-%m-%d")
            if form.get("start_date") and now < form["start_date"]:
                return False, "Form is not yet open."
            if form.get("end_date") and now > form["end_date"]:
                return False, "Form has closed."
            max_sub = form.get("max_submissions")
            if max_sub and form.get("submission_count", 0) >= max_sub:
                return False, "Maximum submissions reached."
            return True, "OK"
        except Exception as e:
            Log.error(f"[Form.can_accept_submissions] {e}")
            return False, str(e)

    @classmethod
    def publish(cls, form_id, business_id, processing_callback=False):
        cls._enforce_permission("publish", skip=processing_callback)
        try:
            return cls.update(form_id, business_id, status=cls.STATUS_PUBLISHED, processing_callback=True)
        except Exception as e:
            Log.error(f"[Form.publish] {e}")
            return False

    @classmethod
    def unpublish(cls, form_id, business_id, processing_callback=False):
        cls._enforce_permission("unpublish", skip=processing_callback)
        try:
            return cls.update(form_id, business_id, status=cls.STATUS_DRAFT, processing_callback=True)
        except Exception as e:
            Log.error(f"[Form.unpublish] {e}")
            return False

    @classmethod
    def update(cls, form_id, business_id, processing_callback=False, **updates):
        cls._enforce_permission("update", skip=processing_callback)
        try:
            updates["updated_at"] = datetime.utcnow()
            updates = {k: v for k, v in updates.items() if v is not None}

            if "title" in updates and updates["title"]:
                p = updates["title"]
                updates["title"] = encrypt_data(p)
                updates["hashed_title"] = hash_data(p.strip().lower())

            if "description" in updates and updates["description"]:
                updates["description"] = encrypt_data(updates["description"])

            if "status" in updates and updates["status"]:
                updates["hashed_status"] = hash_data(updates["status"].strip())

            if "branch_id" in updates and updates["branch_id"]:
                updates["branch_id"] = ObjectId(updates["branch_id"])

            return super().update(form_id, business_id, **updates)
        except Exception as e:
            Log.error(f"[Form.update] {e}")
            return False

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("business_id", 1), ("branch_id", 1), ("hashed_status", 1)])
            c.create_index([("business_id", 1), ("slug", 1)], unique=True)
            c.create_index([("business_id", 1), ("template_type", 1)])
            c.create_index([("business_id", 1), ("hashed_title", 1)])
            return True
        except Exception:
            return False


class FormSubmission(BaseModel):
    """
    Individual form submission with responses and optional file attachments.
    """

    collection_name = "form_submissions"
    _permission_module = "forms"

    FIELDS_TO_DECRYPT = ["submitter_name", "submitter_email"]

    def __init__(
        self,
        form_id,
        branch_id,
        responses=None,
        member_id=None,
        submitter_name=None,
        submitter_email=None,
        is_anonymous=False,
        attachments=None,
        total_file_size_bytes=0,
        submission_time_seconds=None,
        ip_address=None,
        user_agent=None,
        user_id=None,
        user__id=None,
        business_id=None,
        **kw,
    ):
        super().__init__(user__id=user__id, user_id=user_id, business_id=business_id, **kw)
        self.business_id = ObjectId(business_id) if business_id else None
        self.branch_id = ObjectId(branch_id) if branch_id else None
        self.form_id = ObjectId(form_id) if form_id else None

        self.responses = responses or []

        if member_id:
            self.member_id = ObjectId(member_id)
        if submitter_name:
            self.submitter_name = encrypt_data(submitter_name)
        if submitter_email:
            self.submitter_email = encrypt_data(submitter_email)

        self.is_anonymous = bool(is_anonymous)
        self.attachments = attachments or []
        self.total_file_size_bytes = int(total_file_size_bytes)

        if submission_time_seconds is not None:
            self.submission_time_seconds = int(submission_time_seconds)
        if ip_address:
            self.ip_address = ip_address
        if user_agent:
            self.user_agent = user_agent

        self.created_at = datetime.utcnow()

    def to_dict(self):
        doc = {
            "business_id": self.business_id,
            "branch_id": self.branch_id,
            "form_id": self.form_id,
            "responses": self.responses,
            "member_id": getattr(self, "member_id", None),
            "submitter_name": getattr(self, "submitter_name", None),
            "submitter_email": getattr(self, "submitter_email", None),
            "is_anonymous": self.is_anonymous,
            "attachments": self.attachments,
            "total_file_size_bytes": self.total_file_size_bytes,
            "submission_time_seconds": getattr(self, "submission_time_seconds", None),
            "ip_address": getattr(self, "ip_address", None),
            "user_agent": getattr(self, "user_agent", None),
            "created_at": self.created_at,
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
    def _normalise(cls, doc):
        if not doc:
            return None
        for f in ["_id", "business_id", "branch_id", "form_id", "member_id"]:
            if doc.get(f):
                doc[f] = str(doc[f])
        for f in cls.FIELDS_TO_DECRYPT:
            if f in doc:
                doc[f] = cls._safe_decrypt(doc[f])
        return doc

    @classmethod
    def get_by_id(cls, submission_id, business_id=None, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"_id": ObjectId(submission_id)}
            if business_id:
                q["business_id"] = ObjectId(business_id)
            return cls._normalise(c.find_one(q))
        except Exception as e:
            Log.error(f"[FormSubmission.get_by_id] {e}")
            return None

    @classmethod
    def get_all(cls, business_id, form_id=None, branch_id=None, member_id=None, start_date=None, end_date=None, page=1, per_page=50, processing_callback=False):
        cls._enforce_permission("read", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"business_id": ObjectId(business_id)}
            if form_id:
                q["form_id"] = ObjectId(form_id)
            if branch_id:
                q["branch_id"] = ObjectId(branch_id)
            if member_id:
                q["member_id"] = ObjectId(member_id)
            if start_date:
                q.setdefault("created_at", {})["$gte"] = datetime.fromisoformat(start_date)
            if end_date:
                q.setdefault("created_at", {})["$lte"] = datetime.fromisoformat(end_date)

            total = c.count_documents(q)
            cursor = c.find(q).sort("created_at", -1).skip((page - 1) * per_page).limit(per_page)
            return {
                "submissions": [cls._normalise(d) for d in cursor],
                "total_count": total,
                "total_pages": (total + per_page - 1) // per_page,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"[FormSubmission.get_all] {e}")
            return {"submissions": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def get_analytics(cls, form_id, business_id, processing_callback=False):
        cls._enforce_permission("export", skip=processing_callback)
        try:
            c = db.get_collection(cls.collection_name)
            q = {"form_id": ObjectId(form_id), "business_id": ObjectId(business_id)}

            total = c.count_documents(q)
            if total == 0:
                return {"total_submissions": 0}

            time_pipeline = [
                {"$match": {**q, "submission_time_seconds": {"$exists": True, "$gt": 0}}},
                {"$group": {"_id": None, "avg_time": {"$avg": "$submission_time_seconds"}, "min_time": {"$min": "$submission_time_seconds"}, "max_time": {"$max": "$submission_time_seconds"}}},
            ]
            time_agg = list(c.aggregate(time_pipeline))
            time_stats = time_agg[0] if time_agg else {"avg_time": 0, "min_time": 0, "max_time": 0}

            daily_pipeline = [
                {"$match": q},
                {"$addFields": {"day": {"$dateToString": {"format": "%Y-%m-%d", "date": "$created_at"}}}},
                {"$group": {"_id": "$day", "count": {"$sum": 1}}},
                {"$sort": {"_id": -1}},
                {"$limit": 30},
            ]
            daily = [{"date": r["_id"], "submissions": r["count"]} for r in c.aggregate(daily_pipeline)]

            form = Form.get_by_id(form_id, business_id, processing_callback=True)
            field_stats = {}
            if form:
                for fc in form.get("fields_config", []):
                    fid = fc.get("field_id")
                    ftype = fc.get("field_type")

                    if ftype in ("dropdown", "radio", "checkbox"):
                        cursor = c.find(q, {"responses": 1})
                        option_counts = {}
                        for doc in cursor:
                            for resp in doc.get("responses", []):
                                if resp.get("field_id") == fid:
                                    val = resp.get("value")
                                    if isinstance(val, list):
                                        for v in val:
                                            option_counts[v] = option_counts.get(v, 0) + 1
                                    elif val:
                                        option_counts[val] = option_counts.get(val, 0) + 1
                        field_stats[fid] = {"label": fc.get("label"), "type": ftype, "option_counts": option_counts}

                    elif ftype in ("rating",):
                        cursor = c.find(q, {"responses": 1})
                        ratings = []
                        for doc in cursor:
                            for resp in doc.get("responses", []):
                                if resp.get("field_id") == fid:
                                    try:
                                        ratings.append(float(resp.get("value", 0)))
                                    except Exception:
                                        pass
                        field_stats[fid] = {
                            "label": fc.get("label"),
                            "type": ftype,
                            "avg_rating": round(sum(ratings) / len(ratings), 1) if ratings else 0,
                            "total_ratings": len(ratings),
                        }

            completed = 0
            if form:
                required_ids = [f["field_id"] for f in form.get("fields_config", []) if f.get("required")]
                cursor = c.find(q, {"responses": 1})
                for doc in cursor:
                    resp_ids = {r.get("field_id") for r in doc.get("responses", []) if r.get("value")}
                    if all(rid in resp_ids for rid in required_ids):
                        completed += 1

            completion_rate = round((completed / total * 100), 1) if total > 0 else 0
            anon_count = c.count_documents({**q, "is_anonymous": True})

            return {
                "total_submissions": total,
                "completion_rate": completion_rate,
                "completed_submissions": completed,
                "anonymous_submissions": anon_count,
                "identified_submissions": total - anon_count,
                "avg_submission_time_seconds": round(time_stats.get("avg_time", 0), 1),
                "min_submission_time_seconds": round(time_stats.get("min_time", 0), 1),
                "max_submission_time_seconds": round(time_stats.get("max_time", 0), 1),
                "daily_submissions": daily,
                "field_stats": field_stats,
            }
        except Exception as e:
            Log.error(f"[FormSubmission.get_analytics] {e}")
            return {"total_submissions": 0}

    @classmethod
    def create_indexes(cls):
        try:
            c = db.get_collection(cls.collection_name)
            c.create_index([("business_id", 1), ("form_id", 1), ("created_at", -1)])
            c.create_index([("business_id", 1), ("branch_id", 1)])
            c.create_index([("business_id", 1), ("member_id", 1)])
            return True
        except Exception:
            return False