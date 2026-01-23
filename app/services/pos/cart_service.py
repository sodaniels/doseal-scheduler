# services/cart_service.py
from datetime import datetime
from bson import ObjectId
from ...services.pos.pricing_service import PricingService
from ...utils.logger import Log


class CartService:
    """
    Service for building and managing POS carts server-side.
    Carts are ephemeral structures (not persisted until checkout).
    """
    
    @staticmethod
    def create_cart(business_id, outlet_id, user_id, user__id):
        """
        Initialize an empty cart structure.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            
        Returns:
            Dict representing an empty cart
        """
        log_tag = f"[cart_service.py][CartService][create_cart][{business_id}][{outlet_id}]"
        
        try:
            cart = {
                "business_id": str(business_id),
                "outlet_id": str(outlet_id),
                "user_id": user_id,
                "user__id": str(user__id),
                "lines": [],
                "totals": {
                    "subtotal": 0.0,
                    "total_discount": 0.0,
                    "total_tax": 0.0,
                    "grand_total": 0.0
                },
                "created_at": datetime.utcnow().isoformat()
            }
            
            Log.info(f"{log_tag} Created empty cart")
            return cart
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def add_line(
        cart,
        product_id,
        product_name,
        unit_price,
        quantity,
        composite_variant_id=None,
        variant_name=None,
        tax_rate=0,
        discount_type=None,
        discount_value=0
    ):
        """
        Add a line item to the cart with calculated totals.
        
        Args:
            cart: Cart dict
            product_id: Product ObjectId or string
            product_name: String - product name for display
            unit_price: Float - price per unit
            quantity: Float - number of units
            composite_variant_id: Optional variant ObjectId or string
            variant_name: Optional string - variant description
            tax_rate: Float - tax percentage
            discount_type: None, "Fixed", or "Percentage"
            discount_value: Float - discount amount or percentage
            
        Returns:
            Updated cart dict
        """
        log_tag = f"[cart_service.py][CartService][add_line][{cart.get('business_id')}]"
        
        try:
            # Calculate line totals using PricingService
            line_calculations = PricingService.compute_line_totals(
                unit_price=unit_price,
                quantity=quantity,
                tax_rate=tax_rate,
                discount_type=discount_type,
                discount_value=discount_value
            )
            
            # Build line item
            line = {
                "product_id": str(product_id),
                "product_name": product_name,
                "composite_variant_id": str(composite_variant_id) if composite_variant_id else None,
                "variant_name": variant_name,
                "unit_price": float(unit_price),
                "quantity": float(quantity),
                "tax_rate": float(tax_rate),
                "discount_type": discount_type,
                "discount_value": float(discount_value) if discount_value else 0.0,
                **line_calculations  # Includes line_subtotal, discount_amount, etc.
            }
            
            # Add to cart
            cart["lines"].append(line)
            
            # Recompute cart totals
            cart = CartService.recompute_totals(cart)
            
            Log.info(f"{log_tag} Added line for product {product_id}, qty {quantity}, line_total {line['line_total']}")
            return cart
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return cart
    
    @staticmethod
    def recompute_totals(cart):
        """
        Recalculate cart-level totals from all lines.
        
        Args:
            cart: Cart dict with lines
            
        Returns:
            Updated cart dict with recalculated totals
        """
        log_tag = f"[cart_service.py][CartService][recompute_totals]"
        
        try:
            if not cart.get("lines"):
                cart["totals"] = {
                    "subtotal": 0.0,
                    "total_discount": 0.0,
                    "total_tax": 0.0,
                    "grand_total": 0.0
                }
                return cart
            
            # Use PricingService to aggregate
            totals = PricingService.compute_cart_totals(cart["lines"])
            cart["totals"] = totals
            
            Log.info(f"{log_tag} Recomputed totals: grand_total={totals['grand_total']}")
            return cart
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return cart
    
    @staticmethod
    def build_cart_from_lines(business_id, outlet_id, user_id, user__id, line_items):
        """
        Build a complete cart from a list of line item definitions.
        This is the main method used at checkout.
        
        Args:
            business_id: Business ObjectId or string
            outlet_id: Outlet ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            line_items: List of dicts, each containing:
                - product_id: Required
                - product_name: Required
                - unit_price: Required
                - quantity: Required
                - composite_variant_id: Optional
                - variant_name: Optional
                - tax_rate: Optional (default 0)
                - discount_type: Optional
                - discount_value: Optional (default 0)
                
        Returns:
            Complete cart dict with lines and totals
        """
        log_tag = f"[cart_service.py][CartService][build_cart_from_lines][{business_id}][{outlet_id}]"
        
        try:
            # Create empty cart
            cart = CartService.create_cart(
                business_id=business_id,
                outlet_id=outlet_id,
                user_id=user_id,
                user__id=user__id
            )
            
            if not cart:
                Log.error(f"{log_tag} Failed to create cart")
                return None
            
            # Add each line
            for item in line_items:
                cart = CartService.add_line(
                    cart=cart,
                    product_id=item.get("product_id"),
                    product_name=item.get("product_name"),
                    unit_price=item.get("unit_price"),
                    quantity=item.get("quantity"),
                    composite_variant_id=item.get("composite_variant_id"),
                    variant_name=item.get("variant_name"),
                    tax_rate=item.get("tax_rate", 0),
                    discount_type=item.get("discount_type"),
                    discount_value=item.get("discount_value", 0)
                )
            
            Log.info(f"{log_tag} Built cart with {len(cart['lines'])} lines, grand_total={cart['totals']['grand_total']}")
            return cart
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return None
    
    @staticmethod
    def validate_cart(cart):
        """
        Validate cart structure and business rules.
        
        Args:
            cart: Cart dict
            
        Returns:
            Tuple (bool, list of error messages)
        """
        log_tag = f"[cart_service.py][CartService][validate_cart]"
        
        try:
            errors = []
            
            if not cart:
                errors.append("Cart is empty or invalid")
                return False, errors
            
            if not cart.get("lines") or len(cart["lines"]) == 0:
                errors.append("Cart has no line items")
            
            if cart.get("totals", {}).get("grand_total", 0) <= 0:
                errors.append("Cart grand total must be greater than zero")
            
            # Validate each line
            for idx, line in enumerate(cart.get("lines", [])):
                if not line.get("product_id"):
                    errors.append(f"Line {idx + 1}: Missing product_id")
                if line.get("quantity", 0) <= 0:
                    errors.append(f"Line {idx + 1}: Quantity must be greater than zero")
                if line.get("unit_price", 0) < 0:
                    errors.append(f"Line {idx + 1}: Unit price cannot be negative")
            
            if errors:
                Log.error(f"{log_tag} Validation failed: {errors}")
                return False, errors
            else:
                Log.info(f"{log_tag} Cart validated successfully")
                return True, []
                
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return False, [str(e)]