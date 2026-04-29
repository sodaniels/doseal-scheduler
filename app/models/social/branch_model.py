# app/models/church/branch_model.py

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from bson import ObjectId

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class Branch(BaseModel):
    """
    Church branch / campus / parish model.
    """

    collection_name = "branches"
    _permission_module = "branches"

    TYPE_MAIN = "Main"
    TYPE_BRANCH = "Branch"
    TYPE_CAMPUS = "Campus"
    TYPE_PARISH = "Parish"
    TYPE_SATELLITE = "Satellite"
    TYPE_ONLINE = "Online"

    BRANCH_TYPES = [TYPE_MAIN, TYPE_BRANCH, TYPE_CAMPUS, TYPE_PARISH, TYPE_SATELLITE, TYPE_ONLINE]

    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_CLOSED = "Closed"
    STATUS_PENDING = "Pending"
    STATUS_ARCHIVED = "Archived"

    STATUSES = [STATUS_ACTIVE, STATUS_INACTIVE, STATUS_CLOSED, STATUS_PENDING, STATUS_ARCHIVED]

    FIELDS_TO_DECRYPT = [
        "name", "description", "code",
        "address_line_1", "address_line_2", "city",
        "state_province", "postal_code", "country",
        "phone", "email",
        "pastor_name", "contact_person_name", "contact_person_phone",
        "branch_type", "status",
    ]

    def __init__(
        self,
        name: str,
        code: Optional[str] = None,
        description: Optional[str] = None,
        branch_type: str = TYPE_BRANCH,
        status: str = STATUS_ACTIVE,
        parent_branch_id: Optional[str] = None,
        region: Optional[str] = None,
        district: Optional[str] = None,
        address_line_1: Optional[str] = None,
        address_line_2: Optional[str] = None,
        city: Optional[str] = None,
        state_province: Optional[str] = None,
        postal_code: Optional[str] = None,
        country: Optional[str] = None,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        timezone: Optional[str] = None,
        phone: Optional[str] = None,
        email: Optional[str] = None,
        pastor_id: Optional[str] = None,
        pastor_name: Optional[str] = None,
        contact_person_name: Optional[str] = None,
        contact_person_phone: Optional[str] = None,
        service_times=None,
        seating_capacity: Optional[int] = None,
        year_established: Optional[int] = None,
        logo_url: Optional[str] = None,
        cover_photo_url: Optional[str] = None,
        currency: Optional[str] = None,
        language: Optional[str] = None,
        display_order: int = 0,
        is_headquarters: bool = False,
        is_archived: bool = False,
        user_id=None,
        user__id=None,
        business_id=None,
        **kwargs,
    ):
        super().__init__(
            user__id=user__id,
            user_id=user_id,
            business_id=business_id,
            **kwargs,
        )

        self.business_id = ObjectId(business_id) if business_id else None

        if name:
            self.name = encrypt_data(name)
            self.hashed_name = hash_data(name.strip().lower())

        if code:
            self.code = encrypt_data(code)
            self.hashed_code = hash_data(code.strip().upper())

        if description:
            self.description = encrypt_data(description)

        if branch_type:
            self.branch_type = encrypt_data(branch_type)
            self.hashed_branch_type = hash_data(branch_type.strip())

        if status:
            self.status = encrypt_data(status)
            self.hashed_status = hash_data(status.strip())

        if parent_branch_id:
            self.parent_branch_id = ObjectId(parent_branch_id)
        if region:
            self.region = region.strip()
        if district:
            self.district = district.strip()

        if address_line_1:
            self.address_line_1 = encrypt_data(address_line_1)
        if address_line_2:
            self.address_line_2 = encrypt_data(address_line_2)
        if city:
            self.city = encrypt_data(city)
            self.hashed_city = hash_data(city.strip().lower())
        if state_province:
            self.state_province = encrypt_data(state_province)
        if postal_code:
            self.postal_code = encrypt_data(postal_code)
        if country:
            self.country = encrypt_data(country)
            self.hashed_country = hash_data(country.strip().lower())

        if latitude is not None and longitude is not None:
            self.location = {
                "type": "Point",
                "coordinates": [float(longitude), float(latitude)],
            }
        if timezone:
            self.timezone = timezone.strip()

        if phone:
            self.phone = encrypt_data(phone)
            self.hashed_phone = hash_data(phone.strip())
        if email:
            self.email = encrypt_data(email)
            self.hashed_email = hash_data(email.strip().lower())

        if pastor_id:
            self.pastor_id = ObjectId(pastor_id)
        if pastor_name:
            self.pastor_name = encrypt_data(pastor_name)
        if contact_person_name:
            self.contact_person_name = encrypt_data(contact_person_name)
        if contact_person_phone:
            self.contact_person_phone = encrypt_data(contact_person_phone)

        if service_times:
            self.service_times = service_times

        if seating_capacity is not None:
            self.seating_capacity = int(seating_capacity)
        if year_established is not None:
            self.year_established = int(year_established)
        if logo_url:
            self.logo_url = logo_url
        if cover_photo_url:
            self.cover_photo_url = cover_photo_url

        if currency:
            self.currency = currency.strip()
        if language:
            self.language = language.strip()

        self.display_order = int(display_order)
        self.is_headquarters = bool(is_headquarters)
        self.is_archived = bool(is_archived)

        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "business_id": self.business_id,
            "name": getattr(self, "name", None),
            "hashed_name": getattr(self, "hashed_name", None),
            "code": getattr(self, "code", None),
            "hashed_code": getattr(self, "hashed_code", None),
            "description": getattr(self, "description", None),
            "branch_type": getattr(self, "branch_type", None),
            "hashed_branch_type": getattr(self, "hashed_branch_type", None),
            "status": getattr(self, "status", None),
            "hashed_status": getattr(self, "hashed_status", None),
            "parent_branch_id": getattr(self, "parent_branch_id", None),
            "region": getattr(self, "region", None),
            "district": getattr(self, "district", None),
            "address_line_1": getattr(self, "address_line_1", None),
            "address_line_2": getattr(self, "address_line_2", None),
            "city": getattr(self, "city", None),
            "hashed_city": getattr(self, "hashed_city", None),
            "state_province": getattr(self, "state_province", None),
            "postal_code": getattr(self, "postal_code", None),
            "country": getattr(self, "country", None),
            "hashed_country": getattr(self, "hashed_country", None),
            "location": getattr(self, "location", None),
            "timezone": getattr(self, "timezone", None),
            "phone": getattr(self, "phone", None),
            "hashed_phone": getattr(self, "hashed_phone", None),
            "email": getattr(self, "email", None),
            "hashed_email": getattr(self, "hashed_email", None),
            "pastor_id": getattr(self, "pastor_id", None),
            "pastor_name": getattr(self, "pastor_name", None),
            "contact_person_name": getattr(self, "contact_person_name", None),
            "contact_person_phone": getattr(self, "contact_person_phone", None),
            "service_times": getattr(self, "service_times", None),
            "seating_capacity": getattr(self, "seating_capacity", None),
            "year_established": getattr(self, "year_established", None),
            "logo_url": getattr(self, "logo_url", None),
            "cover_photo_url": getattr(self, "cover_photo_url", None),
            "currency": getattr(self, "currency", None),
            "language": getattr(self, "language", None),
            "display_order": getattr(self, "display_order", None),
            "is_headquarters": getattr(self, "is_headquarters", None),
            "is_archived": getattr(self, "is_archived", None),
            "created_at": getattr(self, "created_at", None),
            "updated_at": getattr(self, "updated_at", None),
        }
        return {k: v for k, v in doc.items() if v is not None}

    @staticmethod
    def _safe_decrypt(value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str):
            return value
        try:
            return decrypt_data(value)
        except Exception:
            return value

    @classmethod
    def _normalise_branch_doc(cls, doc: dict) -> Optional[dict]:
        if not doc:
            return None

        for oid_field in ["_id", "business_id", "parent_branch_id", "pastor_id"]:
            if doc.get(oid_field) is not None:
                doc[oid_field] = str(doc[oid_field])

        for field in cls.FIELDS_TO_DECRYPT:
            if field in doc:
                doc[field] = cls._safe_decrypt(doc[field])

        location = doc.get("location")
        if location and isinstance(location, dict):
            coords = location.get("coordinates", [])
            if len(coords) == 2:
                doc["longitude"] = coords[0]
                doc["latitude"] = coords[1]
            doc.pop("location", None)

        for h in [
            "hashed_name", "hashed_code", "hashed_branch_type",
            "hashed_status", "hashed_city", "hashed_country",
            "hashed_phone", "hashed_email",
        ]:
            doc.pop(h, None)

        return doc

    @classmethod
    def get_by_id(cls, branch_id, business_id=None, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_by_id][{branch_id}]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            branch_id = ObjectId(branch_id) if not isinstance(branch_id, ObjectId) else branch_id
            collection = db.get_collection(cls.collection_name)

            query = {"_id": branch_id}
            if business_id:
                query["business_id"] = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            branch = collection.find_one(query)
            if not branch:
                Log.info(f"{log_tag} Branch not found")
                return None
            return cls._normalise_branch_doc(branch)
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_all_by_business(cls, business_id, page=1, per_page=50, include_archived=False, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_all_by_business]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50

            collection = db.get_collection(cls.collection_name)
            query = {
                "business_id": ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id,
            }
            if not include_archived:
                query["is_archived"] = {"$ne": True}

            total_count = collection.count_documents(query)
            cursor = (
                collection.find(query)
                .sort("display_order", 1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            branches = [cls._normalise_branch_doc(b) for b in items]
            total_pages = (total_count + per_page - 1) // per_page

            return {
                "branches": branches,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "branches": [], "total_count": 0,
                "total_pages": 0, "current_page": page, "per_page": per_page,
            }

    @classmethod
    def get_by_status(cls, business_id, status, page=1, per_page=50, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_by_status][{status}]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50

            collection = db.get_collection(cls.collection_name)
            query = {
                "business_id": ObjectId(business_id),
                "hashed_status": hash_data(status.strip()),
            }

            total_count = collection.count_documents(query)
            cursor = (
                collection.find(query)
                .sort("display_order", 1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            branches = [cls._normalise_branch_doc(b) for b in items]
            total_pages = (total_count + per_page - 1) // per_page

            return {
                "branches": branches,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {"branches": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def get_by_type(cls, business_id, branch_type, page=1, per_page=50, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_by_type][{branch_type}]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50

            collection = db.get_collection(cls.collection_name)
            query = {
                "business_id": ObjectId(business_id),
                "hashed_branch_type": hash_data(branch_type.strip()),
                "is_archived": {"$ne": True},
            }

            total_count = collection.count_documents(query)
            cursor = (
                collection.find(query)
                .sort("display_order", 1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            branches = [cls._normalise_branch_doc(b) for b in items]
            total_pages = (total_count + per_page - 1) // per_page

            return {
                "branches": branches,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {"branches": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def get_children(cls, business_id, parent_branch_id, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_children][{parent_branch_id}]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            collection = db.get_collection(cls.collection_name)
            query = {
                "business_id": ObjectId(business_id),
                "parent_branch_id": ObjectId(parent_branch_id),
                "is_archived": {"$ne": True},
            }
            cursor = collection.find(query).sort("display_order", 1)
            items = list(cursor)
            return [cls._normalise_branch_doc(b) for b in items]
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []

    @classmethod
    def get_by_region(cls, business_id, region, page=1, per_page=50, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_by_region][{region}]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50

            collection = db.get_collection(cls.collection_name)
            query = {
                "business_id": ObjectId(business_id),
                "region": region.strip(),
                "is_archived": {"$ne": True},
            }

            total_count = collection.count_documents(query)
            cursor = (
                collection.find(query)
                .sort("display_order", 1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            branches = [cls._normalise_branch_doc(b) for b in items]
            total_pages = (total_count + per_page - 1) // per_page

            return {
                "branches": branches,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {"branches": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def get_by_district(cls, business_id, district, page=1, per_page=50, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_by_district][{district}]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50

            collection = db.get_collection(cls.collection_name)
            query = {
                "business_id": ObjectId(business_id),
                "district": district.strip(),
                "is_archived": {"$ne": True},
            }

            total_count = collection.count_documents(query)
            cursor = (
                collection.find(query)
                .sort("display_order", 1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            branches = [cls._normalise_branch_doc(b) for b in items]
            total_pages = (total_count + per_page - 1) // per_page

            return {
                "branches": branches,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {"branches": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def get_headquarters(cls, business_id, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_headquarters]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            collection = db.get_collection(cls.collection_name)
            query = {
                "business_id": ObjectId(business_id),
                "is_headquarters": True,
                "is_archived": {"$ne": True},
            }
            branch = collection.find_one(query)
            return cls._normalise_branch_doc(branch) if branch else None
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def search(cls, business_id, search_term, page=1, per_page=50, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][search]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50

            collection = db.get_collection(cls.collection_name)
            hashed_lower = hash_data(search_term.strip().lower())
            hashed_upper = hash_data(search_term.strip().upper())

            query = {
                "business_id": ObjectId(business_id),
                "is_archived": {"$ne": True},
                "$or": [
                    {"hashed_name": hashed_lower},
                    {"hashed_code": hashed_upper},
                    {"hashed_city": hashed_lower},
                ],
            }

            total_count = collection.count_documents(query)
            cursor = (
                collection.find(query)
                .sort("display_order", 1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            branches = [cls._normalise_branch_doc(b) for b in items]
            total_pages = (total_count + per_page - 1) // per_page

            return {
                "branches": branches,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {"branches": [], "total_count": 0, "total_pages": 0, "current_page": page, "per_page": per_page}

    @classmethod
    def get_member_count(cls, branch_id, business_id, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_member_count][{branch_id}]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            members_collection = db.get_collection("members")
            count = members_collection.count_documents({
                "business_id": ObjectId(business_id),
                "branch_id": ObjectId(branch_id),
                "is_archived": {"$ne": True},
            })
            return count
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return 0

    @classmethod
    def get_summary(cls, business_id, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][get_summary]"
        cls._enforce_permission("read", skip=processing_callback)
        try:
            collection = db.get_collection(cls.collection_name)
            biz_oid = ObjectId(business_id)

            total = collection.count_documents({"business_id": biz_oid, "is_archived": {"$ne": True}})
            active = collection.count_documents({
                "business_id": biz_oid,
                "hashed_status": hash_data(cls.STATUS_ACTIVE),
                "is_archived": {"$ne": True},
            })
            inactive = collection.count_documents({
                "business_id": biz_oid,
                "hashed_status": hash_data(cls.STATUS_INACTIVE),
                "is_archived": {"$ne": True},
            })

            type_counts = {}
            for bt in cls.BRANCH_TYPES:
                c = collection.count_documents({
                    "business_id": biz_oid,
                    "hashed_branch_type": hash_data(bt.strip()),
                    "is_archived": {"$ne": True},
                })
                if c > 0:
                    type_counts[bt] = c

            regions = collection.distinct("region", {"business_id": biz_oid, "is_archived": {"$ne": True}})
            districts = collection.distinct("district", {"business_id": biz_oid, "is_archived": {"$ne": True}})

            regions = [r for r in regions if r]
            districts = [d for d in districts if d]

            return {
                "total_branches": total,
                "active": active,
                "inactive": inactive,
                "by_type": type_counts,
                "regions": regions,
                "region_count": len(regions),
                "districts": districts,
                "district_count": len(districts),
            }
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "total_branches": 0, "active": 0, "inactive": 0,
                "by_type": {}, "regions": [], "region_count": 0,
                "districts": [], "district_count": 0,
            }

    @classmethod
    def archive(cls, branch_id, business_id, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][archive][{branch_id}]"
        cls._enforce_permission("delete", skip=processing_callback)
        try:
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": ObjectId(branch_id), "business_id": ObjectId(business_id)},
                {
                    "$set": {
                        "is_archived": True,
                        "hashed_status": hash_data(cls.STATUS_ARCHIVED),
                        "status": encrypt_data(cls.STATUS_ARCHIVED),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            return result.modified_count > 0
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False

    @classmethod
    def restore(cls, branch_id, business_id, processing_callback=False):
        log_tag = f"[branch_model.py][Branch][restore][{branch_id}]"
        cls._enforce_permission("update", skip=processing_callback)
        try:
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": ObjectId(branch_id), "business_id": ObjectId(business_id)},
                {
                    "$set": {
                        "is_archived": False,
                        "hashed_status": hash_data(cls.STATUS_ACTIVE),
                        "status": encrypt_data(cls.STATUS_ACTIVE),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            return result.modified_count > 0
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False

    @classmethod
    def update(cls, branch_id, business_id, processing_callback=False, **updates):
        cls._enforce_permission("update", skip=processing_callback)
        updates = dict(updates or {})
        updates["updated_at"] = datetime.utcnow()
        updates = {k: v for k, v in updates.items() if v is not None}

        encrypt_hash_pairs = {
            "name": ("hashed_name", True),
            "code": ("hashed_code", False),
            "branch_type": ("hashed_branch_type", False),
            "status": ("hashed_status", False),
            "email": ("hashed_email", True),
            "phone": ("hashed_phone", False),
        }

        for field, (hash_field, do_lower) in encrypt_hash_pairs.items():
            if field in updates and updates[field]:
                plain = updates[field]
                updates[field] = encrypt_data(plain)
                if field == "code":
                    updates[hash_field] = hash_data(plain.strip().upper())
                elif do_lower:
                    updates[hash_field] = hash_data(plain.strip().lower())
                else:
                    updates[hash_field] = hash_data(plain.strip())

        for geo_field, hash_key in [("city", "hashed_city"), ("country", "hashed_country")]:
            if geo_field in updates and updates[geo_field]:
                plain_val = updates[geo_field]
                updates[hash_key] = hash_data(plain_val.strip().lower())
                updates[geo_field] = encrypt_data(plain_val)

        encrypt_only = [
            "description", "address_line_1", "address_line_2",
            "state_province", "postal_code",
            "pastor_name", "contact_person_name", "contact_person_phone",
        ]
        for field in encrypt_only:
            if field in updates and updates[field]:
                updates[field] = encrypt_data(updates[field])

        for oid_field in ["parent_branch_id", "pastor_id"]:
            if oid_field in updates and updates[oid_field]:
                updates[oid_field] = ObjectId(updates[oid_field])

        lat = updates.pop("latitude", None)
        lng = updates.pop("longitude", None)
        if lat is not None and lng is not None:
            updates["location"] = {
                "type": "Point",
                "coordinates": [float(lng), float(lat)],
            }

        updates = {k: v for k, v in updates.items() if v is not None}
        return super().update(branch_id, business_id, **updates)

    @classmethod
    def create_indexes(cls):
        log_tag = f"[branch_model.py][Branch][create_indexes]"
        try:
            collection = db.get_collection(cls.collection_name)

            collection.create_index([("business_id", 1), ("hashed_status", 1), ("display_order", 1)])
            collection.create_index([("business_id", 1), ("hashed_branch_type", 1)])
            collection.create_index([("business_id", 1), ("hashed_name", 1)])
            collection.create_index([("business_id", 1), ("hashed_code", 1)])
            collection.create_index([("business_id", 1), ("parent_branch_id", 1)])
            collection.create_index([("business_id", 1), ("region", 1)])
            collection.create_index([("business_id", 1), ("district", 1)])
            collection.create_index([("business_id", 1), ("is_headquarters", 1)])
            collection.create_index([("business_id", 1), ("is_archived", 1)])
            collection.create_index([("business_id", 1), ("hashed_city", 1)])
            collection.create_index([("business_id", 1), ("hashed_country", 1)])

            Log.info(f"{log_tag} Indexes created successfully")
            return True
        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False