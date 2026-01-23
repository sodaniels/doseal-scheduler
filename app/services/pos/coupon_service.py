# services/coupon_service.py

import random
import string
from datetime import datetime, timedelta
from bson import ObjectId
from ...models.product_model import Product, Discount
from app import db
from ...utils.logger import Log
from ...utils.crypt import hash_data


class CouponService:
    """Service for generating and managing coupon codes."""
    
    # Coupon code formats
    FORMAT_ALPHANUMERIC = "alphanumeric"  # ABC123XYZ
    FORMAT_LETTERS = "letters"            # ABCDEFGH
    FORMAT_NUMBERS = "numbers"            # 12345678
    FORMAT_MIXED = "mixed"                # AB12-CD34
    FORMAT_WORD = "word"                  # SUMMER2024
    
    @staticmethod
    def generate_code(length=8, format_type="alphanumeric", prefix="", suffix=""):
        """
        Generate a random coupon code.
        
        Args:
            length: Length of the random part (default 8)
            format_type: Type of code to generate
            prefix: Optional prefix (e.g., "SAVE")
            suffix: Optional suffix (e.g., "2024")
            
        Returns:
            String coupon code
        """
        if format_type == CouponService.FORMAT_ALPHANUMERIC:
            # Uppercase letters and numbers (no confusing chars like O, 0, I, 1)
            chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            random_part = ''.join(random.choices(chars, k=length))
            
        elif format_type == CouponService.FORMAT_LETTERS:
            # Only uppercase letters
            chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
            random_part = ''.join(random.choices(chars, k=length))
            
        elif format_type == CouponService.FORMAT_NUMBERS:
            # Only numbers
            random_part = ''.join(random.choices(string.digits, k=length))
            
        elif format_type == CouponService.FORMAT_MIXED:
            # Mixed with separator (e.g., AB12-CD34)
            chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            part1 = ''.join(random.choices(chars, k=length // 2))
            part2 = ''.join(random.choices(chars, k=length // 2))
            random_part = f"{part1}-{part2}"
            
        else:
            # Default alphanumeric
            chars = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
            random_part = ''.join(random.choices(chars, k=length))
        
        # Combine prefix + random + suffix
        code = f"{prefix}{random_part}{suffix}".upper()
        
        return code
    
    @staticmethod
    def check_code_exists(business_id, code):
        """
        Check if a coupon code already exists.
        
        Args:
            business_id: Business ObjectId or string
            code: Coupon code to check
            
        Returns:
            Bool - True if exists, False otherwise
        """
        try:
            business_id_obj = ObjectId(business_id) if not isinstance(business_id, ObjectId) else business_id
            hashed_code = hash_data(code.upper())
            
            collection = db.get_collection(Discount.collection_name)
            
            existing = collection.find_one({
                "business_id": business_id_obj,
                "hashed_code": hashed_code
            })
            
            return existing is not None
            
        except Exception as e:
            Log.error(f"[check_code_exists] Error: {str(e)}")
            return False
    
    @staticmethod
    def generate_unique_code(business_id, length=8, format_type="alphanumeric", prefix="", suffix="", max_attempts=100):
        """
        Generate a unique coupon code (not already in database).
        
        Args:
            business_id: Business ObjectId or string
            length: Length of random part
            format_type: Code format type
            prefix: Optional prefix
            suffix: Optional suffix
            max_attempts: Maximum attempts to find unique code
            
        Returns:
            Tuple (code: str or None, success: bool)
        """
        for attempt in range(max_attempts):
            code = CouponService.generate_code(length, format_type, prefix, suffix)
            
            if not CouponService.check_code_exists(business_id, code):
                return code, True
        
        Log.error(f"[generate_unique_code] Failed to generate unique code after {max_attempts} attempts")
        return None, False
    
    @staticmethod
    def generate_bulk_coupons(
        business_id,
        user_id,
        user__id,
        count=10,
        name_template="Bulk Coupon",
        discount_type="percentage",
        discount_amount=10,
        code_length=8,
        code_format="alphanumeric",
        code_prefix="",
        code_suffix="",
        scope="cart",
        start_date=None,
        end_date=None,
        max_uses=None,
        max_uses_per_customer=1,
        minimum_purchase=None,
        **kwargs
    ):
        """
        Generate multiple coupons in bulk.
        
        Args:
            business_id: Business ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            count: Number of coupons to generate
            name_template: Name template (will append number)
            discount_type: "percentage" or "fixed_amount"
            discount_amount: Discount value
            code_length: Length of random part of code
            code_format: Format type
            code_prefix: Code prefix
            code_suffix: Code suffix
            scope: "product", "category", or "cart"
            start_date: When coupons become active
            end_date: When coupons expire
            max_uses: Total usage limit per coupon
            max_uses_per_customer: Usage limit per customer
            minimum_purchase: Minimum purchase amount
            **kwargs: Additional discount parameters
            
        Returns:
            Dict with created coupons and errors
        """
        log_tag = f"[CouponService][generate_bulk_coupons][{business_id}]"
        
        created_coupons = []
        errors = []
        
        for i in range(count):
            try:
                # Generate unique code
                code, success = CouponService.generate_unique_code(
                    business_id=business_id,
                    length=code_length,
                    format_type=code_format,
                    prefix=code_prefix,
                    suffix=code_suffix
                )
                
                if not success:
                    errors.append(f"Failed to generate unique code for coupon {i+1}")
                    continue
                
                # Create discount/coupon
                discount = Discount(
                    business_id=business_id,
                    user_id=user_id,
                    user__id=user__id,
                    name=f"{name_template} {i+1}",
                    code=code,
                    discount_type=discount_type,
                    discount_amount=discount_amount,
                    scope=scope,
                    start_date=start_date,
                    end_date=end_date,
                    max_uses=max_uses,
                    max_uses_per_customer=max_uses_per_customer,
                    minimum_purchase=minimum_purchase,
                    status="Active",
                    **kwargs
                )
                
                discount_id = discount.save()
                
                if discount_id:
                    created_coupons.append({
                        "id": str(discount_id),
                        "code": code,
                        "name": f"{name_template} {i+1}",
                        "discount_type": discount_type,
                        "discount_amount": discount_amount,
                    })
                    Log.info(f"{log_tag} Coupon created: {code}")
                else:
                    errors.append(f"Failed to save coupon {i+1}")
                    
            except Exception as e:
                Log.error(f"{log_tag} Error creating coupon {i+1}: {str(e)}")
                errors.append(f"Coupon {i+1}: {str(e)}")
        
        Log.info(f"{log_tag} Bulk generation complete: {len(created_coupons)} created, {len(errors)} errors")
        
        return {
            "created": created_coupons,
            "total_created": len(created_coupons),
            "total_requested": count,
            "errors": errors,
            "success_rate": f"{(len(created_coupons) / count * 100):.1f}%" if count > 0 else "0%"
        }
    
    @staticmethod
    def generate_campaign_coupons(
        business_id,
        user_id,
        user__id,
        campaign_name,
        count=100,
        discount_type="percentage",
        discount_amount=10,
        valid_days=30,
        code_prefix="",
        **kwargs
    ):
        """
        Generate coupons for a marketing campaign.
        
        Args:
            business_id: Business ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            campaign_name: Name of the campaign
            count: Number of coupons
            discount_type: "percentage" or "fixed_amount"
            discount_amount: Discount value
            valid_days: Number of days coupons are valid
            code_prefix: Prefix for codes (e.g., "SPRING")
            **kwargs: Additional parameters
            
        Returns:
            Dict with campaign details and coupons
        """
        # Calculate dates
        start_date = datetime.utcnow().isoformat()
        end_date = (datetime.utcnow() + timedelta(days=valid_days)).isoformat()
        
        # Generate bulk coupons
        result = CouponService.generate_bulk_coupons(
            business_id=business_id,
            user_id=user_id,
            user__id=user__id,
            count=count,
            name_template=f"{campaign_name} Coupon",
            discount_type=discount_type,
            discount_amount=discount_amount,
            code_prefix=code_prefix or campaign_name[:4].upper(),
            start_date=start_date,
            end_date=end_date,
            max_uses=1,  # One-time use per coupon
            max_uses_per_customer=1,
            **kwargs
        )
        
        return {
            "campaign_name": campaign_name,
            "campaign_start": start_date,
            "campaign_end": end_date,
            "valid_days": valid_days,
            **result
        }
    
    @staticmethod
    def generate_referral_code(business_id, user_id, user__id, referrer_name="", discount_amount=10):
        """
        Generate a unique referral code for a customer.
        
        Args:
            business_id: Business ObjectId or string
            user_id: User string ID
            user__id: User ObjectId
            referrer_name: Name to include in code
            discount_amount: Discount amount for referral
            
        Returns:
            Dict with referral code details
        """
        # Create prefix from name (first 4 letters)
        prefix = "REF"
        if referrer_name:
            prefix = ''.join(c for c in referrer_name.upper() if c.isalpha())[:4]
        
        # Generate unique code
        code, success = CouponService.generate_unique_code(
            business_id=business_id,
            length=6,
            format_type="alphanumeric",
            prefix=prefix
        )
        
        if not success:
            return {"success": False, "error": "Failed to generate unique code"}
        
        # Create referral discount (no expiry, unlimited uses)
        discount = Discount(
            business_id=business_id,
            user_id=user_id,
            user__id=user__id,
            admin_id=user__id,
            name=f"Referral Code - {referrer_name or 'Customer'}",
            code=code,
            discount_type="percentage",
            discount_amount=discount_amount,
            scope="cart",
            max_uses_per_customer=1,  # One use per customer
            status="Active"
        )
        
        discount_id = discount.save()
        
        if discount_id:
            return {
                "success": True,
                "referral_code": code,
                "discount_id": str(discount_id),
                "discount_amount": discount_amount,
                "type": "percentage"
            }
        else:
            return {"success": False, "error": "Failed to save referral code"}