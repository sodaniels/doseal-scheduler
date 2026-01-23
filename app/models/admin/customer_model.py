import uuid
import bcrypt


from bson.objectid import ObjectId
from datetime import datetime
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ..base_model import BaseModel

# Customer
class Customer(BaseModel):
    """
    A Customer represents a customer in the business.
    """

    collection_name = "customers"

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        first_name,
        last_name,
        phone,
        email=None,
        address=None,
        image=None,
        file_path=None,
        city=None,
        town=None,
        postal_code=None,
        status="Active",
    ):
        super().__init__(
            business_id,
            user_id,
            user__id,
            first_name=first_name,
            last_name=last_name,
            phone=phone,
            email=email,
            address=address,
            image=image,
            file_path=file_path,
            city=city,
            town=town,
            postal_code=postal_code,
            status=status,
        )

        # Encrypt fields
        self.first_name = encrypt_data(first_name)
        self.last_name = encrypt_data(last_name)
        self.phone = encrypt_data(phone)
        self.hashed_phone = hash_data(phone)

        self.email = encrypt_data(email) if email else None
        self.address = encrypt_data(address) if address else None
        self.city = encrypt_data(city) if city else None
        self.town = encrypt_data(town) if town else None
        self.postal_code = encrypt_data(postal_code) if postal_code else None
        self.status = encrypt_data(status)

        self.image = encrypt_data(image) if image else None
        self.file_path = encrypt_data(file_path) if file_path else None

        # Timestamps
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the customer object to a dictionary with encrypted fields.
        """
        customer_dict = super().to_dict()
        customer_dict.update({
            "first_name": self.first_name,
            "last_name": self.last_name,
            "phone": self.phone,
            "email": self.email,
            "address": self.address,
            "image": self.image,
            "file_path": self.file_path,
            "city": self.city,
            "town": self.town,
            "postal_code": self.postal_code,
            "status": self.status,
            "hashed_phone": self.hashed_phone,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return customer_dict

    # -------------------------------------------------
    # GET BY ID
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, customer_id, business_id):
        """
        Retrieve a customer by _id and business_id (business-scoped).
        """
        try:
            customer_id_obj = ObjectId(customer_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        # Use BaseModel.get_by_id just like Unit & Tax
        data = super().get_by_id(customer_id_obj, business_id_obj)

        if not data:
            return None

        # Normalise IDs
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields
        data["first_name"] = decrypt_data(data["first_name"]) if data.get("first_name") else None
        data["last_name"] = decrypt_data(data["last_name"]) if data.get("last_name") else None
        data["phone"] = decrypt_data(data["phone"]) if data.get("phone") else None
        data["email"] = decrypt_data(data["email"]) if data.get("email") else None
        data["address"] = decrypt_data(data["address"]) if data.get("address") else None
        data["image"] = decrypt_data(data["image"]) if data.get("image") else None
        data["file_path"] = decrypt_data(data["file_path"]) if data.get("file_path") else None
        data["city"] = decrypt_data(data["city"]) if data.get("city") else None
        data["town"] = decrypt_data(data["town"]) if data.get("town") else None
        data["postal_code"] = decrypt_data(data["postal_code"]) if data.get("postal_code") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Clean up internal fields
        data.pop("hashed_phone", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)
        data.pop("file_path", None)

        return data

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for c in payload.get("items", []):
            # Normalize IDs
            if "_id" in c:
                c["_id"] = str(c["_id"])
            if "business_id" in c:
                c["business_id"] = str(c["business_id"])
            if "user__id" in c:
                c["user__id"] = str(c["user__id"])

            # Decrypt fields
            c["first_name"] = decrypt_data(c["first_name"]) if c.get("first_name") else None
            c["last_name"] = decrypt_data(c["last_name"]) if c.get("last_name") else None
            c["phone"] = decrypt_data(c["phone"]) if c.get("phone") else None
            c["email"] = decrypt_data(c["email"]) if c.get("email") else None
            c["address"] = decrypt_data(c["address"]) if c.get("address") else None
            c["image"] = decrypt_data(c["image"]) if c.get("image") else None
            c["file_path"] = decrypt_data(c["file_path"]) if c.get("file_path") else None
            c["city"] = decrypt_data(c["city"]) if c.get("city") else None
            c["town"] = decrypt_data(c["town"]) if c.get("town") else None
            c["postal_code"] = decrypt_data(c["postal_code"]) if c.get("postal_code") else None
            c["status"] = decrypt_data(c["status"])

            # Timestamps preserved
            c["created_at"] = c.get("created_at")
            c["updated_at"] = c.get("updated_at")

            # Remove internal fields
            c.pop("hashed_phone", None)
            c.pop("agent_id", None)
            c.pop("admin_id", None)
            c.pop("file_path", None)

            processed.append(c)

        payload["customers"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # GET BY USER + BUSINESS
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []
        for c in payload.get("items", []):

            # Normalize IDs
            if "_id" in c:
                c["_id"] = str(c["_id"])
            if "user__id" in c:
                c["user__id"] = str(c["user__id"])
            if "business_id" in c:
                c["business_id"] = str(c["business_id"])

            # Decrypt fields
            c["first_name"] = decrypt_data(c["first_name"]) if c.get("first_name") else None
            c["last_name"] = decrypt_data(c["last_name"]) if c.get("last_name") else None
            c["phone"] = decrypt_data(c["phone"]) if c.get("phone") else None
            c["email"] = decrypt_data(c["email"]) if c.get("email") else None
            c["address"] = decrypt_data(c["address"]) if c.get("address") else None
            c["image"] = decrypt_data(c["image"]) if c.get("image") else None
            c["file_path"] = decrypt_data(c["file_path"]) if c.get("file_path") else None
            c["city"] = decrypt_data(c["city"]) if c.get("city") else None
            c["town"] = decrypt_data(c["town"]) if c.get("town") else None
            c["postal_code"] = decrypt_data(c["postal_code"]) if c.get("postal_code") else None
            c["status"] = decrypt_data(c["status"])

            # Remove internal fields
            c.pop("hashed_phone", None)
            c.pop("agent_id", None)
            c.pop("admin_id", None)
            c.pop("file_path", None)

            processed.append(c)

        payload["customers"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, customer_id, **updates):
        updates["updated_at"] = datetime.now()

        if "first_name" in updates:
            updates["first_name"] = encrypt_data(updates["first_name"])
        if "last_name" in updates:
            updates["last_name"] = encrypt_data(updates["last_name"])
        if "phone" in updates:
            updates["phone"] = encrypt_data(updates["phone"])
            updates["hashed_phone"] = hash_data(decrypt_data(updates["phone"]))
        if "email" in updates:
            updates["email"] = encrypt_data(updates["email"]) if updates["email"] else None
        if "address" in updates:
            updates["address"] = encrypt_data(updates["address"]) if updates["address"] else None
        if "image" in updates:
            updates["image"] = encrypt_data(updates["image"]) if updates["image"] else None
        if "file_path" in updates:
            updates["file_path"] = encrypt_data(updates["file_path"]) if updates["file_path"] else None
        if "city" in updates:
            updates["city"] = encrypt_data(updates["city"]) if updates["city"] else None
        if "town" in updates:
            updates["town"] = encrypt_data(updates["town"]) if updates["town"] else None
        if "postal_code" in updates:
            updates["postal_code"] = encrypt_data(updates["postal_code"]) if updates["postal_code"] else None
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])

        return super().update(customer_id, **updates)

    # -------------------------------------------------
    # DELETE
    # -------------------------------------------------
    @classmethod
    def delete(cls, customer_id, business_id):
        try:
            customer_id_obj = ObjectId(customer_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(customer_id_obj, business_id_obj)

# Customer Groups
class CustomerGroup(BaseModel):
    """
    A CustomerGroup represents a specific group of customers assigned to a business.
    """

    collection_name = "customer_groups"

    def __init__(self, business_id, user_id, user__id, name, status="Active"):
        super().__init__(business_id, user_id, user__id, name=name, status=status)

        # Encrypt fields
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.status = encrypt_data(status)

        # Timestamps
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the customer group object to a dictionary representation.
        """
        customer_group_dict = super().to_dict()
        customer_group_dict.update({
            "name": self.name,
            "status": self.status,
            "hashed_name": self.hashed_name,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return customer_group_dict

    # -------------------------------------------------
    # GET BY ID (business-scoped)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, customer_group_id, business_id):
        """
        Retrieve a customer group by _id and business_id (business-scoped).
        """
        try:
            cg_id_obj = ObjectId(customer_group_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None

        data = super().get_by_id(cg_id_obj, business_id_obj)
        if not data:
            return None

        # Normalise IDs
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])

        # Decrypt fields
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Remove internal fields
        data.pop("hashed_name", None)
        data.pop("admin_id", None)
        data.pop("agent_id", None)

        return data

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve customer groups by business_id with pagination,
        using BaseModel.get_by_business_id.
        """
        payload = super().get_by_business_id(business_id, page, per_page)
        processed = []

        for g in payload.get("items", []):
            # Normalise IDs
            if "_id" in g:
                g["_id"] = str(g["_id"])
            if "business_id" in g:
                g["business_id"] = str(g["business_id"])
            if "user__id" in g:
                g["user__id"] = str(g["user__id"])

            # Decrypt fields
            g["name"] = decrypt_data(g["name"]) if g.get("name") else None
            g["status"] = decrypt_data(g["status"]) if g.get("status") else None

            # Timestamps preserved
            g["created_at"] = g.get("created_at")
            g["updated_at"] = g.get("updated_at")

            # Remove internal fields
            g.pop("hashed_name", None)
            g.pop("admin_id", None)
            g.pop("agent_id", None)

            processed.append(g)

        payload["customer_groups"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # GET BY USER + BUSINESS (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve customer groups by user__id and business_id with pagination.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []
        for g in payload.get("items", []):
            # Normalise IDs
            if "_id" in g:
                g["_id"] = str(g["_id"])
            if "user__id" in g:
                g["user__id"] = str(g["user__id"])
            if "business_id" in g:
                g["business_id"] = str(g["business_id"])

            # Decrypt fields
            g["name"] = decrypt_data(g["name"]) if g.get("name") else None
            g["status"] = decrypt_data(g["status"]) if g.get("status") else None

            # Timestamps preserved
            g["created_at"] = g.get("created_at")
            g["updated_at"] = g.get("updated_at")

            # Remove internal fields
            g.pop("hashed_name", None)
            g.pop("admin_id", None)
            g.pop("agent_id", None)

            processed.append(g)

        payload["customer_groups"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, customer_group_id, **updates):
        """
        Update a customer group's information by customer_group_id.
        """
        updates["updated_at"] = datetime.now()

        if "name" in updates:
            # hash + encrypt name
            updates["hashed_name"] = hash_data(updates["name"])
            updates["name"] = encrypt_data(updates["name"])

        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])

        return super().update(customer_group_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, customer_group_id, business_id):
        """
        Delete a customer group by id and business_id (business-scoped).
        """
        try:
            cg_id_obj = ObjectId(customer_group_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(cg_id_obj, business_id_obj)

# User
class SystemUser(BaseModel):
    """
    A SystemUser represents a user in the system with different roles such as Cashier, Manager, or Admin.
    """

    collection_name = "system_users"  # Set the collection name

    def __init__(self, business_id,role, user_id, username, display_name, outlet, 
                 password, phone=None, email=None, image=None, file_path=None, status="Active", date_of_birth=None, gender=None, marital_status=None, 
                 alternative_phone=None, family_contact_number=None, twitter_link=None, id_type=None,
                 id_number=None, permanent_address=None, current_address=None, account_name=None, 
                 account_number=None, bank_name=None, sort_code=None, branch=None, tax_payer_id=None):
        
        super().__init__(business_id=business_id,role=role, user_id=user_id, username=username, display_name=display_name, 
                         phone=phone, email=email, image=image, file_path=file_path, 
                         outlet=outlet, password=password, status=status)


        self.role = ObjectId(role) # Encrypt role
        self.username = encrypt_data(username)  # Encrypt the username
        self.hashed_username = hash_data(username)  # Encrypt the hashed username
        self.display_name = encrypt_data(display_name)  # Encrypt display_name
        self.phone = encrypt_data(phone) if phone else None  # Encrypt phone number if provided
        self.email = encrypt_data(email) if email else None  # Encrypt email if provided
        self.image = encrypt_data(image) if image else None  # Encrypt image if provided
        self.file_path = encrypt_data(file_path) if file_path else None  # Encrypt file path
        self.outlet = encrypt_data(outlet)  # Encrypt outlet
        # Hash the password if not already hashed
        if not password.startswith("$2b$"):
            self.password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        else:
            self.password = password  # If already hashed, store as is
        self.status = encrypt_data(status)  # Encrypt status
        self.date_of_birth = encrypt_data(date_of_birth) if date_of_birth else None
        self.gender = encrypt_data(gender) if gender else None
        self.marital_status = encrypt_data(marital_status) if marital_status else None
        self.alternative_phone = encrypt_data(alternative_phone) if alternative_phone else None
        self.family_contact_number = encrypt_data(family_contact_number) if family_contact_number else None
        self.twitter_link = encrypt_data(twitter_link) if twitter_link else None
        self.id_type = encrypt_data(id_type) if id_type else None
        self.id_number = encrypt_data(id_number) if id_number else None
        self.permanent_address = encrypt_data(permanent_address) if permanent_address else None
        self.current_address = encrypt_data(current_address) if current_address else None
        self.account_name = encrypt_data(account_name) if account_name else None
        self.account_number = encrypt_data(account_number) if account_number else None
        self.bank_name = encrypt_data(bank_name) if bank_name else None
        self.sort_code = encrypt_data(sort_code) if sort_code else None
        self.branch = encrypt_data(branch) if branch else None
        self.tax_payer_id = encrypt_data(tax_payer_id) if tax_payer_id else None

        # Add created and updated timestamps
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.last_logged_in = None  # Default to None unless logged in

    def to_dict(self):
        """
        Convert the system user object to a dictionary representation.
        """
        user_dict = super().to_dict()
        user_dict.update({
            "role": self.role,
            "username": self.username,
            "display_name": self.display_name,
            "phone": self.phone,
            "email": self.email,
            "image": self.image,
            "file_path": self.file_path,
            "outlet": self.outlet,
            "status": self.status,
            "date_of_birth": self.date_of_birth,
            "gender": self.gender,
            "marital_status": self.marital_status,
            "alternative_phone": self.alternative_phone,
            "family_contact_number": self.family_contact_number,
            "twitter_link": self.twitter_link,
            "id_type": self.id_type,
            "id_number": self.id_number,
            "permanent_address": self.permanent_address,
            "current_address": self.current_address,
            "account_name": self.account_name,
            "account_number": self.account_number,
            "bank_name": self.bank_name,
            "sort_code": self.sort_code,
            "branch": self.branch,
            "tax_payer_id": self.tax_payer_id,
            "last_logged_in": self.last_logged_in,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return user_dict

    @classmethod
    def get_by_id(cls, system_user_id):
        """
        Retrieve a system user by system_user_id.
        """
        try:
            # Convert system_user_id to ObjectId for the query
            system_user_id_obj = ObjectId(system_user_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)

        # Query using _id (which is MongoDB's default unique identifier)
        data = db[cls.collection_name].find_one({"_id": system_user_id_obj})

        if not data:
            return None  # User not found

        # Convert ObjectId to string for JSON serialization
        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])
        data["role"] = str(data["role"])

        # Decrypt fields before returning
        data["username"] = decrypt_data(data["username"])
        data["display_name"] = decrypt_data(data["display_name"])
        data["phone"] = decrypt_data(data["phone"]) if data["phone"] else None
        data["email"] = decrypt_data(data["email"]) if data["email"] else None
        data["image"] = decrypt_data(data["image"]) if data["image"] else None
        data["file_path"] = decrypt_data(data["file_path"]) if data["file_path"] else None
        data["outlet"] = decrypt_data(data["outlet"])
        data["status"] = decrypt_data(data["status"])
        data["date_of_birth"] = decrypt_data(data["date_of_birth"]) if data["date_of_birth"] else None
        data["gender"] = decrypt_data(data["gender"]) if data["gender"] else None
        data["marital_status"] = decrypt_data(data["marital_status"]) if data["marital_status"] else None
        data["alternative_phone"] = decrypt_data(data["alternative_phone"]) if data["alternative_phone"] else None
        data["family_contact_number"] = decrypt_data(data["family_contact_number"]) if data["family_contact_number"] else None
        data["twitter_link"] = decrypt_data(data["twitter_link"]) if data["twitter_link"] else None
        data["id_type"] = decrypt_data(data["id_type"]) if data["id_type"] else None
        data["id_number"] = decrypt_data(data["id_number"]) if data["id_number"] else None
        data["permanent_address"] = decrypt_data(data["permanent_address"]) if data["permanent_address"] else None
        data["current_address"] = decrypt_data(data["current_address"]) if data["current_address"] else None
        data["account_name"] = decrypt_data(data["account_name"]) if data["account_name"] else None
        data["account_number"] = decrypt_data(data["account_number"]) if data["account_number"] else None
        data["bank_name"] = decrypt_data(data["bank_name"]) if data["bank_name"] else None
        data["sort_code"] = decrypt_data(data["sort_code"]) if data["sort_code"] else None
        data["branch"] = decrypt_data(data["branch"]) if data["branch"] else None
        data["tax_payer_id"] = decrypt_data(data["tax_payer_id"]) if data["tax_payer_id"] else None

        # Remove encrypted password and hashed username from response
        data.pop("password", None)
        data.pop("hashed_username", None)

        return data

    @classmethod
    def update(cls, system_user_id, **updates):
        """
        Update a system user's information by system_user_id.

        Args:
        - system_user_id: The ID of the system user to be updated.
        - **updates: The fields to be updated with their new values.
        """
        # Encrypt the fields if they are being updated
        if "username" in updates:
            updates["username"] = encrypt_data(updates["username"])
        if "display_name" in updates:
            updates["display_name"] = encrypt_data(updates["display_name"])
        if "phone" in updates:
            updates["phone"] = encrypt_data(updates["phone"])
        if "email" in updates:
            updates["email"] = encrypt_data(updates["email"]) if updates["email"] else None
        if "image" in updates:
            updates["image"] = encrypt_data(updates["image"]) if updates["image"] else None
        if "outlet" in updates:
            updates["outlet"] = encrypt_data(updates["outlet"])
        if "role" in updates:
            updates["role"] = ObjectId(updates["role"])
        if "status" in updates:
            updates["status"] = encrypt_data(updates["status"])
        if "date_of_birth" in updates:
            updates["date_of_birth"] = encrypt_data(updates["date_of_birth"]) if updates["date_of_birth"] else None
        if "gender" in updates:
            updates["gender"] = encrypt_data(updates["gender"]) if updates["gender"] else None
        if "marital_status" in updates:
            updates["marital_status"] = encrypt_data(updates["marital_status"]) if updates["marital_status"] else None
        if "alternative_phone" in updates:
            updates["alternative_phone"] = encrypt_data(updates["alternative_phone"]) if updates["alternative_phone"] else None
        if "family_contact_number" in updates:
            updates["family_contact_number"] = encrypt_data(updates["family_contact_number"]) if updates["family_contact_number"] else None
        if "twitter_link" in updates:
            updates["twitter_link"] = encrypt_data(updates["twitter_link"]) if updates["twitter_link"] else None
        if "id_type" in updates:
            updates["id_type"] = encrypt_data(updates["id_type"]) if updates["id_type"] else None
        if "id_number" in updates:
            updates["id_number"] = encrypt_data(updates["id_number"]) if updates["id_number"] else None
        if "permanent_address" in updates:
            updates["permanent_address"] = encrypt_data(updates["permanent_address"]) if updates["permanent_address"] else None
        if "current_address" in updates:
            updates["current_address"] = encrypt_data(updates["current_address"]) if updates["current_address"] else None
        if "account_name" in updates:
            updates["account_name"] = encrypt_data(updates["account_name"]) if updates["account_name"] else None
        if "account_number" in updates:
            updates["account_number"] = encrypt_data(updates["account_number"]) if updates["account_number"] else None
        if "bank_name" in updates:
            updates["bank_name"] = encrypt_data(updates["bank_name"]) if updates["bank_name"] else None
        if "sort_code" in updates:
            updates["sort_code"] = encrypt_data(updates["sort_code"]) if updates["sort_code"] else None
        if "branch" in updates:
            updates["branch"] = encrypt_data(updates["branch"]) if updates["branch"] else None
        if "tax_payer_id" in updates:
            updates["tax_payer_id"] = encrypt_data(updates["tax_payer_id"]) if updates["tax_payer_id"] else None

        return super().update(system_user_id, **updates)

    @classmethod
    def delete(cls, system_user_id):
        """
        Delete a system user by system_user_id.
        """
        return super().delete(system_user_id)
