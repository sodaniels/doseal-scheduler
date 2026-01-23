# app/models/promo.py

from datetime import datetime
from typing import Optional, Any
from bson.objectid import ObjectId
from app.extensions.db import db

from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ..base_model import BaseModel


class Promo(BaseModel):
    collection_name = "promos"

    # -------------------- Encryption Helpers --------------------
    @staticmethod
    def _enc(v: Any) -> Optional[str]:
        return encrypt_data(str(v)) if v is not None else None

    @staticmethod
    def _dec(v: Optional[str]) -> Optional[str]:
        return decrypt_data(v) if v is not None else None

    @staticmethod
    def _dec_float(v: Optional[str]) -> Optional[float]:
        return float(decrypt_data(v)) if v is not None else None

    @staticmethod
    def _dec_int(v: Optional[str]) -> Optional[int]:
        return int(decrypt_data(v)) if v is not None else None

    @staticmethod
    def _dec_bool(v: Optional[str]) -> bool:
        return decrypt_data(v) == "True" if v is not None else False

    @staticmethod
    def _parse_iso(raw: str) -> datetime:
        raw = raw.strip()
        if len(raw) == 10:  # YYYY-MM-DD
            raw = raw + "T00:00:00"
        return datetime.fromisoformat(raw)

    @staticmethod
    def _safe_str(v):
        return str(v) if v is not None else None

    # -------------------- Constructor --------------------
    def __init__(
        self,
        promo_name: str,
        promo_amount: float,
        promo_category: str,
        promo_start_date: str,
        promo_end_date: str,
        promo_threshold: int,
        promo_status: bool,
        promo_limit: Optional[int] = None,
        promo_total_allowable_limit: Optional[int] = None,
        business_id: Optional[str | ObjectId] = None,
        created_by: Optional[str | ObjectId] = None,
        user_id: Optional[str | ObjectId] = None,
        user__id: Optional[str | ObjectId] = None,
    ):
        super().__init__(business_id=business_id, user__id=user__id)

        start_dt = self._parse_iso(promo_start_date)
        end_dt = self._parse_iso(promo_end_date)
        if end_dt < start_dt:
            raise ValueError("promo_end_date must be on/after promo_start_date")

        self.business_id = business_id
        self.created_by = created_by
        self.hashed_promo_name = hash_data(promo_name)

        # Encrypted fields
        self.promo_name = self._enc(promo_name)
        self.promo_amount = self._enc(float(promo_amount))
        self.promo_category = self._enc(promo_category)
        self.promo_start_date = self._enc(start_dt.isoformat())
        self.promo_end_date = self._enc(end_dt.isoformat())
        self.promo_limit = self._enc(int(promo_limit)) if promo_limit is not None else None
        self.promo_threshold = self._enc(int(promo_threshold))
        self.promo_status = self._enc(bool(promo_status))
        self.promo_total_allowable_limit = (
            self._enc(int(promo_total_allowable_limit)) if promo_total_allowable_limit is not None else None
        )

        # Queryable fields for active promo detection
        self.promo_start_at = start_dt
        self.promo_end_at = end_dt
        self.promo_status_bool = bool(promo_status)

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    # -------------------- Serialization --------------------
    def to_dict(self):
        data = super().to_dict()
        data.update({
            "promo_name": self.promo_name,
            "hashed_promo_name": self.hashed_promo_name,
            "promo_amount": self.promo_amount,
            "promo_category": self.promo_category,
            "promo_start_date": self.promo_start_date,
            "promo_end_date": self.promo_end_date,
            "promo_limit": self.promo_limit,
            "promo_threshold": self.promo_threshold,
            "promo_status": self.promo_status,
            "promo_total_allowable_limit": self.promo_total_allowable_limit,
            "promo_start_at": self.promo_start_at,
            "promo_end_at": self.promo_end_at,
            "promo_status_bool": self.promo_status_bool,
            "business_id": self.business_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return data

    
    # -------------------- Create --------------------
    @classmethod
    def create(cls, **kwargs):
        promo = cls(**kwargs)
        return promo.save()

    # -------------------- Get by ID --------------------
    @classmethod
    def get_by_id(cls, business_id, promo_id):
        try:
            promo_oid = ObjectId(promo_id)
            business_oid = ObjectId(business_id)
        except:
            return None

        col = db.get_collection(cls.collection_name)
        d = col.find_one({"_id": promo_oid, "business_id": business_oid})
        if not d:
            return None

        return {
            "_id": cls._safe_str(d["_id"]),
            "business_id": cls._safe_str(d["business_id"]),
            "promo_name": cls._dec(d["promo_name"]),
            "promo_amount": cls._dec_float(d["promo_amount"]),
            "promo_category": cls._dec(d["promo_category"]),
            "promo_start_date": cls._dec(d["promo_start_date"]),
            "promo_end_date": cls._dec(d["promo_end_date"]),
            "promo_limit": cls._dec_int(d.get("promo_limit")),
            "promo_threshold": cls._dec_int(d["promo_threshold"]),
            "promo_status": cls._dec_bool(d["promo_status"]),
            "promo_total_allowable_limit": cls._dec_int(d.get("promo_total_allowable_limit")),
            "created_at": d.get("created_at"),
            "updated_at": d.get("updated_at"),
        }

    # -------------------- Update --------------------
    @classmethod
    def update(cls, promo_id, business_id, **updates):
        ALLOWED = {
            "promo_name", "promo_amount", "promo_category",
            "promo_start_date", "promo_end_date",
            "promo_limit", "promo_threshold",
            "promo_status", "promo_total_allowable_limit",
        }
        clean = {k: v for k, v in updates.items() if k in ALLOWED}
        if not clean:
            return False

        try:
            business_oid = ObjectId(business_id)
            promo_oid = ObjectId(promo_id)
        except:
            return False

        col = db.get_collection(cls.collection_name)
        if not col.find_one({"_id": promo_oid, "business_id": business_oid}):
            return False

        encrypted_updates = {}
        normalized_updates = {}

        for k, v in clean.items():

            if k == "promo_amount" and v is not None:
                v = float(v)

            if k in ("promo_limit", "promo_threshold", "promo_total_allowable_limit") and v is not None:
                v = int(v)

            if k == "promo_status" and v is not None:
                v = bool(v)

            if k in ("promo_start_date", "promo_end_date") and v is not None:
                dt = cls._parse_iso(str(v))
                encrypted_updates[k] = cls._enc(dt.isoformat())
                normalized_updates["promo_start_at" if k == "promo_start_date" else "promo_end_at"] = dt
                continue

            if k == "promo_name":
                encrypted_updates["hashed_promo_name"] = hash_data(v)

            encrypted_updates[k] = cls._enc(v)

        if "promo_status" in clean:
            normalized_updates["promo_status_bool"] = bool(clean["promo_status"])

        encrypted_updates.update(normalized_updates)
        encrypted_updates["updated_at"] = datetime.utcnow()

        return super().update(promo_id, business_oid, **encrypted_updates)

    # -------------------- Get All --------------------
    @classmethod
    def get_all(cls, business_id, page=1, per_page=10, promo_status=None, promo_category=None):
        try:
            business_oid = ObjectId(business_id)
        except:
            return None

        page = int(page) if str(page).isdigit() else 1
        per_page = int(per_page) if str(per_page).isdigit() else 10

        col = db.get_collection(cls.collection_name)

        query = {"business_id": business_oid}
        if promo_status is not None:
            if isinstance(promo_status, str):
                promo_status = promo_status.lower() in {"true", "1", "yes", "y", "t"}
            query["promo_status_bool"] = bool(promo_status)

        cursor = col.find(query).sort([("updated_at", -1)]).skip((page - 1) * per_page).limit(per_page)
        total_count = col.count_documents(query)

        results = []
        for d in cursor:
            category = cls._dec(d["promo_category"])
            if promo_category and category != promo_category:
                continue

            results.append({
                "_id": cls._safe_str(d["_id"]),
                "business_id": cls._safe_str(d["business_id"]),
                "promo_name": cls._dec(d["promo_name"]),
                "promo_amount": cls._dec_float(d["promo_amount"]),
                "promo_category": category,
                "promo_start_date": cls._dec(d["promo_start_date"]),
                "promo_end_date": cls._dec(d["promo_end_date"]),
                "promo_limit": cls._dec_int(d.get("promo_limit")),
                "promo_threshold": cls._dec_int(d["promo_threshold"]),
                "promo_status": cls._dec_bool(d["promo_status"]),
                "promo_total_allowable_limit": cls._dec_int(d.get("promo_total_allowable_limit")),
                "created_at": d.get("created_at"),
                "updated_at": d.get("updated_at"),
            })

        return {
            "promos": results,
            "total_count": len(results),
            "total_pages": 1 if len(results) > 0 else 0,
            "current_page": page,
            "per_page": per_page,
        }

    # -------------------- Active Promo --------------------
    @classmethod
    def get_active_one_by_category(cls, business_id, promo_category):
        try:
            business_oid = ObjectId(business_id)
        except:
            return None

        now = datetime.utcnow()
        col = db.get_collection(cls.collection_name)

        query = {
            "business_id": business_oid,
            "promo_status_bool": True,
            "promo_start_at": {"$lte": now},
            "promo_end_at": {"$gte": now},
        }

        cursor = col.find(query).sort([("updated_at", -1)])
        for d in cursor:
            if cls._dec(d["promo_category"]) == promo_category:
                return {
                    "_id": cls._safe_str(d["_id"]),
                    "business_id": cls._safe_str(d["business_id"]),
                    "promo_name": cls._dec(d["promo_name"]),
                    "promo_amount": cls._dec_float(d["promo_amount"]),
                    "promo_category": promo_category,
                    "promo_start_date": cls._dec(d["promo_start_date"]),
                    "promo_end_date": cls._dec(d["promo_end_date"]),
                    "promo_limit": cls._dec_int(d.get("promo_limit")),
                    "promo_threshold": cls._dec_int(d["promo_threshold"]),
                    "promo_status": cls._dec_bool(d["promo_status"]),
                    "promo_total_allowable_limit": cls._dec_int(d.get("promo_total_allowable_limit")),
                    "created_at": d.get("created_at"),
                    "updated_at": d.get("updated_at"),
                }

        return None


    @staticmethod
    def _upsert_promo_for_subscribers(business_id, promo_id, promo_amount, promo_limit):
        """
        Add/update a promo entry for all users in the same business whose `subscriber_id`
        is a valid BSON ObjectId.

        - Creates the `promos` array if missing via $addToSet
        - Dedupes by promo_id
        - Updates promo_amount (float) and promo_limit (int or None)
        """
        users = db.get_collection("users")

        # business_id: handle either ObjectId or stored-as-string
        try:
            biz_oid = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            business_filters = [
                {"business_id": biz_oid},
                {"business_id": str(biz_oid)},   # if users collection stores business_id as string
            ]
        except Exception:
            # business_id is not an ObjectId; treat as string
            business_filters = [{"business_id": business_id}]

        # only users who have subscriber_id as a real ObjectId
        subs_filter = {"subscriber_id": {"$exists": True, "$type": "objectId"}}

        promo_id_str = str(promo_id)
        promo_amount_val = float(promo_amount)
        promo_limit_val = int(promo_limit) if promo_limit is not None else None

        # 1) Ensure each matched user has `promos` and contains this promo_id (no duplicates)
        for bizf in business_filters:
            seed_filter = {**bizf, **subs_filter, "promos.promo_id": {"$ne": promo_id_str}}
            users.update_many(
                seed_filter,
                {"$addToSet": {"promos": {"promo_id": promo_id_str}}}
            )

        # 2) Update the values on that entry everywhere (array must exist now)
        for bizf in business_filters:
            upd_filter = {**bizf, **subs_filter}
            users.update_many(
                upd_filter,
                {
                    "$set": {
                        "promos.$[p].promo_amount": promo_amount_val,
                        "promos.$[p].promo_limit": promo_limit_val,
                        "promos.$[p].promo_left": promo_limit_val,
                    }
                },
                array_filters=[{"p.promo_id": promo_id_str}],
            )



    # -------------------- Delete --------------------
    @classmethod
    def delete(cls, promo_id, business_id):
        try:
            business_oid = ObjectId(business_id)
        except:
            return False
        return super().delete(promo_id, business_oid)
