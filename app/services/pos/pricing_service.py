# services/pricing_service.py
from decimal import Decimal, ROUND_HALF_UP
from ...utils.logger import Log


class PricingService:
    """
    Service for calculating prices, discounts, and taxes with precise decimal math.
    Handles all pricing logic for POS cart lines.
    """
    
    # Discount types
    DISCOUNT_TYPE_NONE = None
    DISCOUNT_TYPE_FIXED = "Fixed"
    DISCOUNT_TYPE_PERCENTAGE = "Percentage"
    
    # Tax types
    TAX_TYPE_NONE = None
    TAX_TYPE_VAT = "VAT"
    TAX_TYPE_PERCENTAGE = "Percentage"
    
    @staticmethod
    def compute_line_totals(unit_price, quantity, tax_rate=0, discount_type=None, discount_value=0):
        """
        Calculate all line totals with precise decimal arithmetic.
        
        Order of operations:
        1. Calculate subtotal = unit_price * quantity
        2. Apply discount to get line_after_discount
        3. Apply tax to line_after_discount to get line_total
        
        Args:
            unit_price: Decimal or float - price per unit
            quantity: Decimal or float - number of units
            tax_rate: Decimal or float - tax percentage (e.g., 15 for 15%)
            discount_type: None, "Fixed", or "Percentage"
            discount_value: Decimal or float - discount amount or percentage
            
        Returns:
            Dict with precise calculations:
            {
                "line_subtotal": Decimal,
                "discount_amount": Decimal,
                "line_after_discount": Decimal,
                "tax_amount": Decimal,
                "line_total": Decimal
            }
        """
        log_tag = f"[pricing_service.py][PricingService][compute_line_totals]"
        
        try:
            # Convert to Decimal for precision
            unit_price = Decimal(str(unit_price))
            quantity = Decimal(str(quantity))
            tax_rate = Decimal(str(tax_rate))
            discount_value = Decimal(str(discount_value))
            
            # Step 1: Calculate subtotal
            line_subtotal = (unit_price * quantity).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            # Step 2: Calculate discount
            discount_amount = Decimal('0')
            if discount_type == PricingService.DISCOUNT_TYPE_FIXED:
                discount_amount = discount_value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            elif discount_type == PricingService.DISCOUNT_TYPE_PERCENTAGE:
                discount_amount = (line_subtotal * discount_value / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            # Ensure discount doesn't exceed subtotal
            if discount_amount > line_subtotal:
                discount_amount = line_subtotal
            
            line_after_discount = (line_subtotal - discount_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            # Step 3: Calculate tax on discounted amount
            tax_amount = Decimal('0')
            if tax_rate > 0:
                tax_amount = (line_after_discount * tax_rate / Decimal('100')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            line_total = (line_after_discount + tax_amount).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            result = {
                "line_subtotal": float(line_subtotal),
                "discount_amount": float(discount_amount),
                "line_after_discount": float(line_after_discount),
                "tax_amount": float(tax_amount),
                "line_total": float(line_total)
            }
            
            Log.info(f"{log_tag} Calculated: subtotal={result['line_subtotal']}, discount={result['discount_amount']}, tax={result['tax_amount']}, total={result['line_total']}")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            # Return zero values on error
            return {
                "line_subtotal": 0.0,
                "discount_amount": 0.0,
                "line_after_discount": 0.0,
                "tax_amount": 0.0,
                "line_total": 0.0
            }
    
    @staticmethod
    def compute_cart_totals(lines):
        """
        Aggregate totals from all cart lines.
        
        Args:
            lines: List of dicts, each containing:
                - line_subtotal
                - discount_amount
                - line_after_discount
                - tax_amount
                - line_total
                
        Returns:
            Dict with cart-level totals:
            {
                "subtotal": Decimal,
                "total_discount": Decimal,
                "total_tax": Decimal,
                "grand_total": Decimal
            }
        """
        log_tag = f"[pricing_service.py][PricingService][compute_cart_totals]"
        
        try:
            subtotal = Decimal('0')
            total_discount = Decimal('0')
            total_tax = Decimal('0')
            grand_total = Decimal('0')
            
            for line in lines:
                subtotal += Decimal(str(line.get("line_subtotal", 0)))
                total_discount += Decimal(str(line.get("discount_amount", 0)))
                total_tax += Decimal(str(line.get("tax_amount", 0)))
                grand_total += Decimal(str(line.get("line_total", 0)))
            
            result = {
                "subtotal": float(subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                "total_discount": float(total_discount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                "total_tax": float(total_tax.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
                "grand_total": float(grand_total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
            }
            
            Log.info(f"{log_tag} Cart totals: {result}")
            return result
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return {
                "subtotal": 0.0,
                "total_discount": 0.0,
                "total_tax": 0.0,
                "grand_total": 0.0
            }