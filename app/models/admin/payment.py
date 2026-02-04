# models/admin/payment.py

from datetime import datetime
from bson import ObjectId
from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.logger import Log
from ...constants.service_code import HTTP_STATUS_CODES

class Payment(BaseModel):
    """
    Payment model for tracking all payment transactions.
    Supports multiple payment gateways and methods.
    """
    
    collection_name = "payments"
    
    # Payment Statuses
    STATUS_PENDING = "Pending"
    STATUS_PROCESSING = "Processing"
    STATUS_SUCCESS = "Success"
    STATUS_FAILED = "Failed"
    STATUS_CANCELLED = "Cancelled"
    STATUS_REFUNDED = "Refunded"
    
    # Payment Types
    TYPE_SUBSCRIPTION = "subscription"
    TYPE_PURCHASE = "purchase"
    TYPE_TOPUP = "topup"
    TYPE_RENEWAL = "renewal"
    
    def __init__(
        self,
        business_id,
        user_id,
        user__id,
        amount,
        payment_method,
        amount_detail,
        # Optional parameters
        reference=None,
        currency="USD",
        payment_type=None,
        old_package_id=None,
        package_id=None,
        subscription_id=None,
        order_id=None,
        gateway="manual",
        gateway_transaction_id=None,
        checkout_request_id=None,
        status=None,
        status_message=None,
        status_code=411,
        initial_response=None,
        callback_response=None,
        customer_phone=None,
        customer_email=None,
        customer_name=None,
        metadata=None,
        notes=None,
        callback_url=None,
        redirect_url=None,
        error_message=None,
        retry_count=0,
        admin_id=None,
        agent_id=None,
        **kwargs
    ):
        """
        Initialize a payment transaction.
        
        Args:
            business_id: Business ObjectId or string (REQUIRED)
            user_id: User string ID (REQUIRED)
            user__id: User ObjectId (REQUIRED)
            amount: Payment amount (REQUIRED)
            amount_detail: amount_detail (REQUIRED)
            payment_method: Method used (REQUIRED)
            reference: Internal payment reference
            currency: Currency code (default: USD)
            payment_type: Type of payment (default: subscription)
            package_id: Related package ID
            subscription_id: Related subscription ID
            order_id: Related order/invoice ID
            gateway: Payment gateway (default: manual)
            gateway_transaction_id: Transaction ID from gateway
            checkout_request_id: Checkout/request ID from gateway
            status: Payment status (default: Pending)
            status_message: Status message
            status_code: Status code
            initial_response: Initial API response
            callback_response: Callback response
            customer_phone: Customer phone number
            customer_email: Customer email
            customer_name: Customer name
            metadata: Additional metadata (dict)
            notes: Payment notes
            callback_url: Webhook callback URL
            redirect_url: User redirect URL after payment
            error_message: Error message if failed
            retry_count: Number of retry attempts
            admin_id: Admin ObjectId
            agent_id: Agent ObjectId
        """
        super().__init__(
            business_id=business_id,
            user__id=user__id,
            user_id=user_id,
            admin_id=admin_id,
            agent_id=agent_id,
            **kwargs
        )
        
        # Convert to ObjectId
        self.business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        self.user__id = ObjectId(user__id) if not isinstance(user__id, ObjectId) else user__id
        
        if package_id:
            self.package_id = ObjectId(package_id) if not isinstance(package_id, ObjectId) else package_id
        else:
            self.package_id = None
            
        if old_package_id:
            self.old_package_id = ObjectId(old_package_id) if not isinstance(old_package_id, ObjectId) else old_package_id
        else:
            self.old_package_id = None
        
        if subscription_id:
            self.subscription_id = ObjectId(subscription_id) if not isinstance(subscription_id, ObjectId) else subscription_id
        else:
            self.subscription_id = None
        
        if admin_id:
            self.admin_id = ObjectId(admin_id) if not isinstance(admin_id, ObjectId) else admin_id
        else:
            self.admin_id = None
        
        if agent_id:
            self.agent_id = ObjectId(agent_id) if not isinstance(agent_id, ObjectId) else agent_id
        else:
            self.agent_id = None
        
        # Amount details - NO ENCRYPTION
        self.amount = float(amount)
        self.currency = currency
        self.amount_detail = amount_detail
        
        # Payment details - NO ENCRYPTION
        self.reference = reference
        self.payment_method = payment_method
        self.payment_type = payment_type or self.TYPE_SUBSCRIPTION
        self.status = status or self.STATUS_PENDING
        self.status_code = status_code
        self.status_message = status_message
        self.initial_response = initial_response
        self.callback_response = callback_response
        
        # Gateway details - PLAIN
        self.user_id = user_id
        self.gateway = gateway
        self.gateway_transaction_id = gateway_transaction_id
        self.checkout_request_id = checkout_request_id
        self.order_id = order_id
        
        # Customer details - PLAIN
        self.customer_phone = customer_phone
        self.customer_email = customer_email
        self.customer_name = customer_name
        
        # Metadata - PLAIN (JSON)
        self.metadata = metadata or {}
        self.notes = notes
        
        # URLs - PLAIN
        self.callback_url = callback_url
        self.redirect_url = redirect_url
        
        # Error handling - NO ENCRYPTION
        self.error_message = error_message
        self.retry_count = retry_count
        
        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.completed_at = None
        self.failed_at = None
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            "business_id": self.business_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "amount": self.amount,
            "amount_detail": self.amount_detail,
            "currency": self.currency,
            "payment_method": self.payment_method,
            "payment_type": self.payment_type,
            "status": self.status,
            "gateway": self.gateway,
            "customer_phone": self.customer_phone,
            "customer_email": self.customer_email,
            "customer_name": self.customer_name,
            "metadata": self.metadata,
            "retry_count": self.retry_count,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        
        # Optional fields
        if self.package_id:
            doc["package_id"] = self.package_id
        if self.old_package_id:
            doc["old_package_id"] = self.old_package_id
        if self.subscription_id:
            doc["subscription_id"] = self.subscription_id
        if self.order_id:
            doc["order_id"] = self.order_id
        if self.reference:
            doc["reference"] = self.reference
        if self.gateway_transaction_id:
            doc["gateway_transaction_id"] = self.gateway_transaction_id
        if self.checkout_request_id:
            doc["checkout_request_id"] = self.checkout_request_id
        if self.notes:
            doc["notes"] = self.notes
        if self.callback_url:
            doc["callback_url"] = self.callback_url
        if self.redirect_url:
            doc["redirect_url"] = self.redirect_url
        if self.error_message:
            doc["error_message"] = self.error_message
        if self.completed_at:
            doc["completed_at"] = self.completed_at
        if self.failed_at:
            doc["failed_at"] = self.failed_at
        if self.admin_id:
            doc["admin_id"] = self.admin_id
        if self.agent_id:
            doc["agent_id"] = self.agent_id
        if self.status_code:
            doc["status_code"] = self.status_code
        if self.status_message:
            doc["status_message"] = self.status_message
        if self.callback_response:
            doc["callback_response"] = self.callback_response
        if self.initial_response:
            doc["initial_response"] = self.initial_response
            
        return doc
    
    # ---------------- INTERNAL HELPER ---------------- #
    
    @staticmethod
    def _normalise_payment_doc(payment: dict) -> dict:
        """Normalise ObjectId fields - NO DECRYPTION NEEDED."""
        if not payment:
            return None

        payment["_id"] = str(payment["_id"])
        payment["business_id"] = str(payment["business_id"])
        if payment.get("user__id"):
            payment["user__id"] = str(payment["user__id"])
        if payment.get("package_id"):
            payment["package_id"] = str(payment["package_id"])
        if payment.get("old_package_id"):
            payment["old_package_id"] = str(payment["old_package_id"])
        if payment.get("subscription_id"):
            payment["subscription_id"] = str(payment["subscription_id"])
        if payment.get("admin_id"):
            payment["admin_id"] = str(payment["admin_id"])
        if payment.get("agent_id"):
            payment["agent_id"] = str(payment["agent_id"])
            
        if payment.get("amount_detail"):
            payment["amount_detail"] = str(payment["amount_detail"])    
        
        # Ensure amount is float
        if payment.get("amount"):
            try:
                payment["amount"] = float(payment["amount"])
            except (ValueError, TypeError):
                payment["amount"] = 0.0
        
        return payment
    
    # ---------------- QUERIES ---------------- #
    
    @classmethod
    def get_by_id(cls, payment_id, business_id=None):
        """
        Retrieve a payment by ID.
        
        Args:
            payment_id: Payment ObjectId or string
            business_id: Optional business ID for security
            
        Returns:
            Normalised payment dict or None
        """
        log_tag = f"[payment.py][Payment][get_by_id][{payment_id}]"
        
        try:
            payment_id = ObjectId(payment_id) if not isinstance(payment_id, ObjectId) else payment_id
            
            collection = db.get_collection(cls.collection_name)
            
            query = {"_id": payment_id}
            if business_id:
                business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
                query["business_id"] = business_id
            
            payment = collection.find_one(query)
            
            if not payment:
                Log.error(f"{log_tag} Payment not found")
                return None
            
            payment = cls._normalise_payment_doc(payment)
            Log.info(f"{log_tag} Payment retrieved successfully")
            return payment
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @classmethod
    def get_by_order_id(cls, order_id):
        """
        Get payment by order ID (client reference).
        
        Args:
            order_id: Order ID / Client Reference (string)
            
        Returns:
            Normalised payment dict or None
        """
        log_tag = f"[payment.py][Payment][get_by_order_id][{order_id}]"
        
        try:
            if not order_id:
                Log.error(f"{log_tag} Order ID is required")
                return None
            
            collection = db.get_collection(cls.collection_name)
            payment = collection.find_one({"order_id": order_id})
            
            if payment:
                payment = cls._normalise_payment_doc(payment)
                Log.info(f"{log_tag} Payment retrieved successfully")
                return payment
            else:
                Log.warning(f"{log_tag} Payment not found")
                return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return None
    
    @classmethod
    def get_by_reference(cls, reference):
        """
        Get payment by internal reference.
        
        Args:
            reference: Internal payment reference
            
        Returns:
            Normalised payment dict or None
        """
        log_tag = f"[payment.py][Payment][get_by_reference][{reference}]"
        
        try:
            if not reference:
                Log.error(f"{log_tag} Reference is required")
                return None
            
            collection = db.get_collection(cls.collection_name)
            payment = collection.find_one({"reference": reference})
            
            if payment:
                payment = cls._normalise_payment_doc(payment)
                Log.info(f"{log_tag} Payment retrieved successfully")
                return payment
            else:
                Log.warning(f"{log_tag} Payment not found")
                return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}", exc_info=True)
            return None

    @classmethod
    def get_by_checkout_request_id(cls, checkout_request_id):
        """
        Get payment by checkout/request ID.
        
        Args:
            checkout_request_id: Checkout request ID from gateway
            
        Returns:
            Normalised payment dict or None
        """
        log_tag = f"[payment.py][Payment][get_by_checkout_request_id][{checkout_request_id}]"
        
        try:
            if not checkout_request_id:
                Log.error(f"{log_tag} Checkout request ID is required")
                return None
            
            collection = db.get_collection(cls.collection_name)
            payment = collection.find_one({"checkout_request_id": checkout_request_id})
            
            if payment:
                payment = cls._normalise_payment_doc(payment)
                Log.info(f"{log_tag} Payment retrieved successfully")
                return payment
            else:
                Log.warning(f"{log_tag} Payment not found")
                return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_by_gateway_transaction_id(cls, gateway_transaction_id):
        """
        Get payment by gateway transaction ID.
        
        Args:
            gateway_transaction_id: Transaction ID from payment gateway
            
        Returns:
            Normalised payment dict or None
        """
        log_tag = f"[payment.py][Payment][get_by_gateway_transaction_id][{gateway_transaction_id}]"
        
        try:
            if not gateway_transaction_id:
                Log.error(f"{log_tag} Gateway transaction ID is required")
                return None
            
            collection = db.get_collection(cls.collection_name)
            payment = collection.find_one({"gateway_transaction_id": gateway_transaction_id})
            
            if payment:
                payment = cls._normalise_payment_doc(payment)
                Log.info(f"{log_tag} Payment retrieved successfully")
                return payment
            else:
                Log.warning(f"{log_tag} Payment not found")
                return None
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None

    @classmethod
    def get_by_business_id(cls, business_id, page=None, per_page=None, status=None, gateway=None):
        """
        List payments for a business.
        
        Args:
            business_id: Business ObjectId or string
            page: Optional page number
            per_page: Optional items per page
            status: Optional status filter
            gateway: Optional gateway filter
            
        Returns:
            Dict with paginated payments
        """
        log_tag = f"[payment.py][Payment][get_by_business_id][{business_id}]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            
            query = {"business_id": business_id}
            
            # NO ENCRYPTION - direct comparison
            if status:
                query["status"] = status
            
            if gateway:
                query["gateway"] = gateway
            
            # Use BaseModel.paginate
            result = cls.paginate(query, page, per_page, sort_by="created_at", sort_order=-1)
            
            # Normalise all payments
            payments = [cls._normalise_payment_doc(p) for p in result.get("items", [])]
            
            result["payments"] = payments
            result.pop("items", None)
            
            Log.info(f"{log_tag} Retrieved {len(result['payments'])} payments")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "payments": [],
                "total_count": 0,
                "total_pages": 0,
                "current_page": page or 1,
                "per_page": per_page or 50
            }
    
    @classmethod
    def get_pending_payments(cls, business_id=None, older_than_minutes=30):
        """
        Get payments that are still pending after a certain time.
        
        Args:
            business_id: Optional business ID filter
            older_than_minutes: Payments pending for more than X minutes
            
        Returns:
            List of normalised payment dicts
        """
        log_tag = f"[payment.py][Payment][get_pending_payments]"
        
        try:
            from datetime import timedelta
            
            collection = db.get_collection(cls.collection_name)
            
            cutoff_time = datetime.utcnow() - timedelta(minutes=older_than_minutes)
            
            # NO ENCRYPTION - direct comparison
            query = {
                "status": cls.STATUS_PENDING,
                "created_at": {"$lt": cutoff_time}
            }
            
            if business_id:
                business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
                query["business_id"] = business_id
            
            payments = list(collection.find(query).sort("created_at", -1))
            payments = [cls._normalise_payment_doc(p) for p in payments]
            
            Log.info(f"{log_tag} Found {len(payments)} pending payments")
            return payments
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []
    
    @classmethod
    def update_status(cls, payment_id, new_status, gateway_transaction_id=None, error_message=None):
        """
        Update payment status.
        
        Args:
            payment_id: Payment ObjectId or string
            new_status: New status value
            gateway_transaction_id: Optional transaction ID from gateway
            error_message: Optional error message
            
        Returns:
            Bool - success status
        """
        log_tag = f"[payment.py][Payment][update_status][{payment_id}]"
        
        try:
            payment_id = ObjectId(payment_id) if not isinstance(payment_id, ObjectId) else payment_id
            
            # NO ENCRYPTION
            update_doc = {
                "status": new_status,
                "updated_at": datetime.utcnow()
            }
            
            if gateway_transaction_id:
                update_doc["gateway_transaction_id"] = gateway_transaction_id
            
            if error_message:
                update_doc["error_message"] = error_message
            
            if new_status == cls.STATUS_SUCCESS:
                update_doc["completed_at"] = datetime.utcnow()
                update_doc['status_code'] = HTTP_STATUS_CODES["OK"]
            elif new_status == cls.STATUS_FAILED:
                update_doc['status_code'] = HTTP_STATUS_CODES["BAD_REQUEST"]
                update_doc["failed_at"] = datetime.utcnow()
            
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": payment_id},
                {"$set": update_doc}
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
    def increment_retry(cls, payment_id):
        """Increment retry count."""
        log_tag = f"[payment.py][Payment][increment_retry][{payment_id}]"
        
        try:
            payment_id = ObjectId(payment_id) if not isinstance(payment_id, ObjectId) else payment_id
            
            collection = db.get_collection(cls.collection_name)
            result = collection.update_one(
                {"_id": payment_id},
                {
                    "$inc": {"retry_count": 1},
                    "$set": {"updated_at": datetime.utcnow()}
                }
            )
            
            return result.modified_count > 0
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False
    
    @classmethod
    def create_indexes(cls):
        """Create database indexes for optimal query performance."""
        log_tag = f"[payment.py][Payment][create_indexes]"
        
        try:
            collection = db.get_collection(cls.collection_name)
            
            # Core indexes
            collection.create_index([("business_id", 1), ("created_at", -1)])
            collection.create_index([("business_id", 1), ("status", 1)])
            collection.create_index([("business_id", 1), ("gateway", 1)])
            
            # Reference indexes
            collection.create_index([("reference", 1)], unique=True, sparse=True)
            collection.create_index([("order_id", 1)], unique=True, sparse=True)
            collection.create_index([("checkout_request_id", 1)], unique=True, sparse=True)
            collection.create_index([("gateway_transaction_id", 1)], sparse=True)
            
            # Other indexes
            collection.create_index([("subscription_id", 1)], sparse=True)
            collection.create_index([("package_id", 1)])
            collection.create_index([("user_id", 1), ("created_at", -1)])
            collection.create_index([("gateway", 1), ("status", 1)])
            
            Log.info(f"{log_tag} Indexes created successfully")
            return True
            
        except Exception as e:
            Log.error(f"{log_tag} Error creating indexes: {str(e)}")
            return False