# models/product.py
from bson.objectid import ObjectId
from datetime import datetime, date
from math import ceil
from app import db
from pymongo.errors import BulkWriteError
from bson.errors import InvalidId
from ..utils.logger import Log # import logging
from pymongo.errors import PyMongoError
from ..utils.crypt import encrypt_data, decrypt_data, hash_data
from ..models.base_model import BaseModel

class Product(BaseModel):
    """
    A Product represents an item in a business, including its variants, pricing, and other details.
    Enhanced for POS system integration with proper inventory tracking.
    """

    collection_name = "products"

    # All encrypted fields that we need to decrypt when reading
    FIELDS_TO_DECRYPT = [
        "name", "brand", "description", "tags", "category",
        "sell_on_point_of_sale", "images", "file_paths",
        "product_type", "sku", "suppliers", "track_inventory",
        "product_location", "tax", "prices", "variants",
        "composite_product", "status", "warranty", "manufacturer",
        "manufactured_date", "expiry_on", "subcategory", "unit",
        "alert_quantity", "barcode_symbology", "selling_price_group"
    ]

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        admin_id,
        name,
        product_type,
        brand=None,
        description=None,
        tags=None,
        category=None,
        subcategory=None,
        unit=None,
        sell_on_point_of_sale=1,  # Changed default to 1 (enabled)
        images=None,
        file_paths=None,
        sku=None,
        suppliers=None,
        track_inventory=1,  # Changed default to 1 (enabled)
        alert_quantity=None,  # Low stock alert threshold
        product_location=None,
        tax=None,
        prices=None,
        variants=None,
        composite_product=None,
        status="Active",
        warranty=None,
        manufacturer=None,
        manufactured_date=None,
        expiry_on=None,
        barcode_symbology=None,
        selling_price_group=None
    ):
        """
        Create a new Product instance.

        All business/domain fields are encrypted before persistence.
        
        Args:
            business_id: Business ObjectId
            user_id: User string ID
            user__id: User ObjectId
            name: Product name (required)
            product_type: Product type (required) - "Single", "Variable", "Combo"
            brand: Brand ObjectId or string
            description: Product description
            tags: List of tag ObjectIds or strings
            category: Category ObjectId or string
            subcategory: Subcategory ObjectId or string
            unit: Unit ObjectId or string
            sell_on_point_of_sale: 0 or 1 (default 1)
            images: List of image URLs
            file_paths: List of actual file paths
            sku: Stock Keeping Unit code
            suppliers: List of supplier ObjectIds or strings
            track_inventory: 0 or 1 (default 1) - use StockLedger if 1
            alert_quantity: Low stock alert threshold
            product_location: Location in warehouse
            tax: Tax ObjectId or string
            prices: Pricing structure
            variants: List of variant ObjectIds (for variable products)
            composite_product: List of component products (for combo products)
            status: "Active" or "Inactive"
            warranty: Warranty ObjectId or string
            manufacturer: Manufacturer name
            manufactured_date: Manufacturing date
            expiry_on: Expiry date
            barcode_symbology: Barcode type (Code128, EAN13, etc.)
            selling_price_group: Selling price group ObjectId
            admin_id: Optional admin ObjectId
        """
        super().__init__(
            business_id,
            user_id,
            user__id,
            admin_id=admin_id,
            name=name,
            brand=brand,
            description=description,
            tags=tags,
            category=category,
            subcategory=subcategory,
            unit=unit,
            sell_on_point_of_sale=sell_on_point_of_sale,
            images=images,
            file_paths=file_paths,
            product_type=product_type,
            sku=sku,
            suppliers=suppliers,
            track_inventory=track_inventory,
            alert_quantity=alert_quantity,
            product_location=product_location,
            tax=tax,
            prices=prices,
            variants=variants,
            composite_product=composite_product,
            status=status,
            warranty=warranty,
            manufacturer=manufacturer,
            manufactured_date=manufactured_date,
            expiry_on=expiry_on,
            barcode_symbology=barcode_symbology,
            selling_price_group=selling_price_group,
        )

        # Name + hash (required)
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)

        # Required field
        self.product_type = encrypt_data(product_type)

        # Use locals() only to get constructor parameters
        params = locals()

        # Fields that default to None when not provided
        none_default_fields = [
            "brand", "description", "tags", "category", "subcategory", "unit",
            "images", "file_paths", "sku", "suppliers",
            "product_location", "tax", "prices", "variants",
            "composite_product", "warranty", "manufacturer",
            "manufactured_date", "expiry_on", "status", "alert_quantity",
            "barcode_symbology", "selling_price_group"
        ]
        
        for field in none_default_fields:
            value = params.get(field)
            if value is not None:
                setattr(self, field, encrypt_data(value))
            else:
                setattr(self, field, None)
                
        
        # Handle tags - store as array of ObjectIds
        tags_value = params.get("tags")
        if tags_value is not None:
            if isinstance(tags_value, list):
                # Convert to ObjectId strings and validate
                normalized_tags = self._normalize_object_id_array(tags_value, "tags")
                self.tags = encrypt_data(normalized_tags)
            else:
                raise ValueError("tags must be a list of ObjectIds or strings")
        else:
            self.tags = None

        # Handle suppliers - store as array of ObjectIds
        suppliers_value = params.get("suppliers")
        if suppliers_value is not None:
            if isinstance(suppliers_value, list):
                # Convert to ObjectId strings and validate
                normalized_suppliers = self._normalize_object_id_array(suppliers_value, "suppliers")
                self.suppliers = encrypt_data(normalized_suppliers)
            else:
                raise ValueError("suppliers must be a list of ObjectIds or strings")
        else:
            self.suppliers = None
        
        # Handle tax - store as array of ObjectIds
        taxes_value = params.get("tax")
        if taxes_value is not None:
            if isinstance(taxes_value, list):
                # Convert to ObjectId strings and validate
                normalized_taxes = self._normalize_object_id_array(taxes_value, "tax")
                self.tax = encrypt_data(normalized_taxes)
            else:
                raise ValueError("taxes must be a list of ObjectIds or strings")
        else:
            self.tax = None

        # Fields that default to 1 (enabled) or 0 (disabled)
        binary_fields = {
            "sell_on_point_of_sale": 1,  # Enable POS by default
            "track_inventory": 1,  # Track inventory by default
        }
        for field, default_val in binary_fields.items():
            value = params.get(field)
            if value is not None:
                setattr(self, field, encrypt_data(value))
            else:
                setattr(self, field, encrypt_data(default_val))

        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        """
        Convert the product object to a dictionary representation.

        - Uses BaseModel.to_dict() for core fields (business_id, user_id, name, etc.).
        - Adds all active domain fields listed in FIELDS_TO_DECRYPT.
        """
        product_dict = super().to_dict()

        # Add all "active" domain fields based on FIELDS_TO_DECRYPT
        extra_fields = {}
        for field in self.FIELDS_TO_DECRYPT:
            if hasattr(self, field):
                extra_fields[field] = getattr(self, field)

        # Add timestamps explicitly
        extra_fields.update({
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })

        product_dict.update(extra_fields)
        
        return product_dict

    # ------------------------ INTERNAL HELPERS ------------------------ #
    @staticmethod
    def _normalize_object_id_array(items, field_name):
        """
        Normalize an array of ObjectIds or strings to string array.
        
        Args:
            items: List of ObjectIds or strings
            field_name: Name of field for error messages
            
        Returns:
            List of ObjectId strings
        """
        normalized = []
        for item in items:
            if isinstance(item, ObjectId):
                normalized.append(str(item))
            elif isinstance(item, str):
                # Validate it's a valid ObjectId string
                try:
                    ObjectId(item)
                    normalized.append(item)
                except Exception as e:
                    raise ValueError(f"Invalid ObjectId in {field_name}: {item}")
            else:
                raise ValueError(f"Invalid type in {field_name}: expected ObjectId or string, got {type(item)}")
        return normalized
   
        
    @classmethod
    def _decrypt_and_normalise_product_doc(cls, data: dict) -> dict:
        """
        Internal helper:
        - Normalises ObjectIds to strings.
        - Decrypts all FIELDS_TO_DECRYPT.
        - Removes internal/sensitive fields.
        - Returns a product payload ready to send to clients.
        """
        if not data:
            return None

        # Normalise IDs
        if "_id" in data:
            data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user_id" in data and data["user_id"] is not None:
            data["user_id"] = str(data["user_id"])
        if "user__id" in data and data["user__id"] is not None:
            data["user__id"] = str(data["user__id"])
        if "admin_id" in data and data["admin_id"] is not None:
            data["admin_id"] = str(data["admin_id"])

        # Decrypt configured fields
        decrypted = {}
        for field in getattr(cls, "FIELDS_TO_DECRYPT", []):
            value = data.get(field)
            decrypted[field] = decrypt_data(value) if value is not None else None

        product = {
            "_id": data.get("_id"),
            "business_id": data.get("business_id"),
            "user_id": data.get("user_id"),
            "user__id": data.get("user__id"),
            "admin_id": data.get("admin_id"),
            **decrypted,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }

        # Remove internal / sensitive fields if present
        product.pop("file_path", None)   # legacy single file path
        product.pop("hashed_name", None)
        product.pop("file_paths", None)

        return product

    # ------------------------ QUERIES ------------------------ #

    @classmethod
    def get_by_id(cls, product_id, business_id):
        """
        Retrieve a single product by _id and business_id, decrypting selected fields.
        
        Args:
            product_id: Product ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Decrypted product dict or None
        """
        log_tag = f"[product.py][Product][get_by_id][{product_id}][{business_id}]"
        
        try:
            product_id_obj = ObjectId(product_id) if not isinstance(product_id, ObjectId) else product_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        except Exception as e:
            Log.error(f"{log_tag} Invalid ObjectId format: {e}")
            return None

        data = super().get_by_id(product_id_obj, business_id_obj)
        if not data:
            Log.info(f"{log_tag} Product not found")
            return None

        product = cls._decrypt_and_normalise_product_doc(data)
        Log.info(f"{log_tag} Product retrieved successfully")
        return product

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve products by business_id with pagination and decrypted fields.

        Args:
            business_id: Business ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            
        Returns:
            Dict with paginated products:
            {
                "products": [...],
                "total_count": ...,
                "total_pages": ...,
                "current_page": ...,
                "per_page": ...
            }
        """
        log_tag = f"[product.py][Product][get_by_business_id][{business_id}]"
        
        try:
            payload = super().get_by_business_id(business_id, page, per_page)
            processed = []

            for data in payload.get("items", []):
                product = cls._decrypt_and_normalise_product_doc(data)
                if product is not None:
                    processed.append(product)

            payload["products"] = processed
            payload.pop("items", None)

            Log.info(f"{log_tag} Retrieved {len(processed)} products")
            return payload
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return {"products": [], "total_count": 0, "total_pages": 0, "current_page": page or 1, "per_page": per_page or 50}

    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve products by user__id and business_id with pagination and decrypted fields.

        Args:
            user__id: User ObjectId or string
            business_id: Business ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            
        Returns:
            Dict with paginated products:
            {
                "products": [...],
                "total_count": ...,
                "total_pages": ...,
                "current_page": ...,
                "per_page": ...
            }
        """
        log_tag = f"[product.py][Product][get_by_user__id_and_business_id][{user__id}][{business_id}]"
        
        try:
            payload = super().get_all_by_user__id_and_business_id(
                user__id=user__id,
                business_id=business_id,
                page=page,
                per_page=per_page,
            )
            processed = []

            for data in payload.get("items", []):
                product = cls._decrypt_and_normalise_product_doc(data)
                if product is not None:
                    processed.append(product)

            payload["products"] = processed
            payload.pop("items", None)

            Log.info(f"{log_tag} Retrieved {len(processed)} products")
            return payload
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return {"products": [], "total_count": 0, "total_pages": 0, "current_page": page or 1, "per_page": per_page or 50}

    @classmethod
    def get_pos_products(cls, business_id, outlet_id=None, category_id=None, search_term=None, page=None, per_page=None):
        """
        Get products suitable for POS display with optional filtering.
        Only returns products where sell_on_point_of_sale = 1 and status = Active.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Optional outlet filter (for outlet-specific inventory)
            category_id: Optional category filter
            search_term: Optional search term (searches name, sku)
            page: Optional page number
            per_page: Optional items per page
            
        Returns:
            Dict with paginated POS-ready products
        """
        log_tag = f"[product.py][Product][get_pos_products][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            # Build query for POS products
            query = {
                "business_id": business_id,
                "sell_on_point_of_sale": encrypt_data(1),
                "status": encrypt_data("Active")
            }
            
            # Add category filter if provided
            if category_id:
                category_id = ObjectId(category_id) if not isinstance(category_id, ObjectId) else category_id
                query["category"] = encrypt_data(str(category_id))
            
            # Note: Search by encrypted name/sku is not efficient
            # Consider using hashed_name for exact matches or implementing full-text search
            
            result = cls.paginate(query, page, per_page)
            
            # Decrypt all products
            processed = []
            for data in result.get("items", []):
                product = cls._decrypt_and_normalise_product_doc(data)
                if product is not None:
                    # Apply search filter after decryption (not ideal for large datasets)
                    if search_term:
                        search_lower = search_term.lower()
                        name_match = search_lower in (product.get("name") or "").lower()
                        sku_match = search_lower in (product.get("sku") or "").lower()
                        if not (name_match or sku_match):
                            continue
                    
                    processed.append(product)
            
            result["products"] = processed
            result.pop("items", None)
            
            Log.info(f"{log_tag} Retrieved {len(processed)} POS products")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return {"products": [], "total_count": 0, "total_pages": 0, "current_page": page or 1, "per_page": per_page or 50}

    # ------------------------ UPDATE / DELETE ------------------------ #

    @classmethod
    def update(cls, product_id, **updates):
        """
        Update a product's information by product_id.

        - Automatically refreshes `updated_at`.
        - Re-hashes + re-encrypts `name` when present.
        - Encrypts all FIELDS_TO_DECRYPT included in `updates`.
        
        Args:
            product_id: Product ObjectId or string
            **updates: Fields to update
            
        Returns:
            Bool - success status
        """
        log_tag = f"[product.py][Product][update][{product_id}]"
        
        try:
            updates["updated_at"] = datetime.utcnow()

            # Handle name specially (include hashed_name)
            if "name" in updates and updates["name"] is not None:
                updates["hashed_name"] = hash_data(updates["name"])
                updates["name"] = encrypt_data(updates["name"])

            # Encrypt all other encrypted fields if present in updates
            fields_to_encrypt = [f for f in cls.FIELDS_TO_DECRYPT if f != "name"]
            for field in fields_to_encrypt:
                if field in updates and updates[field] is not None:
                    updates[field] = encrypt_data(updates[field])

            result = super().update(product_id, **updates)
            
            if result:
                Log.info(f"{log_tag} Product updated successfully")
            else:
                Log.error(f"{log_tag} Product update failed")
                
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {e}")
            return False

    @classmethod
    def bulk_upsert(cls, business_id, user_info, items, mode="upsert"):
        """
        mode:
        - create: insert only (fails on duplicates)
        - upsert: update if sku exists, else insert (preferred)
        """
        col = db.get_collection(cls.collection_name)
        business_oid = ObjectId(business_id)

        now = datetime.utcnow()
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        admin_id = user_info.get("_id")

        ops = []
        results = {"inserted": 0, "updated": 0, "errors": []}

        for i, raw in enumerate(items):
            sku = (raw.get("sku") or "").strip() or None

            # Build the same payload your constructor expects (plain values)
            payload = dict(raw)
            payload["business_id"] = business_id
            payload["user_id"] = user_id
            payload["user__id"] = user__id
            payload["admin_id"] = admin_id

            # Validate minimum: for upsert we need sku or name uniqueness strategy
            if mode == "upsert" and not sku:
                results["errors"].append({"row": i+1, "error": "SKU_REQUIRED_FOR_UPSERT"})
                continue

            # Create an instance to reuse your encryption logic
            try:
                obj = cls(**payload)
                doc = obj.to_dict()
                doc["business_id"] = business_oid
                doc["updated_at"] = now
            except Exception as e:
                results["errors"].append({"row": i+1, "error": str(e)})
                continue

            if mode == "create":
                ops.append(doc)
            else:
                # upsert by (business_id, sku)
                ops.append((
                    {"business_id": business_oid, "sku": doc.get("sku")},
                    {"$set": doc, "$setOnInsert": {"created_at": now}},
                    True
                ))

        # Execute
        try:
            if mode == "create":
                if ops:
                    res = col.insert_many(ops, ordered=False)
                    results["inserted"] = len(res.inserted_ids)
            else:
                from pymongo import UpdateOne
                bulk_ops = [UpdateOne(f, u, upsert=True) for (f, u, upsert) in ops if isinstance(f, dict)]
                if bulk_ops:
                    res = col.bulk_write(bulk_ops, ordered=False)
                    results["updated"] = res.modified_count
                    results["inserted"] = res.upserted_count

        except BulkWriteError as e:
            # collect detailed errors but continue
            results["errors"].append({"bulk_error": e.details})

        return results
    
    @classmethod
    def delete(cls, product_id, business_id):
        """
        Delete a product by _id and business_id.
        
        Args:
            product_id: Product ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Bool - success status
        """
        log_tag = f"[product.py][Product][delete][{product_id}][{business_id}]"
        
        try:
            product_id_obj = ObjectId(product_id) if not isinstance(product_id, ObjectId) else product_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        except Exception as e:
            Log.error(f"{log_tag} Invalid ObjectId format: {e}")
            return False

        result = super().delete(product_id_obj, business_id_obj)
        
        if result:
            Log.info(f"{log_tag} Product deleted successfully")
        else:
            Log.error(f"{log_tag} Product deletion failed")
            
        return result

    # Add to models/product.py

    @classmethod
    def create_indexes(cls):
        """
        Create database indexes for optimal query performance
        AND enforce uniqueness where required.
        Run this once during setup or migration.
        """
        log_tag = "[product.py][Product][create_indexes]"
        collection = db.get_collection(cls.collection_name)

        try:
            # Core indexes for product queries
            collection.create_index(
                [("business_id", 1), ("created_at", -1)],
                name="business_created_at_idx",
            )

            # 🔐 Enforce unique product names per business (via hashed_name)
            collection.create_index(
                [("business_id", 1), ("hashed_name", 1)],
                unique=True,
                name="uniq_business_product_name",
            )

            collection.create_index(
                [("business_id", 1), ("category", 1)],
                name="business_category_idx",
            )
            collection.create_index(
                [("business_id", 1), ("status", 1)],
                name="business_status_idx",
            )

            # Search and lookup indexes
            collection.create_index(
                [("business_id", 1), ("sku", 1)],
                unique=True,
                sparse=True,
                name="uniq_business_sku",
            )
            collection.create_index(
                [("business_id", 1), ("barcode", 1)],
                sparse=True,
                name="business_barcode_idx",
            )

            # Inventory management indexes
            collection.create_index(
                [("business_id", 1), ("quantity", 1)],
                name="business_quantity_idx",
            )
            collection.create_index(
                [("business_id", 1), ("reorder_point", 1)],
                name="business_reorder_point_idx",
            )

            # Variant index
            collection.create_index(
                [("business_id", 1), ("has_variants", 1)],
                name="business_has_variants_idx",
            )

            # Price and cost indexes (for reports)
            collection.create_index(
                [("business_id", 1), ("price", 1)],
                name="business_price_idx",
            )

            # Multi-field compound indexes for common queries
            collection.create_index(
                [("business_id", 1), ("category", 1), ("status", 1)],
                name="business_category_status_idx",
            )
            collection.create_index(
                [("business_id", 1), ("status", 1), ("quantity", 1)],
                name="business_status_quantity_idx",
            )

            # Text search index
            collection.create_index(
                [("name", "text"), ("description", "text")],
                name="product_text_search_idx",
            )

            Log.info(f"{log_tag} Indexes created successfully")
            return True

        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            # 🔴 IMPORTANT: let the caller know this failed
            raise


#-------------------------SALE MODEL--------------------------------------
class Sale(BaseModel):
    """
    A Sale transaction represents a sale of a product in a business, including
    transaction details like customer, supplier, products sold, and pricing.
    """

    collection_name = "sales"

    # Fields we consistently decrypt when reading
    FIELDS_TO_DECRYPT = [
        "date",
        "purchase_price",
        "order_tax",
        "discount",
        "shipping",
        "grand_total",
        "status",
        "sale_type",
        "notes",
        "reason",
    ]

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        customer_id,
        supplier_id,
        product_ids,
        date,
        purchase_price=0.0,
        order_tax=0.0,
        discount=0.0,
        shipping=0.0,
        grand_total=0.0,
        status="Draft",
        sale_type="SALE",
        original_sale_id=None,
        notes=None,
        reason=None,
        created_at=None,
        updated_at=None,
    ):
        """
        Initialise Sale with encrypted monetary fields and linked ObjectIds.
        """

        # Normalise relational IDs to ObjectId
        customer_obj_id = ObjectId(customer_id) if isinstance(customer_id, str) else customer_id
        supplier_obj_id = ObjectId(supplier_id) if isinstance(supplier_id, str) else supplier_id
        product_obj_ids = [
            ObjectId(pid) if isinstance(pid, str) else pid
            for pid in (product_ids or [])
        ]

        original_sale_obj_id = (
            ObjectId(original_sale_id) if isinstance(original_sale_id, str) else original_sale_id
        )

        super().__init__(
            business_id,
            user_id,
            user__id,
            customer_id=customer_obj_id,
            supplier_id=supplier_obj_id,
            product_ids=product_obj_ids,
            date=date,
            purchase_price=purchase_price,
            order_tax=order_tax,
            discount=discount,
            shipping=shipping,
            grand_total=grand_total,
            status=status,
            sale_type=sale_type,
            original_sale_id=original_sale_obj_id,
            notes=notes,
            reason=reason,
            created_at=created_at,
            updated_at=updated_at,
        )

        # Store relational IDs as ObjectId
        self.customer_id = customer_obj_id
        self.supplier_id = supplier_obj_id
        self.product_ids = product_obj_ids
        self.original_sale_id = original_sale_obj_id

        # Encrypt scalar fields
        self.date = encrypt_data(date) if date is not None else None
        self.purchase_price = encrypt_data(purchase_price) if purchase_price is not None else None
        self.order_tax = encrypt_data(order_tax) if order_tax is not None else None
        self.discount = encrypt_data(discount) if discount is not None else None
        self.shipping = encrypt_data(shipping) if shipping is not None else None
        self.grand_total = encrypt_data(grand_total) if grand_total is not None else None
        self.status = encrypt_data(status) if status is not None else None
        self.sale_type = encrypt_data(sale_type) if sale_type is not None else None
        self.notes = encrypt_data(notes) if notes is not None else None
        self.reason = encrypt_data(reason) if reason is not None else None

        # Timestamps
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the Sale object to a dictionary representation.
        """
        sales_dict = super().to_dict()
        sales_dict.update({
            "customer_id": self.customer_id,
            "supplier_id": self.supplier_id,
            "product_ids": self.product_ids,
            "date": self.date,
            "purchase_price": self.purchase_price,
            "order_tax": self.order_tax,
            "discount": self.discount,
            "shipping": self.shipping,
            "grand_total": self.grand_total,
            "status": self.status,
            "sale_type": self.sale_type,
            "original_sale_id": self.original_sale_id,
            "notes": self.notes,
            "reason": self.reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return sales_dict

    # -------------------------------------------------
    # GET BY ID (business-scoped)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, sale_id, business_id):
        """
        Retrieve a sale by _id and business_id (business-scoped).
        """
        try:
            sale_id_obj = ObjectId(sale_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid id / business_id format

        data = super().get_by_id(sale_id_obj, business_id_obj)
        if not data:
            return None

        # Normalise IDs to strings
        if "_id" in data:
            data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])
        if "user_id" in data and data["user_id"] is not None:
            data["user_id"] = str(data["user_id"])
        if "customer_id" in data and data["customer_id"] is not None:
            data["customer_id"] = str(data["customer_id"])
        if "supplier_id" in data and data["supplier_id"] is not None:
            data["supplier_id"] = str(data["supplier_id"])
        if "product_ids" in data and isinstance(data["product_ids"], list):
            data["product_ids"] = [str(pid) for pid in data["product_ids"]]
        if "original_sale_id" in data and data["original_sale_id"] is not None:
            data["original_sale_id"] = str(data["original_sale_id"])

        # Decrypt configured fields
        for field in cls.FIELDS_TO_DECRYPT:
            if field in data and data[field] is not None:
                data[field] = decrypt_data(data[field])

        # Timestamps preserved
        data["created_at"] = data.get("created_at")
        data["updated_at"] = data.get("updated_at")

        # Remove internal/sensitive fields if present
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    # -------------------------------------------------
    # GET BY USER + BUSINESS (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve sales by user__id and business_id with pagination.
        """
        payload = super().get_all_by_user__id_and_business_id(
            user__id=user__id,
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for sale in payload.get("items", []):
            # Normalise IDs
            if "_id" in sale:
                sale["_id"] = str(sale["_id"])
            if "business_id" in sale:
                sale["business_id"] = str(sale["business_id"])
            if "user__id" in sale:
                sale["user__id"] = str(sale["user__id"])
            if "user_id" in sale and sale["user_id"] is not None:
                sale["user_id"] = str(sale["user_id"])
            if "customer_id" in sale and sale["customer_id"] is not None:
                sale["customer_id"] = str(sale["customer_id"])
            if "supplier_id" in sale and sale["supplier_id"] is not None:
                sale["supplier_id"] = str(sale["supplier_id"])
            if "product_ids" in sale and isinstance(sale["product_ids"], list):
                sale["product_ids"] = [str(pid) for pid in sale["product_ids"]]
            if "original_sale_id" in sale and sale["original_sale_id"] is not None:
                sale["original_sale_id"] = str(sale["original_sale_id"])

            # Decrypt business fields
            for field in cls.FIELDS_TO_DECRYPT:
                if sale.get(field) is not None:
                    sale[field] = decrypt_data(sale[field])

            # Timestamps
            sale["created_at"] = sale.get("created_at")
            sale["updated_at"] = sale.get("updated_at")

            # Strip internal / sensitive
            sale.pop("agent_id", None)
            sale.pop("admin_id", None)

            processed.append(sale)

        payload["sales"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve all sales for a business_id with pagination.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for sale in payload.get("items", []):
            # Normalise IDs
            if "_id" in sale:
                sale["_id"] = str(sale["_id"])
            if "business_id" in sale:
                sale["business_id"] = str(sale["business_id"])
            if "user__id" in sale:
                sale["user__id"] = str(sale["user__id"])
            if "user_id" in sale and sale["user_id"] is not None:
                sale["user_id"] = str(sale["user_id"])
            if "customer_id" in sale and sale["customer_id"] is not None:
                sale["customer_id"] = str(sale["customer_id"])
            if "supplier_id" in sale and sale["supplier_id"] is not None:
                sale["supplier_id"] = str(sale["supplier_id"])
            if "product_ids" in sale and isinstance(sale["product_ids"], list):
                sale["product_ids"] = [str(pid) for pid in sale["product_ids"]]
            if "original_sale_id" in sale and sale["original_sale_id"] is not None:
                sale["original_sale_id"] = str(sale["original_sale_id"])

            # Decrypt business fields
            for field in cls.FIELDS_TO_DECRYPT:
                if sale.get(field) is not None:
                    sale[field] = decrypt_data(sale[field])

            # Timestamps
            sale["created_at"] = sale.get("created_at")
            sale["updated_at"] = sale.get("updated_at")

            # Strip internal / sensitive
            sale.pop("agent_id", None)
            sale.pop("admin_id", None)

            processed.append(sale)

        payload["sales"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, sale_id, business_id, **updates):
        """
        Update a sale's information by sale_id.
        (Business/role checks happen at resource layer.)
        """
        updates["updated_at"] = datetime.now()
        updates["business_id"] = business_id

        # IDs: normalise to ObjectId if passed as strings
        if "customer_id" in updates and isinstance(updates["customer_id"], str):
            updates["customer_id"] = ObjectId(updates["customer_id"])
        if "supplier_id" in updates and isinstance(updates["supplier_id"], str):
            updates["supplier_id"] = ObjectId(updates["supplier_id"])
        if "product_ids" in updates and isinstance(updates["product_ids"], list):
            updates["product_ids"] = [
                ObjectId(pid) if isinstance(pid, str) else pid
                for pid in updates["product_ids"]
            ]
        if "original_sale_id" in updates and isinstance(updates["original_sale_id"], str):
            updates["original_sale_id"] = ObjectId(updates["original_sale_id"])

        # Encrypt scalar/money/date/status fields
        if "date" in updates and updates["date"] is not None:
            updates["date"] = encrypt_data(updates["date"])
        if "purchase_price" in updates and updates["purchase_price"] is not None:
            updates["purchase_price"] = encrypt_data(updates["purchase_price"])
        if "order_tax" in updates and updates["order_tax"] is not None:
            updates["order_tax"] = encrypt_data(updates["order_tax"])
        if "discount" in updates and updates["discount"] is not None:
            updates["discount"] = encrypt_data(updates["discount"])
        if "shipping" in updates and updates["shipping"] is not None:
            updates["shipping"] = encrypt_data(updates["shipping"])
        if "grand_total" in updates and updates["grand_total"] is not None:
            updates["grand_total"] = encrypt_data(updates["grand_total"])
        if "status" in updates and updates["status"] is not None:
            updates["status"] = encrypt_data(updates["status"])
        if "sale_type" in updates and updates["sale_type"] is not None:
            updates["sale_type"] = encrypt_data(updates["sale_type"])
        if "notes" in updates and updates["notes"] is not None:
            updates["notes"] = encrypt_data(updates["notes"])
        if "reason" in updates and updates["reason"] is not None:
            updates["reason"] = encrypt_data(updates["reason"])

        return super().update(sale_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, sale_id, business_id):
        """
        Delete a sale by _id and business_id (business-scoped).
        NOTE: For a real POS you may prefer 'soft delete' (Voided) rather than removal.
        """
        try:
            sale_id_obj = ObjectId(sale_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(sale_id_obj, business_id_obj)

#-------------------------SALE MODEL--------------------------------------

class Discount(BaseModel):
    """
    Enhanced Discount model for POS sales.
    Supports product-level, category-level, and cart-level discounts.
    """

    collection_name = "discounts"

    # Discount types
    TYPE_PERCENTAGE = "percentage"
    TYPE_FIXED = "fixed_amount"
    TYPE_BUY_X_GET_Y = "buy_x_get_y"

    # Discount scope
    SCOPE_PRODUCT = "product"
    SCOPE_CATEGORY = "category"
    SCOPE_CART = "cart"

    # Status
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_EXPIRED = "Expired"

    # Fields to decrypt when reading
    FIELDS_TO_DECRYPT = [
        "name",
        "code",
        "location",
        "discount_type",
        "discount_amount",
        "start_date",
        "end_date",
        "selling_price_group_id",
        "status",
        "scope",
        "minimum_purchase",
    ]

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        admin_id,
        name,
        discount_type,
        discount_amount,
        # Product/Category targeting
        product_ids=None,
        category_names=None,
        # Scope
        scope="cart",
        # Coupon code
        code=None,
        # Location/Outlet
        location=None,
        outlet_ids=None,
        # Validation rules
        minimum_purchase=None,
        maximum_discount=None,
        # Date range
        start_date=None,
        end_date=None,
        # Usage limits
        max_uses=None,
        max_uses_per_customer=None,
        current_uses=0,
        # Priority & groups
        priority=None,
        selling_price_group_id=None,
        apply_in_customer_groups=0,
        # Status
        status="Active",
        # Timestamps
        created_at=None,
        updated_at=None,
        **kwargs
    ):
        """
        Initialize enhanced Discount model.
        
        Args:
            business_id: Business ObjectId or string (required)
            user_id: User string ID (required)
            user__id: User ObjectId (required)
            name: Discount name (required)
            discount_type: "percentage" or "fixed_amount" (required)
            discount_amount: Discount value (required)
            product_ids: List of product IDs (for product-level discounts)
            category_names: List of category names (for category-level discounts)
            scope: "product", "category", or "cart"
            code: Coupon code for customers to enter
            location: Location/outlet name
            outlet_ids: List of outlet IDs where discount applies
            minimum_purchase: Minimum purchase amount required
            maximum_discount: Maximum discount amount (cap)
            start_date: When discount becomes active
            end_date: When discount expires
            max_uses: Total usage limit
            max_uses_per_customer: Per-customer usage limit
            current_uses: Current usage count
            priority: Priority level (higher = applied first)
            selling_price_group_id: Legacy price group ID
            apply_in_customer_groups: Legacy customer group flag
            status: "Active", "Inactive", or "Expired"
        """
        
        super().__init__(
            business_id=business_id,
            user_id=user_id,
            user__id=user__id,
            admin_id=admin_id,
            **kwargs
        )
        
        # ✅ Use helper method to normalize ID lists
        self.product_ids = self._normalize_id_list(product_ids)
        self.outlet_ids = self._normalize_id_list(outlet_ids)


        # Category names (plain strings, not encrypted)
        self.category_names = category_names or []

        # Core fields - ENCRYPTED
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        
        self.discount_type = encrypt_data(discount_type)
        self.discount_amount = encrypt_data(str(discount_amount))
        self.scope = encrypt_data(scope)

        # Coupon code - ENCRYPTED (sensitive)
        self.code = encrypt_data(code.upper()) if code else None
        self.hashed_code = hash_data(code.upper()) if code else None

        # Location - ENCRYPTED
        self.location = encrypt_data(location) if location else None

        # Validation rules - ENCRYPTED
        self.minimum_purchase = encrypt_data(str(minimum_purchase)) if minimum_purchase else None
        self.maximum_discount = encrypt_data(str(maximum_discount)) if maximum_discount else None

        # Date range - ENCRYPTED
        self.start_date = encrypt_data(start_date) if start_date else None
        self.end_date = encrypt_data(end_date) if end_date else None

        # Usage limits - PLAIN (for quick queries)
        self.max_uses = int(max_uses) if max_uses else None
        self.max_uses_per_customer = int(max_uses_per_customer) if max_uses_per_customer else None
        self.current_uses = int(current_uses)

        # Priority - PLAIN
        self.priority = int(priority) if priority else 0

        # Legacy fields - ENCRYPTED
        self.selling_price_group_id = encrypt_data(selling_price_group_id) if selling_price_group_id else None
        self.apply_in_customer_groups = int(apply_in_customer_groups)

        # Status - ENCRYPTED
        self.status = encrypt_data(status)
        self.hashed_status = hash_data(status)

        # Timestamps
        self.created_at = created_at or datetime.utcnow()
        self.updated_at = updated_at or datetime.utcnow()

    def to_dict(self):
        """Convert discount to dictionary for MongoDB insertion."""
        discount_dict = super().to_dict()
        discount_dict.update({
            "name": self.name,
            "hashed_name": self.hashed_name,
            "discount_type": self.discount_type,
            "discount_amount": self.discount_amount,
            "scope": self.scope,
            
            # Product/Category targeting
            "product_ids": self.product_ids,
            "category_names": self.category_names,
            
            # Coupon code
            "code": self.code,
            "hashed_code": self.hashed_code,
            
            # Location
            "location": self.location,
            "outlet_ids": self.outlet_ids,
            
            # Validation rules
            "minimum_purchase": self.minimum_purchase,
            "maximum_discount": self.maximum_discount,
            
            # Date range
            "start_date": self.start_date,
            "end_date": self.end_date,
            
            # Usage limits
            "max_uses": self.max_uses,
            "max_uses_per_customer": self.max_uses_per_customer,
            "current_uses": self.current_uses,
            
            # Priority
            "priority": self.priority,
            
            # Legacy fields
            "selling_price_group_id": self.selling_price_group_id,
            "apply_in_customer_groups": self.apply_in_customer_groups,
            
            # Status
            "status": self.status,
            
            # Timestamps
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return discount_dict

    # ---------------- INTERNAL HELPER ---------------- #
    @staticmethod
    def _normalize_id_list(id_list):
        """
        Normalize various formats of ID lists to ObjectId list.
        
        Args:
            id_list: Can be:
                - List of strings: ["id1", "id2"]
                - List of ObjectIds: [ObjectId(...), ObjectId(...)]
                - JSON string: '["id1", "id2"]'
                - None or empty
                
        Returns:
            List of ObjectId objects
        """
        if not id_list:
            return []
        
        # If it's a string, try to parse as JSON
        import json
        if isinstance(id_list, str):
            try:
                id_list = json.loads(id_list)
            except (json.JSONDecodeError, ValueError):
                Log.warning(f"Failed to parse ID list from string: {id_list}")
                return []
        
        # If it's not a list at this point, wrap it
        if not isinstance(id_list, list):
            id_list = [id_list]
        
        # Convert all to ObjectId
        result = []
        for item in id_list:
            try:
                if isinstance(item, ObjectId):
                    result.append(item)
                elif isinstance(item, str) and item.strip():
                    result.append(ObjectId(item))
            except InvalidId as e:
                Log.warning(f"Invalid ObjectId: {item} - {str(e)}")
                continue
        
        return result
    
    @staticmethod
    def _normalize_discount_doc(discount: dict) -> dict:
        """Normalize ObjectId fields and decrypt data."""
        if not discount:
            return None

        # Normalize IDs
        discount["_id"] = str(discount["_id"])
        discount["business_id"] = str(discount["business_id"])
        if discount.get("user__id"):
            discount["user__id"] = str(discount["user__id"])
        if discount.get("user_id"):
            discount["user_id"] = str(discount["user_id"])
        if discount.get("admin_id"):
            discount["admin_id"] = str(discount["admin_id"])

        # Normalize product_ids
        if "product_ids" in discount and isinstance(discount["product_ids"], list):
            discount["product_ids"] = [str(pid) for pid in discount["product_ids"]]

        # Normalize outlet_ids
        if "outlet_ids" in discount and isinstance(discount["outlet_ids"], list):
            discount["outlet_ids"] = [str(oid) for oid in discount["outlet_ids"]]

        # Decrypt fields
        for field in Discount.FIELDS_TO_DECRYPT:
            if field in discount and discount[field] is not None:
                discount[field] = decrypt_data(discount[field])

        # Convert numeric strings back to numbers
        if discount.get("discount_amount"):
            try:
                discount["discount_amount"] = float(discount["discount_amount"])
            except (ValueError, TypeError):
                pass

        if discount.get("minimum_purchase"):
            try:
                discount["minimum_purchase"] = float(discount["minimum_purchase"])
            except (ValueError, TypeError):
                pass

        if discount.get("maximum_discount"):
            try:
                discount["maximum_discount"] = float(discount["maximum_discount"])
            except (ValueError, TypeError):
                pass

        # Remove internal fields
        discount.pop("hashed_name", None)
        discount.pop("hashed_code", None)
        discount.pop("agent_id", None)
        discount.pop("hashed_status", None)

        return discount

    # ---------------- QUERIES ---------------- #

    @classmethod
    def get_by_id(cls, discount_id, business_id):
        """
        Retrieve discount by ID (business-scoped).
        
        Args:
            discount_id: Discount ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Normalized discount dict or None
        """
        log_tag = f"[discount.py][Discount][get_by_id][{discount_id}][{business_id}]"

        try:
            discount_id_obj = ObjectId(discount_id) if not isinstance(discount_id, ObjectId) else discount_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            data = super().get_by_id(discount_id_obj, business_id_obj)

            if not data:
                Log.error(f"{log_tag} Discount not found")
                return None

            discount = cls._normalize_discount_doc(data)
            Log.info(f"{log_tag} Discount retrieved successfully")
            return discount

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_discount_by_product_id(cls, business_id, product_id, outlet_id=None):
        """
        Get an active, valid discount that applies to a specific product_id.

        Args:
            business_id: Business ObjectId or string
            product_id: Product ObjectId or string (must be present in discount.product_ids)
            outlet_id: Optional outlet ID to check if discount applies

        Returns:
            Normalized discount dict or None
        """
        log_tag = f"[discount.py][Discount][get_discount_by_product_id][{business_id}][{product_id}]"

        try:
            # Normalise IDs
            business_obj_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            product_obj_id = ObjectId(product_id) if not isinstance(product_id, ObjectId) else product_id
            outlet_obj_id = (
                ObjectId(outlet_id) if outlet_id and not isinstance(outlet_id, ObjectId)
                else outlet_id
            )

            collection = db.get_collection(cls.collection_name)

            # Base query: discount that applies to this business + product
            query = {
                "business_id": business_obj_id,
                "product_ids": product_obj_id,  # product_ids is an array of ObjectIds
            }

            # Outlet filter (global or specific outlet)
            if outlet_obj_id:
                query["$or"] = [
                    {"outlet_ids": []},          # applies to all outlets
                    {"outlet_ids": outlet_obj_id}  # or specifically this outlet
                ]

            discount = collection.find_one(query)

            if not discount:
                Log.info(f"{log_tag} No discount found for product_id")
                return None

            # ---------------------------
            # Validate ACTIVE status
            # ---------------------------
            status = decrypt_data(discount.get("status"))
            if status != cls.STATUS_ACTIVE:
                Log.info(f"{log_tag} Discount found but not active (status={status})")
                return None

            now = datetime.utcnow()

            # Start date check
            if discount.get("start_date"):
                start_date_str = decrypt_data(discount["start_date"])
                if start_date_str:
                    start_date = datetime.fromisoformat(start_date_str)
                    if now < start_date:
                        Log.info(f"{log_tag} Discount not yet started")
                        return None

            # End date check
            if discount.get("end_date"):
                end_date_str = decrypt_data(discount["end_date"])
                if end_date_str:
                    end_date = datetime.fromisoformat(end_date_str)
                    if now > end_date:
                        Log.info(f"{log_tag} Discount expired")
                        return None

            # Usage limit check
            if discount.get("max_uses"):
                if discount.get("current_uses", 0) >= discount["max_uses"]:
                    Log.info(f"{log_tag} Discount usage limit reached")
                    return None

            # Normalise before returning
            normalized = cls._normalize_discount_doc(discount)
            Log.info(f"{log_tag} Discount for product_id retrieved successfully")
            return normalized

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_by_code(cls, business_id, code, outlet_id=None):
        """
        Get discount by coupon code.
        
        Args:
            business_id: Business ObjectId or string
            code: Discount code string
            outlet_id: Optional outlet ID to check if discount applies
            
        Returns:
            Normalized discount dict or None
        """
        log_tag = f"[discount.py][Discount][get_by_code][{business_id}][{code}]"

        try:
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            collection = db.get_collection(cls.collection_name)

            # Hash the code for lookup
            hashed_code = hash_data(code)

            query = {
                "business_id": business_id_obj,
                "hashed_code": hashed_code
            }

            # Filter by outlet if specified
            if outlet_id:
                outlet_id_obj = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
                query["$or"] = [
                    {"outlet_ids": []},  # Applies to all outlets
                    {"outlet_ids": outlet_id_obj}  # Applies to this outlet
                ]

            discount = collection.find_one(query)

            if not discount:
                Log.info(f"{log_tag} Discount not found")
                return None

            # Check if active
            status = decrypt_data(discount.get("status"))
            if status != cls.STATUS_ACTIVE:
                Log.info(f"{log_tag} Discount is not active")
                return None

            # Check date range
            now = datetime.utcnow()
            
            if discount.get("start_date"):
                start_date_str = decrypt_data(discount["start_date"])
                start_date = datetime.fromisoformat(start_date_str) if start_date_str else None
                if start_date and now < start_date:
                    Log.info(f"{log_tag} Discount not started yet")
                    return None

            if discount.get("end_date"):
                end_date_str = decrypt_data(discount["end_date"])
                end_date = datetime.fromisoformat(end_date_str) if end_date_str else None
                if end_date and now > end_date:
                    Log.info(f"{log_tag} Discount expired")
                    return None

            # Check usage limits
            if discount.get("max_uses"):
                if discount["current_uses"] >= discount["max_uses"]:
                    Log.info(f"{log_tag} Discount usage limit reached")
                    return None

            discount = cls._normalize_discount_doc(discount)
            Log.info(f"{log_tag} Discount retrieved successfully")
            return discount

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None, status=None):
        """
        Retrieve discounts for a business with pagination.
        
        Args:
            business_id: Business ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            status: Optional status filter
            
        Returns:
            Dict with paginated discounts
        """
        log_tag = f"[discount.py][Discount][get_by_business_id][{business_id}]"

        try:
            payload = super().get_by_business_id(
                business_id=business_id,
                page=page,
                per_page=per_page,
            )

            processed = []

            for d in payload.get("items", []):
                # Filter by status if specified
                if status:
                    d_status = decrypt_data(d.get("status"))
                    if d_status != status:
                        continue

                discount = cls._normalize_discount_doc(d)
                processed.append(discount)

            payload["discounts"] = processed
            payload.pop("items", None)

            Log.info(f"{log_tag} Retrieved {len(processed)} discounts")
            return payload

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "discounts": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50,
            }

    @classmethod
    def increment_usage(cls, discount_id, business_id):
        """
        Increment the usage count for a discount.
        
        Args:
            discount_id: Discount ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Bool - success status
        """
        log_tag = f"[discount.py][Discount][increment_usage][{discount_id}]"

        try:
            discount_id_obj = ObjectId(discount_id) if not isinstance(discount_id, ObjectId) else discount_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            collection = db.get_collection(cls.collection_name)

            result = collection.update_one(
                {
                    "_id": discount_id_obj,
                    "business_id": business_id_obj
                },
                {
                    "$inc": {"current_uses": 1},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )

            if result.modified_count > 0:
                Log.info(f"{log_tag} Usage count incremented")
                return True
            else:
                Log.error(f"{log_tag} Failed to increment usage count")
                return False

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False

    @classmethod
    def update(cls, discount_id, **updates):
        """
        Update discount information.
        
        Args:
            discount_id: Discount ObjectId or string
            **updates: Fields to update
            
        Returns:
            Bool - success status
        """
        updates["updated_at"] = datetime.utcnow()
        
        business_id = updates.get("business_id")

        # Encrypt fields
        if "name" in updates and updates["name"]:
            updates["name"] = encrypt_data(updates["name"])
            updates["hashed_name"] = hash_data(updates["name"])

        if "code" in updates and updates["code"]:
            code_upper = updates["code"].upper()
            updates["code"] = encrypt_data(code_upper)
            updates["hashed_code"] = hash_data(code_upper)

        if "discount_type" in updates and updates["discount_type"]:
            updates["discount_type"] = encrypt_data(updates["discount_type"])

        if "discount_amount" in updates and updates["discount_amount"] is not None:
            updates["discount_amount"] = encrypt_data(str(updates["discount_amount"]))

        if "scope" in updates and updates["scope"]:
            updates["scope"] = encrypt_data(updates["scope"])

        if "location" in updates:
            updates["location"] = encrypt_data(updates["location"]) if updates["location"] else None

        if "minimum_purchase" in updates:
            updates["minimum_purchase"] = encrypt_data(str(updates["minimum_purchase"])) if updates["minimum_purchase"] else None

        if "maximum_discount" in updates:
            updates["maximum_discount"] = encrypt_data(str(updates["maximum_discount"])) if updates["maximum_discount"] else None

        if "start_date" in updates:
            updates["start_date"] = encrypt_data(updates["start_date"]) if updates["start_date"] else None

        if "end_date" in updates:
            updates["end_date"] = encrypt_data(updates["end_date"]) if updates["end_date"] else None

        if "selling_price_group_id" in updates:
            spg = updates["selling_price_group_id"]
            updates["selling_price_group_id"] = encrypt_data(spg) if spg else None

        if "status" in updates and updates["status"]:
            updates["status"] = encrypt_data(updates["status"])

        # Convert ID lists
        if "product_ids" in updates and isinstance(updates["product_ids"], list):
            updates["product_ids"] = [
                ObjectId(pid) if isinstance(pid, str) else pid
                for pid in updates["product_ids"]
            ]

        if "outlet_ids" in updates and isinstance(updates["outlet_ids"], list):
            updates["outlet_ids"] = [
                ObjectId(oid) if isinstance(oid, str) else oid
                for oid in updates["outlet_ids"]
            ]

        return super().update(discount_id, business_id, **updates)

    @classmethod
    def delete(cls, discount_id, business_id):
        """
        Delete discount (business-scoped).
        
        Args:
            discount_id: Discount ObjectId or string
            business_id: Business ObjectId or string
            
        Returns:
            Bool - success status
        """
        try:
            discount_id_obj = ObjectId(discount_id) if not isinstance(discount_id, ObjectId) else discount_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            return super().delete(discount_id_obj, business_id_obj)

        except Exception:
            return False

    @classmethod
    def create_indexes(cls):
        """Create database indexes for optimal query performance."""
        log_tag = f"[discount.py][Discount][create_indexes]"

        try:
            collection = db.get_collection(cls.collection_name)

            # Core indexes
            collection.create_index([("business_id", 1), ("created_at", -1)])
            collection.create_index([("business_id", 1), ("hashed_code", 1)])
            collection.create_index([("business_id", 1), ("current_uses", 1)])
            collection.create_index([("business_id", 1), ("priority", -1)])

            Log.info(f"{log_tag} Indexes created successfully")
            return True

        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False
#-------------------------DISCOUNT MODEL--------------------------------------

class SellingPriceGroup(BaseModel):
    """
    A SellingPriceGroup represents a group of products with a specific price, discount,
    or offers in a business, including details like name, description, status, and timestamps.
    """

    collection_name = "selling_price_groups"  # Set the collection name for selling price groups

    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        name,
        description=None,
        status="Active",
    ):
        # Call BaseModel with raw values
        super().__init__(
            business_id,
            user_id,
            user__id,
            name=name,
            description=description,
            status=status,
        )

        # Encrypt fields before saving them to the database
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.description = encrypt_data(description) if description else None
        self.status = encrypt_data(status) if status is not None else None

        # Timestamps
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def to_dict(self):
        """
        Convert the SellingPriceGroup object to a dictionary representation.
        """
        selling_price_group_dict = super().to_dict()
        selling_price_group_dict.update(
            {
                "name": self.name,
                "description": self.description,
                "status": self.status,
                "hashed_name": self.hashed_name,
                "created_at": self.created_at,
                "updated_at": self.updated_at,
            }
        )
        return selling_price_group_dict

    # -------------------------------------------------
    # GET BY ID (business-scoped)
    # -------------------------------------------------
    @classmethod
    def get_by_id(cls, selling_price_group_id, business_id):
        """
        Retrieve a SellingPriceGroup by _id and business_id (business-scoped).
        Mirrors Discount.get_by_id style.
        """
        try:
            spg_id_obj = ObjectId(selling_price_group_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return None  # Invalid id / business_id format

        # Use BaseModel.get_by_id(id, business_id)
        data = super().get_by_id(spg_id_obj, business_id_obj)
        if not data:
            return None

        # Normalise IDs
        if "_id" in data:
            data["_id"] = str(data["_id"])
        if "business_id" in data:
            data["business_id"] = str(data["business_id"])
        if "user__id" in data:
            data["user__id"] = str(data["user__id"])
        if "user_id" in data and data["user_id"] is not None:
            data["user_id"] = str(data["user_id"])

        # Decrypt fields
        data["name"] = decrypt_data(data["name"]) if data.get("name") else None
        data["description"] = (
            decrypt_data(data["description"]) if data.get("description") else None
        )
        data["status"] = decrypt_data(data["status"]) if data.get("status") else None

        # Timestamps kept as-is
        data["created_at"] = data.get("created_at")
        data["updated_at"] = data.get("updated_at")

        # Remove internal fields
        data.pop("hashed_name", None)
        data.pop("agent_id", None)
        data.pop("admin_id", None)

        return data

    # -------------------------------------------------
    # GET BY BUSINESS ID (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None):
        """
        Retrieve SellingPriceGroups for a business (paginated), decrypting fields.
        Mirrors Discount.get_by_business_id behaviour.
        """
        payload = super().get_by_business_id(
            business_id=business_id,
            page=page,
            per_page=per_page,
        )

        processed = []

        for g in payload.get("items", []):
            # Normalise IDs
            if "_id" in g:
                g["_id"] = str(g["_id"])
            if "business_id" in g:
                g["business_id"] = str(g["business_id"])
            if "user__id" in g:
                g["user__id"] = str(g["user__id"])
            if "user_id" in g and g["user_id"] is not None:
                g["user_id"] = str(g["user_id"])

            # Decrypt fields
            g["name"] = decrypt_data(g["name"]) if g.get("name") else None
            g["description"] = (
                decrypt_data(g["description"]) if g.get("description") else None
            )
            g["status"] = decrypt_data(g["status"]) if g.get("status") else None

            # Timestamps
            g["created_at"] = g.get("created_at")
            g["updated_at"] = g.get("updated_at")

            # Remove internal fields
            g.pop("hashed_name", None)
            g.pop("agent_id", None)
            g.pop("admin_id", None)

            processed.append(g)

        payload["selling_price_groups"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # GET BY USER + BUSINESS (with pagination)
    # -------------------------------------------------
    @classmethod
    def get_by_user__id_and_business_id(cls, user__id, business_id, page=None, per_page=None):
        """
        Retrieve SellingPriceGroups created by a specific user within a business (paginated).
        Mirrors Discount.get_by_user__id_and_business_id behaviour.
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
            if "business_id" in g:
                g["business_id"] = str(g["business_id"])
            if "user__id" in g:
                g["user__id"] = str(g["user__id"])
            if "user_id" in g and g["user_id"] is not None:
                g["user_id"] = str(g["user_id"])

            # Decrypt fields
            g["name"] = decrypt_data(g["name"]) if g.get("name") else None
            g["description"] = (
                decrypt_data(g["description"]) if g.get("description") else None
            )
            g["status"] = decrypt_data(g["status"]) if g.get("status") else None

            # Timestamps
            g["created_at"] = g.get("created_at")
            g["updated_at"] = g.get("updated_at")

            # Remove internal fields
            g.pop("hashed_name", None)
            g.pop("agent_id", None)
            g.pop("admin_id", None)

            processed.append(g)

        payload["selling_price_groups"] = processed
        payload.pop("items", None)
        return payload

    # -------------------------------------------------
    # UPDATE
    # -------------------------------------------------
    @classmethod
    def update(cls, selling_price_group_id, **updates):
        """
        Update a SellingPriceGroup's information by selling_price_group_id.
        Encrypts updated fields and refreshes updated_at.
        """
        updates["updated_at"] = datetime.now()

        # Encrypt fields if they are being updated
        if "name" in updates:
            plain_name = updates["name"]
            updates["name"] = encrypt_data(plain_name)
            updates["hashed_name"] = hash_data(plain_name)

        if "description" in updates:
            desc = updates["description"]
            updates["description"] = encrypt_data(desc) if desc else None

        if "status" in updates:
            status_val = updates["status"]
            updates["status"] = encrypt_data(status_val) if status_val is not None else None

        return super().update(selling_price_group_id, **updates)

    # -------------------------------------------------
    # DELETE (business-scoped)
    # -------------------------------------------------
    @classmethod
    def delete(cls, selling_price_group_id, business_id):
        """
        Delete a SellingPriceGroup by _id and business_id (business-scoped).
        Mirrors Discount.delete behaviour.
        """
        try:
            spg_id_obj = ObjectId(selling_price_group_id)
            business_id_obj = ObjectId(business_id)
        except Exception:
            return False

        return super().delete(spg_id_obj, business_id_obj)
#-------------------------SELLING PRICE GROUP--------------------------------------

#-------------------------SELLING PRICE GROUP--------------------------------------

#-------------------------PACKAGE--------------------------------------
class Package(BaseModel):
    """
    A Package represents a subscription package for a business, including details such as the name,
    number of locations, products, pricing interval, trial days, and various other settings.
    """
    
    collection_name = "packages"  # Set the collection name for packages

    def __init__(self, business_id, user_id, name, number_of_locations, number_of_products, price_interval,
                 trial_days=None, package_description=None, number_of_active_users=None, number_of_choices=None,
                 interval=None, price=0.0, sort_order=1, private_superadmin_only=0, enable_custom_subscription_link=0,
                 one_time_only_subscription=0, mark_as_popular=0, created_at=None, updated_at=None):

        super().__init__(business_id, user_id, name=name, number_of_locations=number_of_locations,
                         number_of_products=number_of_products, price_interval=price_interval, 
                         trial_days=trial_days, package_description=package_description, 
                         number_of_active_users=number_of_active_users, number_of_choices=number_of_choices, 
                         interval=interval, price=price, sort_order=sort_order, 
                         private_superadmin_only=private_superadmin_only, 
                         enable_custom_subscription_link=enable_custom_subscription_link,
                         one_time_only_subscription=one_time_only_subscription, 
                         mark_as_popular=mark_as_popular, created_at=created_at, updated_at=updated_at)
        
        # Encrypt sensitive fields
        self.name = encrypt_data(name)
        self.package_description = encrypt_data(package_description) if package_description else None
        self.price_interval = encrypt_data(price_interval)
        self.price = encrypt_data(price)
        self.trial_days = trial_days
        self.number_of_locations = number_of_locations
        self.number_of_products = number_of_products
        self.number_of_active_users = number_of_active_users
        self.number_of_choices = number_of_choices
        self.interval = interval
        self.sort_order = sort_order
        self.private_superadmin_only = private_superadmin_only
        self.enable_custom_subscription_link = enable_custom_subscription_link
        self.one_time_only_subscription = one_time_only_subscription
        self.mark_as_popular = mark_as_popular

        # Add created and updated timestamps
        self.created_at = created_at or datetime.now()
        self.updated_at = updated_at or datetime.now()

    def to_dict(self):
        """
        Convert the package object to a dictionary representation.
        """
        package_dict = super().to_dict()
        package_dict.update({
            "name": self.name,
            "number_of_locations": self.number_of_locations,
            "number_of_products": self.number_of_products,
            "price_interval": self.price_interval,
            "trial_days": self.trial_days,
            "package_description": self.package_description,
            "number_of_active_users": self.number_of_active_users,
            "number_of_choices": self.number_of_choices,
            "interval": self.interval,
            "price": self.price,
            "sort_order": self.sort_order,
            "private_superadmin_only": self.private_superadmin_only,
            "enable_custom_subscription_link": self.enable_custom_subscription_link,
            "one_time_only_subscription": self.one_time_only_subscription,
            "mark_as_popular": self.mark_as_popular,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        })
        return package_dict

    @classmethod
    def get_by_id(cls, package_id):
        """
        Retrieve a package by package_id, decrypting all fields.
        """
        try:
            package_id_obj = ObjectId(package_id)
        except Exception as e:
            return None  # Return None if conversion fails (invalid _id format)

        data = db[cls.collection_name].find_one({"_id": package_id_obj})

        if not data:
            return None  # Package not found

        data["_id"] = str(data["_id"])
        data["business_id"] = str(data["business_id"])

        # Decrypt all fields before returning them
        data["name"] = decrypt_data(data["name"])
        data["package_description"] = decrypt_data(data["package_description"]) if data.get("package_description") else None
        data["price_interval"] = decrypt_data(data["price_interval"])
        data["price"] = decrypt_data(data["price"])
        data["trial_days"] = data.get("trial_days")
        data["number_of_locations"] = data.get("number_of_locations")
        data["number_of_products"] = data.get("number_of_products")
        data["number_of_active_users"] = data.get("number_of_active_users")
        data["number_of_choices"] = data.get("number_of_choices")
        data["interval"] = data.get("interval")
        data["sort_order"] = data.get("sort_order")
        data["private_superadmin_only"] = data.get("private_superadmin_only")
        data["enable_custom_subscription_link"] = data.get("enable_custom_subscription_link")
        data["one_time_only_subscription"] = data.get("one_time_only_subscription")
        data["mark_as_popular"] = data.get("mark_as_popular")

        data.pop("hashed_name", None)

        return data
    
    @classmethod
    def get_packages_by_business_id(cls, business_id):
        """
        Retrieve packages by business_id, decrypting fields.
        """
        if isinstance(business_id, str):
            try:
                business_id = ObjectId(business_id)
            except Exception as e:
                raise ValueError(f"Invalid business_id format: {business_id}") from e

        packages_cursor = db[cls.collection_name].find({"business_id": business_id})

        result = []
        for package in packages_cursor:
            package["business_id"] = str(package["business_id"])
            package["name"] = decrypt_data(package["name"])
            package["package_description"] = decrypt_data(package["package_description"]) if package.get("package_description") else None
            package["price_interval"] = decrypt_data(package["price_interval"])
            package["price"] = decrypt_data(package["price"])

            package["_id"] = str(package["_id"])
            package.pop("hashed_name", None)

            result.append(package)

        return result

    @classmethod
    def update_package(cls, package_id, **updates):
        """
        Update a package's information by package_id.
        """
        if "name" in updates:
            updates["name"] = encrypt_data(updates["name"])
        if "price_interval" in updates:
            updates["price_interval"] = encrypt_data(updates["price_interval"])
        if "price" in updates:
            updates["price"] = encrypt_data(updates["price"])
        if "package_description" in updates:
            updates["package_description"] = encrypt_data(updates["package_description"]) if updates["package_description"] else None
        if "trial_days" in updates:
            updates["trial_days"] = updates["trial_days"]
        if "number_of_locations" in updates:
            updates["number_of_locations"] = updates["number_of_locations"]
        if "number_of_products" in updates:
            updates["number_of_products"] = updates["number_of_products"]
        if "number_of_active_users" in updates:
            updates["number_of_active_users"] = updates["number_of_active_users"]
        if "number_of_choices" in updates:
            updates["number_of_choices"] = updates["number_of_choices"]
        if "interval" in updates:
            updates["interval"] = updates["interval"]
        if "sort_order" in updates:
            updates["sort_order"] = updates["sort_order"]
        if "private_superadmin_only" in updates:
            updates["private_superadmin_only"] = updates["private_superadmin_only"]
        if "enable_custom_subscription_link" in updates:
            updates["enable_custom_subscription_link"] = updates["enable_custom_subscription_link"]
        if "one_time_only_subscription" in updates:
            updates["one_time_only_subscription"] = updates["one_time_only_subscription"]
        if "mark_as_popular" in updates:
            updates["mark_as_popular"] = updates["mark_as_popular"]

        result = db[cls.collection_name].update_one({"_id": ObjectId(package_id)}, {"$set": updates})

        return result.modified_count > 0

    @classmethod
    def delete(cls, package_id):
        """
        Delete a package by package_id.
        """
        return super().delete(package_id)
#-------------------------PACKAGE--------------------------------------