# models/stock_ledger.py
from datetime import datetime
from bson import ObjectId

from ...models.base_model import BaseModel
from ...extensions.db import db
from ...utils.crypt import encrypt_data, decrypt_data, hash_data
from ...utils.logger import Log


class StockLedger(BaseModel):
    """
    StockLedger is the single source of truth for all inventory movements.
    Every stock change (purchase, sale, return, adjustment) creates a ledger entry.
    """
    
    collection_name = "stock_ledger"
    
    # Reference types for stock movements
    REF_TYPE_OPENING_STOCK = "OPENING_STOCK"
    REF_TYPE_PURCHASE = "PURCHASE"
    REF_TYPE_SALE = "SALE"
    REF_TYPE_SALE_VOID = "SALE_VOID"
    REF_TYPE_SALE_RETURN = "SALE_RETURN"
    REF_TYPE_ADJUSTMENT = "ADJUSTMENT"
    REF_TYPE_TRANSFER_IN = "TRANSFER_IN"
    REF_TYPE_TRANSFER_OUT = "TRANSFER_OUT"
    REF_TYPE_DAMAGE = "DAMAGE"
    
    def __init__(
        self,
        business_id,
        outlet_id,
        product_id,
        quantity_delta,
        reference_type,
        user_id,
        user__id,
        composite_variant_id=None,
        reference_id=None,
        note=None,
        unit_cost=None,
        agent_id=None,
        admin_id=None,
        **kwargs
    ):
        """
        Initialize a stock ledger entry.
        
        Args:
            business_id: Business ObjectId
            outlet_id: Outlet/location ObjectId
            product_id: Product ObjectId
            quantity_delta: Float - positive for stock in, negative for stock out
            reference_type: String - type of transaction (SALE, PURCHASE, etc.)
            user_id: User string ID from token
            user__id: User ObjectId from token
            composite_variant_id: Optional - specific variant ObjectId
            reference_id: Optional - ObjectId of related document (sale_id, purchase_id, etc.)
            note: Optional - encrypted note about the movement
            unit_cost: Optional - cost per unit for COGS tracking
            agent_id: Optional - agent ObjectId
            admin_id: Optional - admin ObjectId
        """
        super().__init__(business_id=business_id)
        
        # Convert to ObjectId if needed
        self.business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
        self.outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
        self.product_id = ObjectId(product_id) if not isinstance(product_id, ObjectId) else product_id
        self.user__id = ObjectId(user__id) if not isinstance(user__id, ObjectId) else user__id
        
        # Optional ObjectIds
        if composite_variant_id:
            self.composite_variant_id = ObjectId(composite_variant_id) if not isinstance(composite_variant_id, ObjectId) else composite_variant_id
        else:
            self.composite_variant_id = None
            
        if reference_id:
            self.reference_id = ObjectId(reference_id) if not isinstance(reference_id, ObjectId) else reference_id
        else:
            self.reference_id = None
            
        if agent_id:
            self.agent_id = ObjectId(agent_id) if not isinstance(agent_id, ObjectId) else agent_id
        else:
            self.agent_id = None
            
        if admin_id:
            self.admin_id = ObjectId(admin_id) if not isinstance(admin_id, ObjectId) else admin_id
        else:
            self.admin_id = None
        
        # Core fields
        self.user_id = user_id
        self.quantity_delta = float(quantity_delta)
        self.reference_type = reference_type
        
        # Encrypted fields
        self.note = encrypt_data(note) if note else None
        
        # Optional tracking
        self.unit_cost = float(unit_cost) if unit_cost else None
        
        # Timestamps
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def to_dict(self):
        """Convert to dictionary for MongoDB insertion."""
        doc = {
            "business_id": self.business_id,
            "outlet_id": self.outlet_id,
            "product_id": self.product_id,
            "user_id": self.user_id,
            "user__id": self.user__id,
            "quantity_delta": self.quantity_delta,
            "reference_type": self.reference_type,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
        
        # Optional fields
        if self.composite_variant_id:
            doc["composite_variant_id"] = self.composite_variant_id
        if self.reference_id:
            doc["reference_id"] = self.reference_id
        if self.note:
            doc["note"] = self.note
        if self.unit_cost is not None:
            doc["unit_cost"] = self.unit_cost
        if self.agent_id:
            doc["agent_id"] = self.agent_id
        if self.admin_id:
            doc["admin_id"] = self.admin_id
            
        return doc
    
    @classmethod
    def get_by_reference(cls, business_id, reference_type, reference_id):
        """
        Get all ledger entries for a specific reference.
        Useful for viewing all stock movements related to a sale, purchase, etc.
        
        Args:
            business_id: Business ObjectId or string
            reference_type: String (e.g., "SALE")
            reference_id: ObjectId or string of the reference document
            
        Returns:
            List of decrypted ledger entry dicts
        """
        log_tag = f"[stock_ledger.py][StockLedger][get_by_reference]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            reference_id = ObjectId(reference_id) if not isinstance(reference_id, ObjectId) else reference_id
            
            collection = db.get_collection(cls.collection_name)
            entries = list(collection.find({
                "business_id": business_id,
                "reference_type": reference_type,
                "reference_id": reference_id
            }).sort("created_at", -1))
            
            # Decrypt and normalize
            result = []
            for entry in entries:
                entry["_id"] = str(entry["_id"])
                entry["business_id"] = str(entry["business_id"])
                entry["outlet_id"] = str(entry["outlet_id"])
                entry["product_id"] = str(entry["product_id"])
                entry["user__id"] = str(entry["user__id"])
                
                if entry.get("composite_variant_id"):
                    entry["composite_variant_id"] = str(entry["composite_variant_id"])
                if entry.get("reference_id"):
                    entry["reference_id"] = str(entry["reference_id"])
                if entry.get("agent_id"):
                    entry["agent_id"] = str(entry["agent_id"])
                if entry.get("admin_id"):
                    entry["admin_id"] = str(entry["admin_id"])
                if entry.get("note"):
                    entry["note"] = decrypt_data(entry["note"])
                    
                result.append(entry)
            
            Log.info(f"{log_tag} Found {len(result)} entries for {reference_type}:{reference_id}")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []
    
    @classmethod
    def get_stock_history(cls, business_id, outlet_id, product_id, composite_variant_id=None, limit=100):
        """
        Get stock movement history for a specific product/variant at an outlet.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            product_id: Product ObjectId or string
            composite_variant_id: Optional variant ObjectId or string
            limit: Max number of entries to return (default 100)
            
        Returns:
            List of decrypted ledger entry dicts, sorted by newest first
        """
        log_tag = f"[stock_ledger.py][StockLedger][get_stock_history]"
        
        try:
            business_id = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            outlet_id = ObjectId(outlet_id) if not isinstance(outlet_id, ObjectId) else outlet_id
            product_id = ObjectId(product_id) if not isinstance(product_id, ObjectId) else product_id
            
            query = {
                "business_id": business_id,
                "outlet_id": outlet_id,
                "product_id": product_id
            }
            
            if composite_variant_id:
                composite_variant_id = ObjectId(composite_variant_id) if not isinstance(composite_variant_id, ObjectId) else composite_variant_id
                query["composite_variant_id"] = composite_variant_id
            
            collection = db.get_collection(cls.collection_name)
            entries = list(collection.find(query).sort("created_at", -1).limit(limit))
            
            # Decrypt and normalize
            result = []
            for entry in entries:
                entry["_id"] = str(entry["_id"])
                entry["business_id"] = str(entry["business_id"])
                entry["outlet_id"] = str(entry["outlet_id"])
                entry["product_id"] = str(entry["product_id"])
                entry["user__id"] = str(entry["user__id"])
                
                if entry.get("composite_variant_id"):
                    entry["composite_variant_id"] = str(entry["composite_variant_id"])
                if entry.get("reference_id"):
                    entry["reference_id"] = str(entry["reference_id"])
                if entry.get("agent_id"):
                    entry["agent_id"] = str(entry["agent_id"])
                if entry.get("admin_id"):
                    entry["admin_id"] = str(entry["admin_id"])
                if entry.get("note"):
                    entry["note"] = decrypt_data(entry["note"])
                    
                result.append(entry)
            
            Log.info(f"{log_tag} Found {len(result)} history entries")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return []