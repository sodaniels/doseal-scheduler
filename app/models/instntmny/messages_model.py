from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Union
from datetime import datetime
from bson import ObjectId

from app.extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data  # noqa: F401
from ..base_model import BaseModel
import os

ObjectIdLike = Union[str, ObjectId]

# --- Status constants & normalizer ---
STATUS_QUEUED     = "queued"
STATUS_DISPATCHED = "dispatched"
STATUS_FAILED     = "failed"

_ALLOWED_STATUSES = {STATUS_QUEUED, STATUS_DISPATCHED, STATUS_FAILED}

_STATUS_ALIASES = {
    # queued
    "queue": STATUS_QUEUED, "queued": STATUS_QUEUED, "queu": STATUS_QUEUED,
    "pending": STATUS_QUEUED, "enqueued": STATUS_QUEUED,
    # dispatched
    "dispatch": STATUS_DISPATCHED, "dispatched": STATUS_DISPATCHED,
    "sent": STATUS_DISPATCHED, "sending": STATUS_DISPATCHED, "delivered": STATUS_DISPATCHED,
    "accepted": STATUS_DISPATCHED, "queued": STATUS_DISPATCHED,  # Twilio's "queued" => we treat as dispatched internally
    # failed
    "fail": STATUS_FAILED, "failed": STATUS_FAILED, "undelivered": STATUS_FAILED, "error": STATUS_FAILED,
}

def _coerce_status_input(value) -> str:
    """
    Coerce incoming shapes (str/list/dict/None) to one of: queued | dispatched | failed.
    """
    if value is None:
        return STATUS_QUEUED
    if isinstance(value, (list, tuple, set)):
        if not value:
            return STATUS_QUEUED
        if isinstance(value, set):
            value = list(value)
        value = value[0]
    if isinstance(value, dict):
        value = value.get("status", "")
    s = str(value).strip().lower()
    s = _STATUS_ALIASES.get(s, s)
    if s not in _ALLOWED_STATUSES:
        raise ValueError(f"Invalid status {value!r}; must be one of {_ALLOWED_STATUSES}")
    return s

def _to_object_id(value: ObjectIdLike, *, field: str = "id") -> ObjectId:
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(str(value))
    except Exception:
        raise ValueError(f"Invalid {field}: {value!r}")


def _now() -> datetime:
    return datetime.now()


class Message(BaseModel):
    """
    Stores outbound messages linked to a contact and business.

    Encrypted at-rest fields: message, status, date, to
    References: contact_id (contacts._id), business_id, created_by, user_id
    """

    collection_name = "messages"

    def __init__(
        self,
        message: str,
        date: str,
        contact_id: ObjectIdLike,
        business_id: ObjectIdLike,
        user_id: ObjectIdLike,
        created_by: ObjectIdLike,
        *,
        status: str = STATUS_QUEUED,
        user__id: Optional[ObjectIdLike] = None,
        schedule_date: Optional[datetime] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
    ):
        super().__init__(business_id=business_id, user_id=user_id, user__id=user__id)

        # Core (encrypted at rest)
        self.message = encrypt_data(message)
        self.status = encrypt_data(self._validate_status(status))
        self.date = encrypt_data(date)

        # References
        self.contact_id = _to_object_id(contact_id, field="contact_id")
        self.business_id = _to_object_id(business_id, field="business_id")
        self.created_by = _to_object_id(created_by, field="created_by")
        self.user_id = _to_object_id(user_id, field="user_id")

        # Hashes for dedupe/lookups
        self.hashed_date = hash_data(date)
        self.hashed_message = hash_data(message)
        self.hashed_contact_id = hash_data(str(contact_id))

        # Timestamps
        now = _now()
        self.schedule_date = schedule_date or now
        self.created_at = created_at or now
        self.updated_at = updated_at or now
        self.status_updated_at = now

    # ---------------------------
    # Validation & transitions
    # ---------------------------
    @staticmethod
    def _validate_status(value: str) -> str:
        v = (value or "").strip().lower()
        if v not in _ALLOWED_STATUSES:
            raise ValueError(f"Invalid status {value!r}; must be one of {_ALLOWED_STATUSES}")
        return v

    # ---------------------------
    # Serialization
    # ---------------------------
    def to_dict(self) -> Dict[str, Any]:
        base = super().to_dict()
        base.update(
            {
                # encrypted fields
                "message": self.message,
                "date": self.date,
                "schedule_date": self.schedule_date,

                # references
                "contact_id": self.contact_id,
                "business_id": self.business_id,
                "created_by": self.created_by,
                "user_id": self.user_id,

                # hashes for dedupe
                "hashed_date": self.hashed_date,
                "hashed_message": self.hashed_message,
                "hashed_contact_id": self.hashed_contact_id,

                # timestamps
                "created_at": self.created_at,
                "updated_at": self.updated_at,
                "status_updated_at": self.status_updated_at,
            }
        )
        if getattr(self, "user__id", None):
            base["user__id"] = _to_object_id(self.user__id, field="user__id")
        return base

    # ---------------------------
    # CRUD
    # ---------------------------
    def save(self) -> str:
        col = db.get_collection(self.collection_name)
        res = col.insert_one(self.to_dict())
        return str(res.inserted_id)

    @classmethod
    def check_item_exists(cls, business_id, date, message, contact_id):
        try:
            hashed_date = hash_data(date)
            hashed_message = hash_data(message)
            hashed_contact_id = hash_data(contact_id)
            query = {
                "business_id": ObjectId(business_id),
                "hashed_date": hashed_date,
                "hashed_message": hashed_message,
                "hashed_contact_id": hashed_contact_id,
            }
            collection = db.get_collection(cls.collection_name)
            return bool(collection.find_one(query))
        except Exception as e:
            print(f"Error occurred: {e}")
            return False

    
    # Convenience creators / updaters for the 3-state flow
    @classmethod
    def _make_payload_entry(cls, *, sid: str, contact: Optional[str] = None,
                            status: Optional[str] = None, delivery_status: Optional[str] = None,
                            error_code: Optional[str] = None, error_message: Optional[str] = None,
                            price: Optional[str] = None, price_unit: Optional[str] = None,
                            num_segments: Optional[str] = None) -> Dict[str, Any]:
        entry: Dict[str, Any] = {
            "sid": sid,
            "contact": contact,
            "status": (_coerce_status_input(status) if status is not None else None),
            "delivery_status": (str(delivery_status).lower() if delivery_status is not None else None),
            "error_code": error_code,
            "error_message": error_message,
            "price": price,
            "price_unit": price_unit,
            "num_segments": num_segments,
            "created_at": _now(),
            "updated_at": _now(),
        }
        # Remove Nones so array equality is stable for unique indexes / comparisons
        return {k: v for k, v in entry.items() if v is not None}


    @classmethod
    def upsert_payload_detail(cls,
                            message_id: ObjectIdLike,
                            *,
                            sid: str,
                            fields: Dict[str, Any]) -> bool:
        """
        Update payload_detail entry by (message_id, sid). If not present, push a new entry.
        """
        oid = _to_object_id(message_id, field="message_id")
        col = db.get_collection(cls.collection_name)

        # 1) Ensure the array path exists (prevents "path must exist" error)
        col.update_one(
            {"_id": oid, "payload_detail": {"$exists": False}},
            {"$set": {"payload_detail": []}}
        )

        # 2) Build $set doc for arrayFilters update
        set_doc = {}
        for k, v in fields.items():
            if v is None:
                continue
            if k == "status":
                v = _coerce_status_input(v)
            if k == "delivery_status":
                v = str(v).lower()
            set_doc[f"payload_detail.$[p].{k}"] = v
        set_doc["payload_detail.$[p].updated_at"] = _now()

        modified = False

        # 3) Try in-place update on the matching element (sid)
        if set_doc:
            try:
                res = col.update_one(
                    {"_id": oid},
                    {"$set": set_doc},
                    array_filters=[{"p.sid": sid}],
                )
                modified = bool(res.modified_count)
            except Exception as e:
                # Path not existing (older Mongo) or other arrayFilters errors – we’ll push instead
                modified = False

        # 4) If no matching element, push a new entry with this sid
        if not modified:
            entry = cls._make_payload_entry(sid=sid, **fields)
            res2 = col.update_one(
                {"_id": oid, "payload_detail.sid": {"$ne": sid}},
                {"$push": {"payload_detail": entry}},
            )
            if not res2.modified_count:
                # Fallback push (creates array if somehow missing)
                res3 = col.update_one({"_id": oid}, {"$push": {"payload_detail": entry}})
                modified = bool(res3.modified_count)
            else:
                modified = True

        return modified

    @classmethod
    def update(cls, message_id: ObjectIdLike, **updates) -> bool:
        """
        Encrypts/normalizes specific fields; auto-bumps updated_at.
        Also mirrors key values into payload_detail (by message_id & sid)
        and maintains a top-level 'sids' array (unique list of all SIDs seen).
        Returns True if a doc was modified.
        """
        # --- capture plain values BEFORE encryption ---
        contact_plain         = updates.get("to")
        status_plain          = None
        if "status" in updates and isinstance(updates["status"], str):
            try:
                status_plain = _coerce_status_input(updates["status"])
            except Exception:
                status_plain = None
        delivery_status_plain = updates.get("delivery_status")
        error_code_plain      = updates.get("error_code")
        error_message_plain   = updates.get("error_message")
        price_plain           = updates.get("price")
        price_unit_plain      = updates.get("price_unit")
        num_segments_plain    = updates.get("num_segments")
        sid_plain             = updates.get("sid")
        if sid_plain is not None:
            sid_plain = str(sid_plain)

        # remove items we don't want to set at the top-level in this method
        updates.pop("sid", None)
        updates.pop("delivery_status", None)
        updates.pop("to", None)

        # --- normal $set updates (with encryption where applicable) ---
        if "message" in updates and updates["message"] is not None:
            updates["message"] = encrypt_data(updates["message"])

        if "status" in updates and updates["status"] is not None:
            if isinstance(updates["status"], str):
                # encrypt but don't keep plaintext around
                _ = encrypt_data(_coerce_status_input(updates["status"]))
            updates.setdefault("status_updated_at", _now())
        # we intentionally do not set top-level 'status' here
        updates.pop("status", None)

        if "date" in updates and updates["date"] is not None:
            updates["date"] = encrypt_data(updates["date"])

        # Normalize referenced IDs
        for ref_field in ("contact_id", "business_id", "created_by", "user_id", "user__id"):
            if ref_field in updates and updates[ref_field] is not None:
                updates[ref_field] = _to_object_id(updates[ref_field], field=ref_field)

        if "status_updated_at" not in updates and "status" in updates:
            updates["status_updated_at"] = _now()

        updates["updated_at"] = _now()

        # --- perform top-level update by message_id ---
        modified_any = super().update(message_id, **updates)

        # --- if a sid is present, (1) add to top-level sids and (2) mirror to payload_detail ---
        if sid_plain:
            oid = _to_object_id(message_id, field="message_id")
            col = db.get_collection(cls.collection_name)

            # (1) maintain a unique list of all SIDs seen on this message
            res_sids = col.update_one(
                {"_id": oid},
                {"$addToSet": {"sids": sid_plain}}
            )
            modified_any = modified_any or bool(res_sids.modified_count)

            # (2) mirror into payload_detail (per-recipient row addressed by sid)
            fields_for_payload = {
                "contact": contact_plain,
                "status": status_plain,
                "delivery_status": (str(delivery_status_plain).lower() if delivery_status_plain is not None else None),
                "error_code": error_code_plain,
                "error_message": error_message_plain,
                "price": price_plain,
                "price_unit": price_unit_plain,
                "num_segments": num_segments_plain,
            }
            cls.upsert_payload_detail(message_id, sid=sid_plain, fields=fields_for_payload)

        return bool(modified_any)

    @classmethod
    def update_by_sid(cls, *, sid: str, **updates) -> bool:
        """
        Update ONLY the per-recipient payload_detail entry selected by `sid`.
        Parent doc is located via $or: sids contains sid, payload_detail has sid, or legacy top-level sid.
        No top-level fields are modified.
        """
        if not sid:
            return False

        allowed = {
            "contact",
            "status",
            "delivery_status",
            "error_code",
            "error_message",
            "price",
            "price_unit",
            "num_segments",
        }
        fields_for_payload = {k: updates.get(k) for k in allowed if k in updates}
        if not fields_for_payload:
            return False

        return cls._upsert_payload_detail_by_sid(sid=sid, fields=fields_for_payload)

    @classmethod
    def delete(cls, message_id: ObjectIdLike, business_id: ObjectIdLike) -> bool:
        return super().delete(message_id, business_id)

    # ---------------------------
    # Reads
    # ---------------------------
    @classmethod
    def get_by_id(
        cls,
        message_id: ObjectIdLike,
        business_id: ObjectIdLike,
        *,
        include_contact: bool = True,
        decrypt: bool = True,
    ) -> Optional[Dict[str, Any]]:
        mid = _to_object_id(message_id, field="message_id")
        bid = _to_object_id(business_id, field="business_id")
        col = db.get_collection(cls.collection_name)

        if include_contact:
            pipeline = [
                {"$match": {"_id": mid, "business_id": bid}},
                _lookup_contact_stage(),
                {"$unwind": {"path": "$contact", "preserveNullAndEmptyArrays": True}},
                {"$limit": 1},
            ]
            docs = list(col.aggregate(pipeline))
            if not docs:
                return None
            return _post_process_message_doc(docs[0], decrypt=decrypt)
        else:
            doc = col.find_one({"_id": mid, "business_id": bid})
            if not doc:
                return None
            return _post_process_message_doc(doc, decrypt=decrypt)

    @classmethod
    def get_all(
        cls,
        business_id: ObjectIdLike,
        page: Optional[int] = 1,
        per_page: Optional[int] = 10,
        *,
        include_contact: bool = True,
        decrypt: bool = True,
        sort: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", "1"))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", "10"))
        page = max(1, int(page or default_page))
        per_page = max(1, int(per_page or default_per_page))

        bid = _to_object_id(business_id, field="business_id")
        col = db.get_collection(cls.collection_name)
        sort_spec = sort or {"created_at": -1}

        pipeline = [{"$match": {"business_id": bid}}]

        if include_contact:
            pipeline.append(_lookup_contact_stage())
            pipeline.append({"$unwind": {"path": "$contact", "preserveNullAndEmptyArrays": True}})

        # ---- NEW: add per-message counts from payload_detail ----
        # Use $ifNull to handle missing arrays, and case-insensitive compare
        payload_safe = {"$ifNull": ["$payload_detail", []]}
        pipeline.append(
            {"$addFields": {
                "dispatched_count": {
                    "$size": {
                        "$filter": {
                            "input": payload_safe,
                            "as": "p",
                            "cond": {
                                "$eq": [
                                    { "$toLower": { "$ifNull": ["$$p.status", ""] } },
                                    "dispatched"
                                ]
                            }
                        }
                    }
                },
                "delivered_count": {
                    "$size": {
                        "$filter": {
                            "input": payload_safe,
                            "as": "p",
                            "cond": {
                                "$eq": [
                                    { "$toLower": { "$ifNull": ["$$p.delivery_status", ""] } },
                                    "delivered"
                                ]
                            }
                        }
                    }
                }
            }}
        )
        # --------------------------------------------------------

        pipeline.extend(
            [
                {"$sort": sort_spec},
                {
                    "$facet": {
                        "meta": [{"$count": "total"}],
                        "data": [
                            {"$skip": (page - 1) * per_page},
                            {"$limit": per_page},
                        ],
                    }
                },
            ]
        )

        agg = list(col.aggregate(pipeline))
        if not agg:
            total_count = 0
            docs = []
        else:
            meta = agg[0].get("meta", [])
            total_count = int(meta[0]["total"]) if meta else 0
            docs = agg[0].get("data", [])

        items: List[Dict[str, Any]] = [_post_process_message_doc(d, decrypt=decrypt) for d in docs]
        total_pages = (total_count + per_page - 1) // per_page

        return {
            "messages": items,
            "total_count": total_count,
            "total_pages": total_pages,
            "page": page,
            "per_page": per_page,
        }

    @classmethod
    def apply_twilio_status_webhook(cls, payload: Dict[str, Any]) -> bool:
        """
        Apply a Twilio status callback payload to a stored message, located by SID.
        Maps Twilio MessageStatus -> internal 3-state status and stores delivery details.
        """
        # Accept both our normalized keys and Twilio's raw form keys
        sid = payload.get("message_sid") or payload.get("MessageSid")
        if not sid:
            return False

        tw_status = (payload.get("status") or payload.get("MessageStatus") or "").lower()
        to_num = payload.get("to") or payload.get("To")
        from_display = payload.get("from") or payload.get("From")
        error_code = payload.get("error_code") or payload.get("ErrorCode")
        error_message = payload.get("error_message") or payload.get("ErrorMessage")
        price = payload.get("price") or payload.get("Price")
        price_unit = payload.get("price_unit") or payload.get("PriceUnit")
        num_segments = payload.get("num_segments") or payload.get("NumSegments")

        # Map Twilio statuses to our internal 3-state:
        # - failed/undelivered -> FAILED
        # - anything else (queued/sending/sent/delivered/accepted/…) -> DISPATCHED
        internal_status = STATUS_FAILED if tw_status in ("failed", "undelivered") else STATUS_DISPATCHED

        updates: Dict[str, Any] = {
            "status": internal_status,          # encrypted inside update_by_sid()
            "delivery_status": tw_status,       # encrypted inside update_by_sid()
            "error_code": error_code,
            "error_message": error_message,
            "twilio_from": from_display,        # alpha sender or number; stored plain
            "price": price,
            "price_unit": price_unit,
            "num_segments": num_segments,
        }

        # Capture delivery moment
        if tw_status == "delivered":
            updates["delivered_at"] = _now()

        if to_num:
            updates["to"] = to_num  # will be encrypted + hashed in update_by_sid()

        return cls.update_by_sid(sid, **updates)

    @classmethod
    def _upsert_payload_detail_where_sids_contains(cls, *, sid: str, fields: Dict[str, Any]) -> bool:
        """
        Upsert payload_detail entry by locating the parent document whose `sids` array contains `sid`.
        If an entry with this sid exists inside payload_detail, update it in-place via arrayFilters;
        otherwise push a new entry.
        """
        col = db.get_collection(cls.collection_name)

        # 1) Ensure the array path exists on the matched parent (prevents 'path must exist' errors)
        col.update_one(
            {"sids": sid, "payload_detail": {"$exists": False}},
            {"$set": {"payload_detail": []}}
        )

        # 2) Build $set doc for in-place update
        set_doc: Dict[str, Any] = {}
        for k, v in fields.items():
            if v is None:
                continue
            if k == "status":
                v = _coerce_status_input(v)
            if k == "delivery_status":
                v = str(v).lower()
            set_doc[f"payload_detail.$[p].{k}"] = v
        set_doc["payload_detail.$[p].updated_at"] = _now()

        modified = False

        # 3) Try in-place update of the matching element (payload_detail.$[p] where p.sid == sid)
        if set_doc:
            try:
                res = col.update_one(
                    {"sids": sid},
                    {"$set": set_doc},
                    array_filters=[{"p.sid": sid}],
                )
                modified = bool(res.modified_count)
            except Exception:
                modified = False  # fall through to push

        # 4) If no matching payload_detail element, push a new one with this sid
        if not modified:
            entry = cls._make_payload_entry(
                sid=sid,
                contact=fields.get("contact"),
                status=fields.get("status"),
                delivery_status=fields.get("delivery_status"),
                error_code=fields.get("error_code"),
                error_message=fields.get("error_message"),
                price=fields.get("price"),
                price_unit=fields.get("price_unit"),
                num_segments=fields.get("num_segments"),
            )

            # push only if not already present; if nothing matched (e.g. array exists but no sid), push anyway
            res2 = col.update_one(
                {"sids": sid, "payload_detail.sid": {"$ne": sid}},
                {"$push": {"payload_detail": entry}},
            )
            if not res2.modified_count:
                res3 = col.update_one(
                    {"sids": sid},
                    {"$push": {"payload_detail": entry}},
                )
                modified = bool(res3.modified_count)
            else:
                modified = True

        return modified

    @classmethod
    def _upsert_payload_detail_by_sid(cls, *, sid: str, fields: Dict[str, Any]) -> bool:
        """
        Robust, race-safe upsert for payload_detail[sid]:
        1) Try in-place $set via arrayFilters (updates ALL elements with this sid).
        2) If none modified, atomically push a new element only if sid not present,
            and add sid to parent sids at the same time.
        3) Try in-place $set again (covers the race where another thread pushed first).
        """
        col = db.get_collection(cls.collection_name)

        parent_filter = {
            "$or": [
                {"sids": sid},
                {"payload_detail.sid": sid},
                {"sid": sid},  # legacy
            ]
        }

        # Ensure array exists on matched doc (no-op if present)
        col.update_one(
            {"$and": [parent_filter, {"payload_detail": {"$exists": False}}]},
            {"$set": {"payload_detail": []}}
        )

        # Build $set for in-place update
        set_doc: Dict[str, Any] = {}
        for k, v in (fields or {}).items():
            if v is None:
                continue
            if k == "status":
                v = _coerce_status_input(v)
            if k == "delivery_status":
                v = str(v).lower()
            set_doc[f"payload_detail.$[p].{k}"] = v
        set_doc["payload_detail.$[p].updated_at"] = _now()

        # 1) Update existing element(s) for this SID (handles re-entrant callbacks cleanly)
        if set_doc:
            res1 = col.update_one(
                parent_filter,
                {"$set": set_doc},
                array_filters=[{"p.sid": sid}],
            )
            if res1.modified_count:
                # Also make sure the SID is tracked at top level (idempotent)
                col.update_one(parent_filter, {"$addToSet": {"sids": sid}})
                return True

        # 2) Atomically push if the SID is not already present
        entry = cls._make_payload_entry(
            sid=sid,
            contact=fields.get("contact"),
            status=fields.get("status"),
            delivery_status=fields.get("delivery_status"),
            error_code=fields.get("error_code"),
            error_message=fields.get("error_message"),
            price=fields.get("price"),
            price_unit=fields.get("price_unit"),
            num_segments=fields.get("num_segments"),
        )

        res2 = col.update_one(
            {
                "$and": [
                    parent_filter,
                    {"payload_detail.sid": {"$ne": sid}},   # guards double-push under race
                ]
            },
            {
                "$push": {"payload_detail": entry},
                "$addToSet": {"sids": sid},
            },
        )
        if res2.modified_count:
            return True

        # 3) Another thread likely pushed first; do the in-place update now
        if set_doc:
            res3 = col.update_one(
                parent_filter,
                {"$set": set_doc},
                array_filters=[{"p.sid": sid}],
            )
            # Ensure top-level 'sids' contains sid
            col.update_one(parent_filter, {"$addToSet": {"sids": sid}})
            return bool(res3.modified_count)

        return False
# ---------------------------
# Aggregation helpers
# ---------------------------
def _lookup_contact_stage() -> dict:
    return {
        "$lookup": {
            "from": "contacts",
            "let": {"cid": "$contact_id", "bid": "$business_id"},
            "pipeline": [
                {
                    "$match": {
                        "$expr": {
                            "$and": [
                                {
                                    "$eq": [
                                        "$_id",
                                        {
                                            "$cond": [
                                                {"$eq": [{"$type": "$$cid"}, "string"]},
                                                {"$toObjectId": "$$cid"},
                                                "$$cid",
                                            ]
                                        },
                                    ]
                                },
                                {"$eq": ["$business_id", "$$bid"]},
                            ]
                        }
                    }
                },
                {
                    "$project": {
                        "_id": 1,
                        "name": 1,       # encrypted at rest
                        "contacts": 1,   # encrypted at rest
                    }
                },
            ],
            "as": "contact",
        }
    }


def _post_process_message_doc(doc: Dict[str, Any], *, decrypt: bool = True) -> Dict[str, Any]:
    # Stringify top-level ObjectIds
    for key in ("_id", "business_id", "created_by", "user_id", "contact_id"):
        if key in doc and isinstance(doc[key], ObjectId):
            doc[key] = str(doc[key])

    # Decrypt fields
    if decrypt and doc.get("message"):
        try:
            doc["message"] = decrypt_data(doc["message"])
        except Exception:
            pass
    if decrypt and doc.get("status"):
        try:
            doc["status"] = decrypt_data(doc["status"])
        except Exception:
            pass
    if decrypt and doc.get("date"):
        try:
            doc["date"] = decrypt_data(doc["date"])
        except Exception:
            pass
    if decrypt and doc.get("to"):
        try:
            doc["to"] = decrypt_data(doc["to"])
        except Exception:
            pass
        
    if decrypt and doc.get("delivery_status"):
        try:
            doc["delivery_status"] = decrypt_data(doc["delivery_status"])
        except Exception:
            pass

    # Embedded contact (if any)
    contact = doc.pop("contact", None)
    if isinstance(contact, dict):
        if "_id" in contact and isinstance(contact["_id"], ObjectId):
            contact["_id"] = str(contact["_id"])
        if decrypt:
            for fld in ("name", "contacts"):
                if fld in contact and contact[fld]:
                    try:
                        contact[fld] = decrypt_data(contact[fld])
                    except Exception:
                        pass
        contacts_val = contact.get("contacts")
        contacts_list = None
        if isinstance(contacts_val, list):
            contacts_list = contacts_val
        elif isinstance(contacts_val, str):
            parsed = None
            try:
                parsed = json.loads(contacts_val)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                contacts_list = parsed
            else:
                parts = [p.strip() for p in contacts_val.replace("\n", ",").split(",") if p.strip()]
                contacts_list = parts or None
        contact["contact_count"] = len(contacts_list) if contacts_list is not None else 0
        contact.pop("contacts", None)
        doc["contact"] = contact

    # Remove internal/hash fields from outward responses
    for key in ("user__id", "hashed_contact_id", "hashed_date", "hashed_message", "hashed_to"):
        doc.pop(key, None)

    return doc
