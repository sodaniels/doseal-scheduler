# models/sale.py
from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...extensions.db import db
from ...utils.logger import Log


class Sale(BaseModel):
    """
    Enhanced Sale model for comprehensive POS reporting.
    Supports 26+ report types with complete tracking.
    """

    collection_name = "sales"

    # Sale statuses
    STATUS_COMPLETED = "Completed"
    STATUS_PENDING = "Pending"
    STATUS_VOIDED = "Voided"
    STATUS_REFUNDED = "Refunded"
    STATUS_PARTIALLY_REFUNDED = "Partially_Refunded"
    STATUS_FAILED = "Failed"

    # Payment methods
    PAYMENT_CASH = "cash"
    PAYMENT_CREDIT_CARD = "credit_card"
    PAYMENT_DEBIT_CARD = "debit_card"
    PAYMENT_MOBILE_MONEY = "mobile_money"
    PAYMENT_BANK_TRANSFER = "bank_transfer"
    PAYMENT_GIFT_CARD = "gift_card"
    PAYMENT_STORE_CREDIT = "store_credit"

    # Discount types
    DISCOUNT_PERCENTAGE = "percentage"
    DISCOUNT_FIXED = "fixed_amount"
    DISCOUNT_PROMOTIONAL = "promotional"
    DISCOUNT_COUPON = "coupon"
    DISCOUNT_LOYALTY = "loyalty"

    def __init__(
        self,
        business_id,
        outlet_id,
        user_id,
        user__id,
        cart,
        payment_method,
        # Core fields
        cashier_id=None,
        customer_id=None,
        status=STATUS_COMPLETED,
        amount_paid=None,
        # Transaction identifiers
        transaction_number=None,
        receipt_number=None,
        # Discount & promotion
        discount_type=None,
        coupon_code=None,
        promotion_id=None,
        # Refund/void tracking
        refund_reason=None,
        void_reason=None,
        authorized_by=None,
        # Operational tracking
        cash_session_id=None,
        device_id=None,
        # Legacy/compatibility
        reference_note=None,
        agent_id=None,
        admin_id=None,
        # Metadata
        notes=None,
        checksum=None,
        hold_id=None,
        **kwargs
    ):
        """
        Initialize enhanced sale record.

        Args:
            business_id: Business ObjectId or string (required)
            outlet_id: Outlet ObjectId or string (required)
            user_id: User string ID (required)
            user__id: User ObjectId or string (required)
            cart: Dict - enhanced cart structure with lines and totals (required)
            payment_method: String - payment type (required)
            cashier_id: Cashier ObjectId or string (defaults to user__id)
            customer_id: Optional customer ObjectId or string
            status: String - sale status
            amount_paid: Float - amount paid by customer
            transaction_number: Unique transaction identifier
            receipt_number: Receipt/invoice number
            discount_type: Type of discount applied
            coupon_code: Coupon code used
            promotion_id: Promotion ObjectId or string
            refund_reason: Reason for refund (if applicable)
            void_reason: Reason for void (if applicable)
            authorized_by: Manager who authorized void/refund
            cash_session_id: Shift/session ObjectId or string
            device_id: POS device identifier
            reference_note: Additional notes
            notes: General notes
        """
        super().__init__(
            business_id=business_id,
            user__id=user__id,
            user_id=user_id,
            admin_id=admin_id
        )

        # CORE IDENTIFIERS - REQUIRED
        self.business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        self.outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
        self.user__id = ObjectId(user__id) if not isinstance(user__id, ObjectId) else user__id
        
        # Cashier defaults to user if not specified
        if cashier_id:
            self.cashier_id = ObjectId(cashier_id) if not isinstance(cashier_id, ObjectId) else cashier_id
        else:
            self.cashier_id = self.user__id

        # CUSTOMER - OPTIONAL
        self.customer_id = ObjectId(customer_id) if customer_id and not isinstance(customer_id, ObjectId) else customer_id

        # TRANSACTION IDENTIFIERS
        self.transaction_number = transaction_number
        self.receipt_number = receipt_number
        self.user_id = user_id
        
        self.checksum = hash_data(checksum) if checksum else None

        # STATUS & PAYMENT - REQUIRED
        self.status = status
        self.payment_method = payment_method

        # CART - REQUIRED (enhanced structure)
        self.cart = cart

        # FINANCIAL
        grand_total = float(cart.get("totals", {}).get("grand_total", 0))
        self.amount_paid = float(amount_paid) if amount_paid is not None else grand_total
        self.change_amount = max(0.0, self.amount_paid - grand_total)

        # DISCOUNT & PROMOTION - OPTIONAL
        self.discount_type = discount_type
        self.coupon_code = coupon_code
        self.promotion_id = ObjectId(promotion_id) if promotion_id and not isinstance(promotion_id, ObjectId) else promotion_id

        # REFUND/VOID TRACKING - CONDITIONAL
        self.refund_reason = refund_reason
        self.void_reason = void_reason
        self.authorized_by = ObjectId(authorized_by) if authorized_by and not isinstance(authorized_by, ObjectId) else authorized_by

        # OPERATIONAL TRACKING - OPTIONAL
        self.cash_session_id = ObjectId(cash_session_id) if cash_session_id else None
        self.device_id = device_id
        
        self.hold_id = hold_id

        # METADATA
        self.notes = notes or reference_note
        self.reference_note = reference_note  # Keep for backward compatibility

        # LEGACY FIELDS - OPTIONAL
        self.agent_id = ObjectId(agent_id) if agent_id and not isinstance(agent_id, ObjectId) else agent_id
        self.admin_id = ObjectId(admin_id) if admin_id and not isinstance(admin_id, ObjectId) else admin_id

        # TIMESTAMPS
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            # CORE - REQUIRED
            "business_id": self.business_id,
            "outlet_id": self.outlet_id,
            "cashier_id": self.cashier_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "hold_id": self.hold_id,
            "status": self.status,
            "payment_method": self.payment_method,
            
            # CART - REQUIRED
            "cart": self.cart,
            
            # FINANCIAL
            "amount_paid": self.amount_paid,
            "change_amount": self.change_amount,
            
            # TIMESTAMPS
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

        # OPTIONAL FIELDS - Only include if set
        if self.customer_id:
            doc["customer_id"] = self.customer_id
        if self.transaction_number:
            doc["transaction_number"] = self.transaction_number
        if self.receipt_number:
            doc["receipt_number"] = self.receipt_number
        if self.discount_type:
            doc["discount_type"] = self.discount_type
        if self.coupon_code:
            doc["coupon_code"] = self.coupon_code
        if self.promotion_id:
            doc["promotion_id"] = self.promotion_id
        if self.refund_reason:
            doc["refund_reason"] = self.refund_reason
        if self.void_reason:
            doc["void_reason"] = self.void_reason
        if self.authorized_by:
            doc["authorized_by"] = self.authorized_by
        if self.cash_session_id:
            doc["cash_session_id"] = self.cash_session_id
        if self.device_id:
            doc["device_id"] = self.device_id
        if self.notes:
            doc["notes"] = self.notes
        if self.reference_note:
            doc["reference_note"] = self.reference_note
        if self.agent_id:
            doc["agent_id"] = self.agent_id
        if self.admin_id:
            doc["admin_id"] = self.admin_id
        if self.checksum:
            doc["checksum"] = self.checksum

        return doc

    # ---------------- INTERNAL HELPER ---------------- #

    @staticmethod
    def _normalise_sale_doc(sale: dict) -> dict:
        """Normalise ObjectId fields to strings for API responses."""
        if not sale:
            return None

        sale["_id"] = str(sale["_id"])
        
        # Required ObjectIds
        if sale.get("business_id"):
            sale["business_id"] = str(sale["business_id"])
        if sale.get("outlet_id"):
            sale["outlet_id"] = str(sale["outlet_id"])
        if sale.get("cashier_id"):
            sale["cashier_id"] = str(sale["cashier_id"])
        if sale.get("user__id"):
            sale["user__id"] = str(sale["user__id"])
        
        # Optional ObjectIds
        if sale.get("customer_id"):
            sale["customer_id"] = str(sale["customer_id"])
        if sale.get("authorized_by"):
            sale["authorized_by"] = str(sale["authorized_by"])
        if sale.get("promotion_id"):
            sale["promotion_id"] = str(sale["promotion_id"])
        if sale.get("cash_session_id"):
            sale["cash_session_id"] = str(sale["cash_session_id"])
        if sale.get("agent_id"):
            sale["agent_id"] = str(sale["agent_id"])
        if sale.get("admin_id"):
            sale["admin_id"] = str(sale["admin_id"])

        return sale

    # ---------------- QUERIES ---------------- #

    @classmethod
    def get_by_id(cls, sale_id, business_id):
        """
        Retrieve a sale by ID.

        Args:
            sale_id: Sale ObjectId or string
            business_id: Business ObjectId or string

        Returns:
            Normalised sale dict or None
        """
        log_tag = f"[sale.py][Sale][get_by_id][{sale_id}][{business_id}]"

        try:
            sale_id_obj = ObjectId(sale_id) if not isinstance(sale_id, ObjectId) else sale_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            collection = db.get_collection(cls.collection_name)
            sale = collection.find_one({
                "_id": sale_id_obj,
                "business_id": business_id_obj,
            })

            if not sale:
                Log.error(f"{log_tag} Sale not found")
                return None

            sale = cls._normalise_sale_doc(sale)
            Log.info(f"{log_tag} Sale retrieved successfully")
            return sale

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None, status=None, outlet_id=None, start_date=None, end_date=None):
        """
        List sales for a business with optional filtering.

        Args:
            business_id: Business ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            status: Optional status filter
            outlet_id: Optional outlet filter
            start_date: Optional start date filter
            end_date: Optional end date filter

        Returns:
            Dict with paginated sales
        """
        log_tag = f"[sale.py][Sale][get_by_business_id][{business_id}]"

        try:
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            # Pagination defaults
            page = int(page) if page else 1
            per_page = int(per_page) if per_page else 50
            if page < 1:
                page = 1
            if per_page <= 0:
                per_page = 50

            query = {"business_id": business_id_obj}

            if status:
                query["status"] = status

            if outlet_id:
                outlet_id_obj = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
                query["outlet_id"] = outlet_id_obj

            if start_date or end_date:
                date_query = {}
                if start_date:
                    date_query["$gte"] = start_date
                if end_date:
                    date_query["$lte"] = end_date
                query["created_at"] = date_query

            collection = db.get_collection(cls.collection_name)

            total_count = collection.count_documents(query)

            cursor = (
                collection.find(query)
                .sort("created_at", -1)
                .skip((page - 1) * per_page)
                .limit(per_page)
            )

            items = list(cursor)
            sales = [cls._normalise_sale_doc(s) for s in items]

            total_pages = (total_count + per_page - 1) // per_page if per_page else 1

            payload = {
                "sales": sales,
                "total_count": total_count,
                "total_pages": total_pages,
                "current_page": page,
                "per_page": per_page,
            }

            Log.info(f"{log_tag} Retrieved {len(sales)} sales (total_count={total_count})")
            return payload

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "sales": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50,
            }

    @classmethod
    def update_status(cls, sale_id, business_id, new_status, reason=None, authorized_by=None):
        """
        Update sale status (for void, refund operations).

        Args:
            sale_id: Sale ObjectId or string
            business_id: Business ObjectId or string
            new_status: String - new status value
            reason: Optional reason for status change
            authorized_by: Optional manager who authorized

        Returns:
            Bool - success status
        """
        log_tag = f"[sale.py][Sale][update_status][{sale_id}][{business_id}]"

        try:
            sale_id_obj = ObjectId(sale_id) if not isinstance(sale_id, ObjectId) else sale_id
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id

            update_doc = {
                "status": new_status,
                "updated_at": datetime.utcnow(),
            }

            # Add reason based on status
            if new_status in [cls.STATUS_VOIDED] and reason:
                update_doc["void_reason"] = reason
            elif new_status in [cls.STATUS_REFUNDED, cls.STATUS_PARTIALLY_REFUNDED] and reason:
                update_doc["refund_reason"] = reason

            # Add authorization tracking
            if authorized_by:
                auth_id = ObjectId(authorized_by) if not isinstance(authorized_by, ObjectId) else authorized_by
                update_doc["authorized_by"] = auth_id

            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": sale_id_obj, "business_id": business_id_obj},
                {"$set": update_doc},
            )

            if result.modified_count > 0:
                Log.info(f"{log_tag} Status updated to {new_status}")
                return True
            else:
                Log.error(f"{log_tag} Failed to update status")
                return False

        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False

    @classmethod
    def create_indexes(cls):
        """
        Create database indexes for optimal report query performance.
        Run this once during setup or migration.
        """
        log_tag = f"[sale.py][Sale][create_indexes]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            # Core indexes for reports
            collection.create_index([("business_id", 1), ("created_at", -1)])
            collection.create_index([("business_id", 1), ("outlet_id", 1), ("created_at", -1)])
            collection.create_index([("business_id", 1), ("status", 1), ("created_at", -1)])
            collection.create_index([("business_id", 1), ("cashier_id", 1), ("created_at", -1)])
            collection.create_index([("business_id", 1), ("customer_id", 1), ("created_at", -1)])
            collection.create_index([("business_id", 1), ("payment_method", 1), ("created_at", -1)])
            collection.create_index([("transaction_number", 1)], unique=True, sparse=True)
            collection.create_index([("receipt_number", 1)], sparse=True)
            
            Log.info(f"{log_tag} Indexes created successfully")
            return True
            
        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False