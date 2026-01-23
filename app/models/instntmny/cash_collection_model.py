from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from bson.objectid import ObjectId
from decimal import Decimal
import os, re, json

from app.extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ..base_model import BaseModel


class CashCollections(BaseModel):
    """
    CashCollections represents cash collection events carried out by agents.

    Fields:
      - agent (ObjectId, required)
      - admin (ObjectId, optional)
      - amount (float, required) [encrypted at rest]
      - signature (str, required) [encrypted at rest]
      - location (str|dict, required) [encrypted at rest as JSON string if dict]
      - images (list[str], optional) [each element encrypted at rest]
      - image_paths (list[str], optional) [NOT encrypted; storage keys/paths]
      - status (list[dict] with keys among: initiated, confirmed, approved)
      - business_id (ObjectId, required)
      - created_by (ObjectId, required)
      - created_at, updated_at
    """
    collection_name = "cash_collections"

    def __init__(
        self,
        *,
        agent: str,
        amount: float,
        signature: str,
        location,  # str or dict; will be normalized
        business_id: str,
        created_by: str,
        admin: str | None = None,
        barcode: str | None = None,
        date: str | None = None,
        message: str | None = None,
        remark: str | None = None,
        images: list[str] | str | None = None,   
        image_paths: list[str] | None = None, 
        status: dict | list | None = None,
        user_id: str | None = None,
        user__id: str | None = None,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
    ):
        super().__init__(business_id=business_id, user_id=user_id, user__id=user__id)

        # --- IDs ---
        self.agent = ObjectId(agent) if isinstance(agent, str) else agent
        self.admin = ObjectId(admin) if admin and isinstance(admin, str) else admin
        self.business_id = ObjectId(business_id) if isinstance(business_id, str) else business_id
        self.created_by = ObjectId(created_by) if isinstance(created_by, str) else created_by

        # --- Core fields (encrypted) ---
        self.amount = encrypt_data(str(float(amount))) 
        self.signature = encrypt_data(signature)
        self.message = encrypt_data(message) if message else None
        self.remark = encrypt_data(remark) if remark else None
        self.barcode = encrypt_data(barcode) if barcode else None
        self.date = encrypt_data(date) if date else None
        
        # hashed fields
        self.hashed_amount = hash_data(str(float(amount))) if amount else None
        self.hashed_date = hash_data(date) if date else None
        self.hashed_signature = hash_data(signature) if signature else None

        # location can be dict or str; store as encrypted string
        _loc_str = json.dumps(location) if isinstance(location, (dict, list)) else str(location)
        self.location = encrypt_data(_loc_str)

        # images: encrypt each element individually
        if images is None:
            self.images = None
        else:
            if isinstance(images, str):
                # Single URL as string
                self.images = [encrypt_data(images)]
            elif isinstance(images, list):
                self.images = [encrypt_data(img) for img in images if img is not None]
            else:
                # Unexpected type; coerce to string and encrypt
                self.images = [encrypt_data(str(images))]

        # image_paths: keep as-is (NOT encrypted)
        if image_paths is None:
            self.image_paths = None
        else:
            # Ensure list of strings
            if isinstance(image_paths, list):
                self.image_paths = [str(p) for p in image_paths if p is not None]
            else:
                self.image_paths = [str(image_paths)]

        # --- Status ---
        self.status = status

        # --- Dates ---
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    # -------- Serialization --------
    def to_dict(self):
        doc = super().to_dict()
        doc.update({
            "agent": self.agent,
            "admin": self.admin,
            "amount": self.amount,
            "signature": self.signature,
            "location": self.location,
            "message": self.message,
            "remark": self.remark,
            "barcode": self.barcode,
            "images": self.images,
            "image_paths": self.image_paths,
            "status": self.status,
            "business_id": self.business_id,
            "created_by": self.created_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return doc

    def _coerce_amount(raw):
        """Return amount as float from raw (numeric, encrypted str, or plain str)."""
        if raw is None:
            return 0.0
        # already numeric
        if isinstance(raw, (int, float, Decimal)):
            try:
                return float(raw)
            except Exception:
                return 0.0
        # string-like
        if isinstance(raw, str):
            # try decrypt first
            try:
                dec = decrypt_data(raw)
                if isinstance(dec, (bytes, bytearray)):
                    dec = dec.decode("utf-8", errors="ignore")
                return float(str(dec).strip())
            except Exception:
                # maybe it was stored as plain string number
                try:
                    return float(raw.strip())
                except Exception:
                    return 0.0
        # anything else
        return 0.0


    # -------- Helpers --------
    @classmethod
    def _post_process(cls, data: dict) -> dict:
        """Convert ObjectIds to str, decrypt sensitive fields, normalize shapes."""
        if not data:
            return data

        # IDs to string
        data["_id"] = str(data["_id"])
        for key in ("business_id", "agent", "admin", "created_by"):
            if data.get(key):
                data[key] = str(data[key])

        # Decrypt amount
        if data.get("amount") is not None:
            try:
                data["amount"] = float(decrypt_data(data["amount"]))
            except Exception:
                pass

        # Decrypt signature
        if data.get("signature"):
            try:
                data["signature"] = decrypt_data(data["signature"])
            except Exception:
                pass
            
        if data.get("message"):
            try:
                data["message"] = decrypt_data(data["message"])
            except Exception:
                pass
            
        if data.get("remark"):
            try:
                data["remark"] = decrypt_data(data["remark"])
            except Exception:
                pass

        # Decrypt location; try to load JSON if applicable
        if data.get("location"):
            try:
                loc_str = decrypt_data(data["location"])
                try:
                    data["location"] = json.loads(loc_str)
                except Exception:
                    data["location"] = loc_str
            except Exception:
                pass
            
        if data.get("bardcode"):
            try:
                bar_str = decrypt_data(data["bardcode"])
                try:
                    data["bardcode"] = json.loads(bar_str)
                except Exception:
                    data["bardcode"] = bar_str
            except Exception:
                pass


        # Decrypt images: supports list-of-encrypted or legacy single encrypted string
        if data.get("images"):
            try:
                if isinstance(data["images"], list):
                    decrypted_list = []
                    for enc in data["images"]:
                        try:
                            decrypted_list.append(decrypt_data(enc))
                        except Exception:
                            # if one image fails, skip it (or append raw enc)
                            continue
                    data["images"] = decrypted_list
                elif isinstance(data["images"], str):
                    # legacy: single encrypted string
                    try:
                        data["images"] = [decrypt_data(data["images"])]
                    except Exception:
                        data["images"] = [data["images"]]
            except Exception:
                pass

        # image_paths: leave as-is (not encrypted); normalize to list
        if data.get("image_paths") and not isinstance(data["image_paths"], list):
            data["image_paths"] = [str(data["image_paths"])]

        # Drop internal
        data.pop("user__id", None)
        return data

    # -------- CRUD --------
    @classmethod
    def create(
        cls,
        *,
        agent: str,
        amount: float,
        signature: str,
        location,
        business_id: str,
        created_by: str,
        barcode: str | None = None,
        message: str | None = None,
        date: str | None = None,
        admin: str | None = None,
        images: list[str] | str | None = None,
        image_paths: list[str] | None = None,
        status: dict | list | None = None,
        user_id: str | None = None,
        user__id: str | None = None,
    ):
        entry = cls(
            agent=agent,
            amount=amount,
            signature=signature,
            message=message,
            location=location,
            date=date,
            barcode=barcode,
            business_id=business_id,
            created_by=created_by,
            admin=admin,
            images=images,
            image_paths=image_paths,
            status=status,
            user_id=user_id,
            user__id=user__id,
        )

        if not cls.check_permission(cls, "create", "collections"):
            raise PermissionError("User does not have permission to create collections.")

        return entry.save()

    @classmethod
    def check_item_exists(cls, business_id, key, value):
        """
        Check if a beneficiary exists based on a specific key (e.g., phone, user_id) and value.
        This method allows dynamic checks for any key (like 'phone', 'user_id', etc.) using hashed values.
        
        :param business_id: The ID of the business.
        :param key: The field to check (e.g., "phone", "user_id").
        :param value: The value to check for the given key.
        :return: True if the beneficiary exists, False otherwise.
        """
        try:
            # Check if the user has permission to 'add' before proceeding
            if not cls.check_permission(cls, 'read', 'collections'):
                raise PermissionError(f"User does not have permission to read {cls.__name__}.")

            # Ensure that business_id is in the correct ObjectId format if it's passed as a string
            try:
                business_id_obj = ObjectId(business_id)  # Convert string business_id to ObjectId
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e
                

            # Dynamically hash the value of the key
            hashed_key = hash_data(value)  # Assuming hash_data is a method to hash the value
            
            # Dynamically create the query with business_id and hashed key
            query = {
                "business_id": business_id_obj,  # Ensure query filters by business_id
                f"hashed_{key}": hashed_key  # Use dynamic key for hashed comparison (e.g., "hashed_phone")
            }

            # Query the database for an item matching the given business_id and hashed value
            collection = db.get_collection(cls.collection_name)
            existing_item = collection.find_one(query)

            # Return True if a matching item is found, else return False
            if existing_item:
                return True  # Item exists
            else:
                return False  # Item does not exist

        except Exception as e:
            # Handle errors and return False in case of an exception
            print(f"Error occurred: {e}")  # For debugging purposes
            return False
    
    @classmethod
    def get_all(
        cls,
        business_id: str,
        page: int | None = 1,
        per_page: int | None = 10,
        *,
        agent: str | None = None,
        extra_filter: dict | None = None,
        confirmed: str | bool | None = None,
        sort: list[tuple[str, int]] | None = None,
        created_by: str | None = None,   # <-- NEW: admin ObjectId string
    ):
        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", "1"))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", "10"))

        try:
            bid = ObjectId(business_id)
        except Exception:
            return None

        if not cls.check_permission(cls, "read", "collections"):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")

        page = int(page) if page else default_page
        per_page = int(per_page) if per_page else default_per_page

        col = db.get_collection(cls.collection_name)
        query = {"business_id": bid}

        if agent:
            try:
                query["agent"] = ObjectId(agent)
            except Exception:
                return {
                    "cash_collections": [],
                    "total_count": 0,
                    "total_pages": 0,
                    "current_page": page,
                    "per_page": per_page,
                    "today_total_pickups_for_admin": 0,
                }

        # Normalize confirmed
        if isinstance(confirmed, str):
            lc = confirmed.strip().lower()
            if lc in {"true", "1", "yes", "on"}:
                confirmed = True
            elif lc in {"false", "0", "no", "off"}:
                confirmed = False
            else:
                confirmed = None

        if confirmed is True:
            query["status.confirmed.status"] = True
        elif confirmed is False:
            query["status.confirmed.status"] = False

        if extra_filter:
            query.update(extra_filter)

        # ---- Main list query (paginated) ----
        cursor = col.find(query)
        cursor = cursor.sort(sort) if sort else cursor.sort([("created_at", -1)])

        total_count = col.count_documents(query)
        cursor = cursor.skip((page - 1) * per_page).limit(per_page)

        results = []
        fields_to_strip = ("hashed_amount", "hashed_date", "hashed_signature", "date")

        for doc in cursor:
            processed = cls._post_process(doc)
            for k in fields_to_strip:
                processed.pop(k, None)
            results.append(processed)

        total_pages = (total_count + per_page - 1) // per_page

        # ---- Today's pickups count for a particular admin (created_by) ----
        today_total_pickups_for_admin = 0
        if created_by:
            try:
                created_by_oid = ObjectId(created_by)

                # London "today" boundaries converted to UTC for querying created_at
                now_ldn = datetime.now(ZoneInfo("Europe/London"))
                start_ldn = datetime(now_ldn.year, now_ldn.month, now_ldn.day, tzinfo=ZoneInfo("Europe/London"))
                end_ldn = start_ldn + timedelta(days=1)

                start_utc = start_ldn.astimezone(timezone.utc)
                end_utc = end_ldn.astimezone(timezone.utc)

                today_query = {
                    **query,  # inherit all filters already applied (business, agent, confirmed, extra_filter)
                    "created_by": created_by_oid,
                    "created_at": {"$gte": start_utc, "$lt": end_utc},
                }

                today_total_pickups_for_admin = col.count_documents(today_query)
            except Exception:
                # If created_by is invalid or any error occurs, keep the count as 0
                today_total_pickups_for_admin = 0

        return {
            "cash_collections": results,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
            "today_total_pickups_for_admin": today_total_pickups_for_admin,  # <-- NEW
        }
    
    @classmethod
    def get_all_by_created_by(
        cls,
        business_id: str,
        page: int | None = 1,
        per_page: int | None = 10,
        *,
        confirmed: str | bool | None = None,
        created_by: str | None = None,
    ):
        default_page = int(os.getenv("DEFAULT_PAGINATION_PAGE", "1"))
        default_per_page = int(os.getenv("DEFAULT_PAGINATION_PER_PAGE", "10"))

        try:
            bid = ObjectId(business_id)
        except Exception:
            return None

        if not cls.check_permission(cls, "read", "collections"):
            raise PermissionError(f"User does not have permission to view {cls.__name__}.")

        page = int(page) if page else default_page
        per_page = int(per_page) if per_page else default_per_page

        col = db.get_collection(cls.collection_name)

        # Europe/London "today"
        now_ldn = datetime.now(ZoneInfo("Europe/London"))
        start_ldn = datetime(now_ldn.year, now_ldn.month, now_ldn.day, tzinfo=ZoneInfo("Europe/London"))
        end_ldn = start_ldn + timedelta(days=1)
        start_utc = start_ldn.astimezone(timezone.utc)
        end_utc = end_ldn.astimezone(timezone.utc)

        # RFC-1123 prefix like "Mon, 06 Oct 2025"
        rfc1123_prefix = start_ldn.strftime("%a, %d %b %Y")
        rfc1123_regex = f"^{re.escape(rfc1123_prefix)}\\b"

        # Build filters
        filters = [{"business_id": bid}]
        if created_by:
            try:
                filters.append({"created_by": ObjectId(created_by)})
            except Exception:
                return {
                    "cash_collections": [],
                    "total_count": 0,
                    "total_pages": 0,
                    "current_page": page,
                    "per_page": per_page,
                    "today_total_pickups_for_admin": 0,
                    "today_total_amount": 0.0,
                }

        # normalize confirmed
        if isinstance(confirmed, str):
            lc = confirmed.strip().lower()
            if lc in {"true", "1", "yes", "on"}:
                confirmed = True
            elif lc in {"false", "0", "no", "off"}:
                confirmed = False
            else:
                confirmed = None

        if confirmed is True:
            filters.append({"status": {"$elemMatch": {"confirmed.status": True}}})
        elif confirmed is False:
            filters.append({"status": {"$elemMatch": {"confirmed.status": False}}})

        # Date filter: BSON Date OR RFC-1123 string
        filters.append({
            "$or": [
                {"created_at": {"$gte": start_utc, "$lt": end_utc}},
                {"created_at": {"$regex": rfc1123_regex}},
            ]
        })

        query = {"$and": filters}

        # Projection for list (exclude hashed/sensitive fields)
        projection = {
            "hashed_amount": 0,
            "hashed_date": 0,
            "hashed_signature": 0,
            "date": 0,
        }

        # ---- Main list (paginated) ----
        cursor = col.find(query, projection).sort([("created_at", -1)])
        total_count = col.count_documents(query)
        cursor = cursor.skip((page - 1) * per_page).limit(per_page)

        results = []
        for doc in cursor:
            processed = cls._post_process(doc)
            # Decrypt/normalize amount for response item
            processed["amount"] = cls._coerce_amount(processed.get("amount"))
            results.append(processed)

        total_pages = (total_count + per_page - 1) // per_page

        # ---- Sum today's total amount across ALL matches (not just page) ----
        # Use a light projection to only fetch what we need
        sum_cursor = col.find(query, {"amount": 1})
        today_total_amount = 0.0
        for d in sum_cursor:
            today_total_amount +=  cls._coerce_amount(d.get("amount"))

        return {
            "cash_collections": results,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page,
            "today_total_pickups_for_admin": total_count,
            "today_total_amount": today_total_amount,
        }
    
    @classmethod
    def get_by_id(cls, collection_id: str, business_id: str):
        try:
            _id = ObjectId(collection_id)
        except Exception:
            return None

        try:
            bid = ObjectId(business_id)
        except Exception:
            return None

        if not cls.check_permission(cls, "read", "collections"):
            raise PermissionError("User does not have permission to view collections.")

        col = db.get_collection(cls.collection_name)
        data = col.find_one({"_id": _id, "business_id": bid})
        return cls._post_process(data) if data else None

    @staticmethod
    def get_by_business_id_and_bardcode(barcode: str):

        col = db.get_collection("cash_collections")
        data = col.find_one({
            "barcode_hased": barcode
        })
        return True if data else None

    @classmethod
    def get_by_id_and_bardcode(cls, collection_id: str, business_id: str, barcode: str):
        try:
            _id = ObjectId(collection_id)
        except Exception:
            return None

        try:
            bid = ObjectId(business_id)
        except Exception:
            return None
        
        barcode_hased = hash_data(barcode)

        if not cls.check_permission(cls, "read", "collections"):
            raise PermissionError("User does not have permission to view collections.")

        col = db.get_collection(cls.collection_name)
        data = col.find_one({
            "_id": _id, 
            "business_id": bid, 
            "barcode_hased": barcode_hased
        })
        return cls._post_process(data) if data else None


    
    @classmethod
    def update(cls, collection_id: str, **updates):
        """Update fields with re-encryption for sensitive ones."""
        if not cls.check_permission(cls, "create", "collections"):
            raise PermissionError(f"User does not have permission to update {cls.__name__}.")

        if "amount" in updates and updates["amount"] is not None:
            updates["amount"] = encrypt_data(str(float(updates["amount"])))

        if "signature" in updates and updates["signature"] is not None:
            updates["signature"] = encrypt_data(updates["signature"])
            
        if "message" in updates and updates["message"] is not None:
            updates["message"] = encrypt_data(updates["message"])
        
        if "remark" in updates and updates["remark"] is not None:
            updates["remark"] = encrypt_data(updates["remark"])

        if "location" in updates and updates["location"] is not None:
            _loc_str = json.dumps(updates["location"]) if isinstance(updates["location"], (dict, list)) else str(updates["location"])
            updates["location"] = encrypt_data(_loc_str)
            
        if "barcode" in updates and updates["barcode"] is not None:
            barcode = updates["barcode"]
            updates["barcode"] = encrypt_data(updates["barcode"])
            updates["barcode_hashed"] = hash_data(barcode)
            updates["hashed_barcode"] = hash_data(barcode)

        # images: encrypt each element (supports list or single string)
        if "images" in updates and updates["images"] is not None:
            imgs = updates["images"]
            if isinstance(imgs, str):
                updates["images"] = [encrypt_data(imgs)]
            elif isinstance(imgs, list):
                updates["images"] = [encrypt_data(i) for i in imgs if i is not None]
            else:
                updates["images"] = [encrypt_data(str(imgs))]

        # image_paths: store as list of strings, not encrypted
        if "image_paths" in updates and updates["image_paths"] is not None:
            paths = updates["image_paths"]
            if isinstance(paths, list):
                updates["image_paths"] = [str(p) for p in paths if p is not None]
            else:
                updates["image_paths"] = [str(paths)]

        # Cast IDs if passed
        for k in ("agent", "admin", "business_id", "created_by"):
            if k in updates and updates[k] and isinstance(updates[k], str):
                try:
                    updates[k] = ObjectId(updates[k])
                except Exception:
                    pass

        updates["updated_at"] = datetime.now()
        return super().update(collection_id, **updates)

    @classmethod
    def update_status_by_collection_id(cls, collection_id, user_id, field, update_value, client_ip):
        """Update a specific field in the 'status' for the given collection ID."""
        cash_collections = db.get_collection("cash_collections")

        if field == 'confirm':
            if not cls.check_permission(cls, "confirm", "collections"):
                raise PermissionError("User does not have permission to confirm.")

        if field == 'approve':
            if not cls.check_permission(cls, "approve", "collections"):
                raise PermissionError("User does not have permission to approve.")

        # Fetch collection
        collection = cash_collections.find_one({"_id": ObjectId(collection_id)})
        if not collection:
            return {"success": False, "message": "Collection not found"}

        account_status = collection.get("status", None)
        if account_status is None:
            return {"success": False, "message": "Status not found"}

        field_updated = False
        for st in account_status:
            if field in st:
                st[field]["status"] = update_value
                st[field]["created_at"] = datetime.utcnow().isoformat()
                st[field]["ip_address"] = client_ip
                if field == 'confirmed':
                    st[field]["collector_id"] = str(user_id)
                if field == 'approved':
                    st[field]["admin_id"] = str(user_id)
                field_updated = True
                break

        if not field_updated:
            return {"success": False, "message": f"Field '{field}' not found in account status"}

        result = cash_collections.update_one(
            {"_id": ObjectId(collection_id)},
            {"$set": {"status": account_status}}
        )

        if result.matched_count > 0:
            return {"success": True, "message": "Account status updated successfully"}
        else:
            return {"success": False, "message": "Failed to update account status"}

    @classmethod
    def delete(cls, collection_id: str, business_id: str):
        return super().delete(collection_id, business_id)
