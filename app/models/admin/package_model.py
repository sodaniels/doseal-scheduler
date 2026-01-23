# models/admin/package_model.py

from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class Package(BaseModel):
    """
    Subscription package/plan model.
    Defines features, limits, and pricing for different subscription tiers.
    """
    
    collection_name = "packages"
    
    # Package Tiers
    TIER_FREE = "Free"
    TIER_STARTER = "Starter"
    TIER_PROFESSIONAL = "Professional"
    TIER_ENTERPRISE = "Enterprise"
    TIER_CUSTOM = "Custom"
    
    # Billing Periods
    PERIOD_MONTHLY = "monthly"
    PERIOD_QUARTERLY = "quarterly"
    PERIOD_YEARLY = "yearly"
    PERIOD_LIFETIME = "lifetime"
    
    # Status
    STATUS_ACTIVE = "Active"
    STATUS_INACTIVE = "Inactive"
    STATUS_DEPRECATED = "Deprecated"
    
    # Fields to decrypt
    FIELDS_TO_DECRYPT = [
        "name",
        "description",
        "tier",
        "billing_period",
        "currency",
        "status",
        "price",       # 👈 now decrypted
        "setup_fee",   # 👈 now decrypted
    ]
    
    def __init__(
        self,
        name,
        tier,
        billing_period,
        price,
        currency="USD",
        # Feature limits
        max_users=None,
        max_outlets=None,
        max_products=None,
        max_transactions_per_month=None,
        storage_limit_gb=None,
        # Feature flags
        features=None,
        # Pricing
        setup_fee=0.0,
        trial_days=0,
        # Metadata
        description=None,
        is_popular=False,
        display_order=0,
        status=STATUS_ACTIVE,
        # Internal
        user_id=None,
        user__id=None,
        business_id=None,
        **kwargs
    ):
        """
        Initialize a subscription package.
        
        Args:
            name: Package name (e.g., "Professional Plan")
            tier: Package tier (Free, Starter, Professional, Enterprise, Custom)
            billing_period: Billing cycle (monthly, quarterly, yearly, lifetime)
            price: Price for the billing period
            currency: Currency code (default USD)
            max_users: Maximum number of users allowed
            max_outlets: Maximum number of outlets/locations
            max_products: Maximum number of products
            max_transactions_per_month: Monthly transaction limit
            storage_limit_gb: Storage limit in GB
            features: Dict of feature flags and values
            setup_fee: One-time setup fee
            trial_days: Free trial period in days
            description: Package description
            is_popular: Mark as popular/recommended
            display_order: Display order (lower = shown first)
            status: Package status
        """
        super().__init__(
            user__id=user__id,
            user_id=user_id,
            business_id=business_id,
            **kwargs
        )
        
        self.business_id = ObjectId(business_id)
        
        # Core fields - ENCRYPTED
        self.name = encrypt_data(name)
        self.hashed_name = hash_data(name)
        self.description = encrypt_data(description) if description else None
        self.tier = encrypt_data(tier)
        self.billing_period = encrypt_data(billing_period)
        self.currency = encrypt_data(currency)
        
        self.status = encrypt_data(status)
        self.hashed_status = hash_data(status)
        
        # Pricing - ENCRYPTED (sensitive)
        self.price = encrypt_data(str(price))
        self.setup_fee = encrypt_data(str(setup_fee))
        
        # Limits - PLAIN (for quick queries)
        self.max_users = int(max_users) if max_users else None
        self.max_outlets = int(max_outlets) if max_outlets else None
        self.max_products = int(max_products) if max_products else None
        self.max_transactions_per_month = int(max_transactions_per_month) if max_transactions_per_month else None
        self.storage_limit_gb = float(storage_limit_gb) if storage_limit_gb else None
        
        # Features - PLAIN (JSON object)
        self.features = features or {
            "pos": True,
            "inventory": True,
            "reports": True,
            "multi_outlet": False,
            "api_access": False,
            "custom_branding": False,
            "priority_support": False,
            "advanced_analytics": False,
            "integrations": False,
            "mobile_app": True,
            "web_app": True,
            "backup_restore": True,
            "user_permissions": True,
            "discount_coupons": True,
            "loyalty_program": False,
            "email_notifications": True,
            "sms_notifications": False,
            "whatsapp_notifications": False,
        }
        
        # Trial and display - PLAIN
        self.trial_days = int(trial_days)
        self.is_popular = bool(is_popular)
        self.display_order = int(display_order)
        
        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            "business_id": self.business_id,
            "name": self.name,
            "hashed_name": self.hashed_name,
            "description": self.description,
            "tier": self.tier,
            "billing_period": self.billing_period,
            "price": self.price,
            "currency": self.currency,
            "setup_fee": self.setup_fee,
            "max_users": self.max_users,
            "max_outlets": self.max_outlets,
            "max_products": self.max_products,
            "max_transactions_per_month": self.max_transactions_per_month,
            "storage_limit_gb": self.storage_limit_gb,
            "features": self.features,
            "trial_days": self.trial_days,
            "is_popular": self.is_popular,
            "display_order": self.display_order,
            "status": self.status,
            "hashed_status": self.hashed_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        
        return doc
    
    # ---------------- INTERNAL HELPER ---------------- #
    
    @staticmethod
    def _normalise_package_doc(package: dict) -> dict:
        """Normalise ObjectId fields and decrypt data."""
        if not package:
            return None

        package["_id"] = str(package["_id"])
        package["business_id"] = str(package["business_id"])
        
        # Decrypt fields (now also price & setup_fee)
        for field in Package.FIELDS_TO_DECRYPT:
            if field in package and package[field] is not None:
                package[field] = decrypt_data(package[field])
        
        # Convert price fields back to numbers
        if package.get("price") is not None:
            try:
                package["price"] = float(package["price"])
            except (ValueError, TypeError):
                package["price"] = 0.0
        
        if package.get("setup_fee") is not None:
            try:
                package["setup_fee"] = float(package["setup_fee"])
            except (ValueError, TypeError):
                package["setup_fee"] = 0.0
        
        # Remove internal fields
        package.pop("hashed_name", None)
        package.pop("hashed_status", None)
        
        return package
    
    # ---------------- QUERIES ---------------- #
    
    @classmethod
    def get_by_id(cls, package_id):
        """
        Retrieve a package by ID.
        
        Args:
            package_id: Package ObjectId or string
            
        Returns:
            Normalised package dict or None
        """
        log_tag = f"[package.py][Package][get_by_id][{package_id}]"
        
        try:
            package_id = ObjectId(package_id) if not isinstance(package_id, ObjectId) else package_id
            
            collection = db.get_collection(cls.collection_name)
            package = collection.find_one({"_id": package_id})
            
            if not package:
                Log.error(f"{log_tag} Package not found")
                return None
            
            package = cls._normalise_package_doc(package)
            Log.info(f"{log_tag} Package retrieved successfully")
            return package
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_all_active(cls, page=None, per_page=None):
        """
        Get all active packages.
        
        Args:
            page: Optional page number
            per_page: Optional items per page
            
        Returns:
            Dict with paginated packages
        """
        log_tag = f"[package.py][Package][get_all_active]"
        
        try:
            # Pagination defaults
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50
            
            collection = db.get_collection(cls.collection_name)
            
            # Query active packages (using hashed_status)
            query = {"hashed_status": hash_data(cls.STATUS_ACTIVE)}
            
            total_count = collection.count_documents(query)
            
            cursor = (
                collection.find(query)
                .sort("display_order", 1)  # Sort by display order
                .skip((page - 1) * per_page)
                .limit(per_page)
            )
            
            items = list(cursor)
            packages = [cls._normalise_package_doc(p) for p in items]
            
            total_pages = (total_count + per_page - 1) // per_page
            
            result = {
                "packages": packages,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }
            
            Log.info(f"{log_tag} Retrieved {len(packages)} packages")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "packages": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50,
            }
    
    @classmethod
    def get_by_tier(cls, tier):
        """
        Get packages by tier.
        
        Args:
            tier: Package tier (Free, Starter, etc.)
            
        Returns:
            List of normalised package dicts
        """
        log_tag = f"[package.py][Package][get_by_tier][{tier}]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            packages = list(
                collection.find({
                    "tier": encrypt_data(tier),
                    "hashed_status": hash_data(cls.STATUS_ACTIVE)
                }).sort("price", 1)
            )
            
            packages = [cls._normalise_package_doc(p) for p in packages]
            
            Log.info(f"{log_tag} Retrieved {len(packages)} packages")
            return packages
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []
    
    @classmethod
    def update(cls, package_id, business_id, **updates):
        """
        Update a package.
        
        Args:
            package_id: Package ObjectId or string
            business_id: Business ObjectId or string
            **updates: Fields to update
            
        Returns:
            Bool - success status
        """
        updates["updated_at"] = datetime.utcnow()
        
        # Encrypt fields – be careful to hash the *plaintext*,
        # not the encrypted string.
        if "name" in updates and updates["name"]:
            original_name = updates["name"]
            updates["name"] = encrypt_data(original_name)
            updates["hashed_name"] = hash_data(original_name)
        
        if "description" in updates:
            updates["description"] = (
                encrypt_data(updates["description"])
                if updates["description"]
                else None
            )
        
        if "tier" in updates and updates["tier"]:
            updates["tier"] = encrypt_data(updates["tier"])
        
        if "billing_period" in updates and updates["billing_period"]:
            updates["billing_period"] = encrypt_data(updates["billing_period"])
        
        if "currency" in updates and updates["currency"]:
            updates["currency"] = encrypt_data(updates["currency"])
        
        if "status" in updates and updates["status"]:
            plain_status = updates["status"]
            updates["status"] = encrypt_data(plain_status)
            updates["hashed_status"] = hash_data(plain_status)
        
        if "price" in updates and updates["price"] is not None:
            updates["price"] = encrypt_data(str(updates["price"]))
        
        if "setup_fee" in updates and updates["setup_fee"] is not None:
            updates["setup_fee"] = encrypt_data(str(updates["setup_fee"]))
        
        return super().update(package_id, business_id, **updates)
    
    @classmethod
    def create_indexes(cls):
        """Create database indexes for optimal query performance."""
        log_tag = f"[package.py][Package][create_indexes]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            # Core indexes
            collection.create_index([("status", 1), ("display_order", 1)])
            collection.create_index([("tier", 1), ("price", 1)])
            collection.create_index([("is_popular", 1)])
            collection.create_index([("hashed_name", 1)])
            collection.create_index([("hashed_status", 1)])
            
            Log.info(f"{log_tag} Indexes created successfully")
            return True
            
        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False