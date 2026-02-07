#app/models/social/scheduled_post.py

from datetime import datetime, timezone
from bson import ObjectId
from pymongo import ReturnDocument
from typing import Optional, Dict, Any, List, Union

from ..base_model import BaseModel
from ...extensions import db as db_ext
from ...utils.logger import Log


class ScheduledPost(BaseModel):
    collection_name = "scheduled_posts"

    STATUS_DRAFT = "draft"
    STATUS_SCHEDULED = "scheduled"
    STATUS_ENQUEUED = "enqueued"
    STATUS_PUBLISHING = "publishing"
    STATUS_PENDING = "pending"
    STATUS_PUBLISHED = "published"
    STATUS_FAILED = "failed"
    STATUS_PARTIAL = "partial"
    STATUS_CANCELLED = "cancelled"
    STATUS_SUSPENDED_HOLD = "suspended_hold"
    STATUS_MISSED_SUSPENSION = "missed_suspension"
    STATUS_HELD = "held"

    def __init__(
        self,
        business_id,
        user__id,
        content,
        scheduled_at_utc,
        destinations,
        platform="multi",
        status=None,
        provider_results=None,
        error=None,
        created_by=None,
        **kwargs
    ):
        super().__init__(business_id=business_id, user__id=user__id, created_by=created_by, **kwargs)

        self.platform = platform  # "facebook" or "multi"

        # {"text": "...", "link": "...", "media": {...optional...}}
        self.content = content or {}

        # Always store UTC datetime
        self.scheduled_at_utc = scheduled_at_utc

        # [{"platform":"facebook","destination_type":"page","destination_id":"123"}]
        self.destinations = destinations or []

        self.status = status or self.STATUS_SCHEDULED
        self.provider_results = provider_results or []
        self.error = error

        self.created_at = datetime.now(timezone.utc)
        self.updated_at = datetime.now(timezone.utc)

    def to_dict(self):
        return {
            "business_id": self.business_id,
            "user__id": self.user__id,
            "platform": self.platform,

            "content": self.content,
            "scheduled_at_utc": self.scheduled_at_utc,
            "destinations": self.destinations,

            "status": self.status,
            "provider_results": self.provider_results,
            "error": self.error,

            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    # -------------------------
    # Helpers
    # -------------------------

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        if isinstance(value, datetime):
            # ensure tz-aware UTC
            if value.tzinfo is None:
                return value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc)
        if isinstance(value, str):
            # allow "Z"
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        return None

    @staticmethod
    def _oid_str(doc):
        if not doc:
            return None
        if "_id" in doc:
            doc["_id"] = str(doc["_id"])
        if "business_id" in doc:
            doc["business_id"] = str(doc["business_id"])
        if "user__id" in doc:
            doc["user__id"] = str(doc["user__id"])
        return doc

    # -------------------------
    # CRUD
    # -------------------------

    @classmethod
    def create(cls, doc: dict):
        """
        Insert a scheduled post document into MongoDB.

        Expects doc to include:
        business_id, user__id, content, scheduled_at_utc, destinations
        """

        col = db_ext.get_collection(cls.collection_name)
        insert_doc = dict(doc or {})

        # --------------------------------------------------
        # REQUIRED OWNER FIELDS
        # --------------------------------------------------
        if not insert_doc.get("business_id") or not insert_doc.get("user__id"):
            raise ValueError("business_id and user__id are required")

        insert_doc["business_id"] = ObjectId(str(insert_doc["business_id"]))
        insert_doc["user__id"] = ObjectId(str(insert_doc["user__id"]))

        # --------------------------------------------------
        # SCHEDULE TIME
        # --------------------------------------------------
        insert_doc["scheduled_at_utc"] = cls._parse_dt(insert_doc.get("scheduled_at_utc"))
        if not insert_doc["scheduled_at_utc"]:
            raise ValueError("scheduled_at_utc is required and must be ISO string or datetime")

        # --------------------------------------------------
        # NORMALIZE CONTENT / MEDIA
        # --------------------------------------------------
        content = insert_doc.get("content") or {}
        media = content.get("media")

        # normalize to list
        if isinstance(media, dict):
            media = [media]
        elif not isinstance(media, list):
            media = []

        normalized_media = []
        for m in media:
            if not isinstance(m, dict):
                continue

            asset_type = (m.get("asset_type") or "").lower()

            media_doc = {
                "asset_id": m.get("asset_id") or m.get("public_id"),
                "public_id": m.get("public_id"),
                "asset_provider": m.get("asset_provider") or "cloudinary",
                "asset_type": asset_type,
                "url": m.get("url"),

                # metadata (VERY important for reels)
                "bytes": m.get("bytes"),
                "duration": m.get("duration"),
                "format": m.get("format"),
                "width": m.get("width"),
                "height": m.get("height"),

                "created_at": m.get("created_at") or datetime.now(timezone.utc),
            }

            normalized_media.append(media_doc)

        content["media"] = normalized_media or None
        insert_doc["content"] = content

        # --------------------------------------------------
        # DEFAULT FIELDS
        # --------------------------------------------------
        insert_doc.setdefault("platform", "multi")
        insert_doc.setdefault("destinations", [])
        insert_doc.setdefault("status", cls.STATUS_SCHEDULED)

        now = datetime.now(timezone.utc)
        insert_doc.setdefault("provider_results", [])
        insert_doc.setdefault("error", None)
        insert_doc.setdefault("created_at", now)
        insert_doc.setdefault("updated_at", now)

        # --------------------------------------------------
        # INSERT
        # --------------------------------------------------
        res = col.insert_one(insert_doc)
        insert_doc["_id"] = res.inserted_id

        return cls._oid_str(insert_doc)

    @classmethod
    def get_by_id(cls, post_id: str, business_id: str):
        col = db_ext.get_collection(cls.collection_name)
        doc = col.find_one({
            "_id": ObjectId(str(post_id)),
            "business_id": ObjectId(str(business_id)),
        })
        return cls._oid_str(doc)

    @classmethod
    def get_due_posts(cls, limit=50):
        """Fetch scheduled posts that are due now (UTC)."""
        col = db_ext.get_collection(cls.collection_name)
        now = datetime.now(timezone.utc)
        return list(col.find({
            "status": cls.STATUS_SCHEDULED,
            "scheduled_at_utc": {"$lte": now},
        }).sort("scheduled_at_utc", 1).limit(limit))

    # -------------------------
    # Atomic scheduler support
    # -------------------------

    @classmethod
    def claim_due_posts(cls, limit=50):
        """
        IMPORTANT (scales well):
        Atomically move due posts from scheduled -> enqueued
        so only ONE scheduler process can enqueue them.
        """
        col = db_ext.get_collection(cls.collection_name)
        now = datetime.now(timezone.utc)

        claimed = []
        for _ in range(limit):
            doc = col.find_one_and_update(
                {
                    "status": cls.STATUS_SCHEDULED,
                    "scheduled_at_utc": {"$lte": now},
                },
                {
                    "$set": {
                        "status": cls.STATUS_ENQUEUED,
                        "updated_at": now,
                    }
                },
                sort=[("scheduled_at_utc", 1)],
                return_document=ReturnDocument.AFTER,
            )
            if not doc:
                break
            claimed.append(cls._oid_str(doc))
        return claimed

    # -------------------------
    # Status updates
    # -------------------------

    @classmethod
    def update_status(cls, post_id, business_id, status, **extra):
        col = db_ext.get_collection(cls.collection_name)
        extra = extra or {}
        extra["status"] = status
        extra["updated_at"] = datetime.now(timezone.utc)

        res = col.update_one(
            {"_id": ObjectId(str(post_id)), "business_id": ObjectId(str(business_id))},
            {"$set": extra}
        )
        return res.modified_count > 0

    # ----------------------------------------
    # LIST BY BUSINESS
    # ----------------------------------------
    @classmethod
    def list_by_business_id(
        cls,
        *,
        business_id: str,
        page: int = 1,
        per_page: int = 20,
        status: Optional[str] = None,

        # ✅ platform filter means destination platform(s)
        platform: Optional[Union[str, List[str]]] = None,

        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
    ) -> Dict[str, Any]:

        log_tag = f"[scheduled_post.py][ScheduledPost][list_by_business_id][business_id={business_id}]"

        try:
            collection = db_ext.get_collection(cls.collection_name)

            query: Dict[str, Any] = {"business_id": ObjectId(str(business_id))}

            # -----------------------------
            # OPTIONAL FILTERS
            # -----------------------------
            if status:
                query["status"] = status

            # ✅ platform(s) => match destinations[].platform
            if platform:
                if isinstance(platform, str):
                    # allow "instagram,facebook" OR single "instagram"
                    platform_list = [p.strip().lower() for p in platform.split(",") if p.strip()]
                else:
                    platform_list = [str(p).strip().lower() for p in platform if str(p).strip()]

                if platform_list:
                    query["destinations"] = {
                        "$elemMatch": {"platform": {"$in": platform_list}}
                    }

            # ✅ date range (correct field)
            if date_from or date_to:
                q = {}
                if date_from:
                    q["$gte"] = cls._parse_dt(date_from)
                if date_to:
                    q["$lte"] = cls._parse_dt(date_to)
                query["scheduled_at_utc"] = q

            # -----------------------------
            # PAGINATION
            # -----------------------------
            page = max(int(page), 1)
            per_page = min(max(int(per_page), 1), 100)
            skip = (page - 1) * per_page

            total_count = collection.count_documents(query)

            cursor = (
                collection.find(query)
                .sort("scheduled_at_utc", -1)
                .skip(skip)
                .limit(per_page)
            )

            items = list(cursor)

            for doc in items:
                doc["_id"] = str(doc["_id"])
                doc["business_id"] = str(doc["business_id"])
                doc["user__id"] = str(doc["user__id"])

                for k in ("created_at", "updated_at", "scheduled_at_utc"):
                    if doc.get(k) and hasattr(doc[k], "isoformat"):
                        doc[k] = doc[k].isoformat()

            total_pages = (total_count + per_page - 1) // per_page

            return {
                "items": items,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }

        except Exception as e:
            Log.error(f"{log_tag} ERROR: {e}")
            return {
                "items": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page,
                "per_page": per_page,
            }     
           
    # ----------------------------------------
    # UPDATE FIELDS (generic safe updater)
    # ----------------------------------------
    @classmethod
    def update_fields(
        cls,
        post_id: str,
        business_id: str,
        updates: Dict[str, Any],
    ) -> bool:
        """
        Update arbitrary fields on a scheduled post (business-scoped).

        Notes:
        - Always sets updated_at
        - Removes immutable keys if accidentally passed
        - Returns True if a document was modified
        """
        if not updates or not isinstance(updates, dict):
            return False

        col = db_ext.get_collection(cls.collection_name)

        # never allow these to be overwritten via update_fields
        updates = dict(updates)
        updates.pop("_id", None)
        updates.pop("business_id", None)
        updates.pop("user__id", None)
        updates.pop("created_at", None)

        updates["updated_at"] = datetime.now(timezone.utc)

        res = col.update_one(
            {"_id": ObjectId(str(post_id)), "business_id": ObjectId(str(business_id))},
            {"$set": updates},
        )
        return res.modified_count > 0

    # ----------------------------------------
    # UPDATE BY ID (wrapper with common fields)
    # ----------------------------------------
    @classmethod
    def update_by_id(
        cls,
        post_id: str,
        business_id: str,
        *,
        content: Optional[Dict[str, Any]] = None,
        destinations: Optional[list] = None,
        scheduled_at_utc: Optional[Any] = None,  # datetime or iso string (depending on your _parse_dt)
        status: Optional[str] = None,
        error: Optional[str] = None,
        provider_results: Optional[list] = None,
        manual_required: Optional[list] = None,
        mode: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Opinionated updater for the common scheduled-post fields.
        Uses update_fields() underneath.

        - scheduled_at_utc is stored as datetime (via cls._parse_dt if you already have it)
        - content/destinations overwrite completely when provided
        """
        updates: Dict[str, Any] = {}

        if content is not None:
            updates["content"] = content

        if destinations is not None:
            updates["destinations"] = destinations

        if scheduled_at_utc is not None:
            # if you already have cls._parse_dt used elsewhere, use it here
            try:
                updates["scheduled_at_utc"] = cls._parse_dt(scheduled_at_utc)
            except Exception:
                # fallback: store as-is (but ideally fix upstream)
                updates["scheduled_at_utc"] = scheduled_at_utc

            # optional: keep string mirror field if your UI expects it
            try:
                dt = updates["scheduled_at_utc"]
                if hasattr(dt, "isoformat"):
                    updates["scheduled_at"] = dt.isoformat()
            except Exception:
                pass

        if status is not None:
            updates["status"] = status

        if error is not None:
            updates["error"] = error

        if provider_results is not None:
            updates["provider_results"] = provider_results

        if manual_required is not None:
            updates["manual_required"] = manual_required

        if mode is not None:
            updates["mode"] = mode

        if extra and isinstance(extra, dict):
            # allow custom fields (e.g. "title", "draft_name", etc.)
            for k, v in extra.items():
                updates[k] = v

        return cls.update_fields(post_id, business_id, updates)
     
    # ----------------------------------------
    # SUSPEND schedulling
    # ----------------------------------------
    @classmethod
    def mark_missed_due_to_suspension(
        cls,
        *,
        post_id: str,
        business_id: str,
        reason: str = None,
        suspended_at: Any = None,
    ) -> bool:
        """
        Mark a scheduled/enqueued post as missed because org was suspended at publish-time.
        """
        extra = {
            "status": cls.STATUS_MISSED_SUSPENSION,
            "missed_reason": (reason or "").strip() or "Publishing suspended",
            "missed_at": datetime.now(timezone.utc),
        }
        if suspended_at:
            try:
                extra["suspended_at"] = cls._parse_dt(suspended_at) or suspended_at
            except Exception:
                extra["suspended_at"] = suspended_at

        return cls.update_fields(post_id, business_id, extra)

    @classmethod
    def mark_suspended_hold(
        cls,
        *,
        post_id: str,
        business_id: str,
        reason: str = None,
        suspended_at: Any = None,
    ) -> bool:
        """
        Optional: freeze future scheduled posts immediately when suspension happens.
        """
        extra = {
            "status": cls.STATUS_SUSPENDED_HOLD,
            "hold_reason": (reason or "").strip() or "Publishing suspended",
            "hold_at": datetime.now(timezone.utc),
        }
        if suspended_at:
            extra["suspended_at"] = suspended_at

        return cls.update_fields(post_id, business_id, extra)
    
    
    @classmethod
    def ensure_indexes(cls):
        col = db_ext.get_collection(cls.collection_name)

        # scheduler reads
        col.create_index([("status", 1), ("scheduled_at_utc", 1)])

        # listing per tenant/user
        col.create_index([("business_id", 1), ("user__id", 1), ("created_at", -1)])

        # optional: faster multi-destination queries later
        col.create_index([("business_id", 1), ("status", 1), ("scheduled_at_utc", 1)])
        return True