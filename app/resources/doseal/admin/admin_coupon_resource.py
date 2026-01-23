# resources/coupon_resource.py

from flask import g, request
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import Schema, fields, validate
from ....models.product_model import Discount

from .admin_business_resource import token_required
from ....services.pos.coupon_service import CouponService
from ....utils.json_response import prepared_response
from ....utils.logger import Log

coupon_blp = Blueprint("coupons", __name__, description="Coupon generation and management")


# ============================================
# SCHEMAS
# ============================================

class GenerateCouponSchema(Schema):
    """Schema for generating a single coupon."""
    
    name = fields.Str(required=True)
    discount_type = fields.Str(
        required=True,
        validate=validate.OneOf(["percentage", "fixed_amount"])
    )
    discount_amount = fields.Float(required=True)
    code_length = fields.Int(load_default=8, validate=validate.Range(min=4, max=20))
    code_format = fields.Str(
        load_default="alphanumeric",
        validate=validate.OneOf(["alphanumeric", "letters", "numbers", "mixed"])
    )
    code_prefix = fields.Str(load_default="")
    code_suffix = fields.Str(load_default="")
    scope = fields.Str(load_default="cart", validate=validate.OneOf(["product", "category", "cart"]))
    start_date = fields.Str(required=False, allow_none=True)
    end_date = fields.Str(required=False, allow_none=True)
    max_uses = fields.Int(required=False, allow_none=True)
    max_uses_per_customer = fields.Int(load_default=1)
    minimum_purchase = fields.Float(required=False, allow_none=True)
    product_ids = fields.List(fields.Str(), load_default=[])
    outlet_ids = fields.List(fields.Str(), load_default=[])
    category_names = fields.List(fields.Str(), load_default=[])


class BulkCouponSchema(Schema):
    """Schema for bulk coupon generation."""
    
    count = fields.Int(required=True, validate=validate.Range(min=1, max=1000))
    name_template = fields.Str(required=True)
    discount_type = fields.Str(
        required=True,
        validate=validate.OneOf(["percentage", "fixed_amount"])
    )
    discount_amount = fields.Float(required=True)
    code_length = fields.Int(load_default=8)
    code_format = fields.Str(load_default="alphanumeric")
    code_prefix = fields.Str(load_default="")
    code_suffix = fields.Str(load_default="")
    scope = fields.Str(load_default="cart")
    start_date = fields.Str(required=False, allow_none=True)
    end_date = fields.Str(required=False, allow_none=True)
    max_uses = fields.Int(required=False, allow_none=True)
    outlet_ids = fields.List(fields.Str(), load_default=[])
    max_uses_per_customer = fields.Int(load_default=1)
    minimum_purchase = fields.Float(required=False, allow_none=True)


class CampaignCouponSchema(Schema):
    """Schema for campaign coupon generation."""
    
    campaign_name = fields.Str(required=True)
    count = fields.Int(required=True, validate=validate.Range(min=1, max=1000))
    discount_type = fields.Str(required=True, validate=validate.OneOf(["percentage", "fixed_amount"]))
    discount_amount = fields.Float(required=True)
    valid_days = fields.Int(required=True, validate=validate.Range(min=1, max=365))
    code_prefix = fields.Str(load_default="")
    outlet_ids = fields.List(fields.Str(), load_default=[])
    minimum_purchase = fields.Float(required=False, allow_none=True)


# ============================================
# ENDPOINTS
# ============================================

@coupon_blp.route("/coupons/generate", methods=["POST"])
class GenerateSingleCoupon(MethodView):
    """Generate a single coupon code."""
    
    @token_required
    @coupon_blp.arguments(GenerateCouponSchema, location="json")
    def post(self, json_data):
        """Generate a single coupon."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        admin_id = str(user_info.get("_id"))
        
        try:
            
            # Generate unique code
            code, success = CouponService.generate_unique_code(
                business_id=business_id,
                length=json_data.get("code_length", 8),
                format_type=json_data.get("code_format", "alphanumeric"),
                prefix=json_data.get("code_prefix", ""),
                suffix=json_data.get("code_suffix", "")
            )
            
            if not success:
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="Failed to generate unique coupon code",
                    errors=["Unable to find unique code after multiple attempts"]
                )
            
            # Create discount
            discount = Discount(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                admin_id=admin_id,
                name=json_data.get("name"),
                code=code,
                discount_type=json_data.get("discount_type"),
                discount_amount=json_data.get("discount_amount"),
                scope=json_data.get("scope", "cart"),
                start_date=json_data.get("start_date"),
                end_date=json_data.get("end_date"),
                max_uses=json_data.get("max_uses"),
                max_uses_per_customer=json_data.get("max_uses_per_customer", 1),
                minimum_purchase=json_data.get("minimum_purchase"),
                product_ids=json_data.get("product_ids", []),
                outlet_ids=json_data.get("outlet_ids", []),
                category_names=json_data.get("category_names", []),
                status="Active"
            )
            
            discount_id = discount.save()
            
            if not discount_id:
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="Failed to save coupon"
                )
            
            created_coupon = Discount.get_by_id(discount_id, business_id)
            
            created_coupon.pop("hashed_status", None)
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Coupon generated successfully",
                data=created_coupon
            )
            
        except Exception as e:
            Log.error(f"[GenerateSingleCoupon] Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to generate coupon",
                errors=[str(e)]
            )


@coupon_blp.route("/coupons/generate/bulk", methods=["POST"])
class GenerateBulkCoupons(MethodView):
    """Generate multiple coupons in bulk."""
    
    @token_required
    @coupon_blp.arguments(BulkCouponSchema, location="json")
    def post(self, json_data):
        """Generate bulk coupons."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        admin_id = str(user_info.get("_id"))
        
        try:
            result = CouponService.generate_bulk_coupons(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                admin_id=admin_id,
                **json_data
            )
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message=f"Bulk generation complete: {result['total_created']} of {result['total_requested']} coupons created",
                data=result
            )
            
        except Exception as e:
            Log.error(f"[GenerateBulkCoupons] Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to generate bulk coupons",
                errors=[str(e)]
            )


@coupon_blp.route("/coupons/generate/campaign", methods=["POST"])
class GenerateCampaignCoupons(MethodView):
    """Generate coupons for a marketing campaign."""
    
    @token_required
    @coupon_blp.arguments(CampaignCouponSchema, location="json")
    def post(self, json_data):
        """Generate campaign coupons."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        admin_id = str(user_info.get("_id"))
        
        try:
            result = CouponService.generate_campaign_coupons(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                admin_id=admin_id,
                **json_data
            )
            
            return prepared_response(
                status=True,
                status_code="CREATED",
                message=f"Campaign '{json_data['campaign_name']}' created with {result['total_created']} coupons",
                data=result
            )
            
        except Exception as e:
            Log.error(f"[GenerateCampaignCoupons] Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to generate campaign coupons",
                errors=[str(e)]
            )


@coupon_blp.route("/coupons/generate/referral", methods=["POST"])
class GenerateReferralCode(MethodView):
    """Generate a referral code for a customer."""
    
    @token_required
    def post(self):
        """Generate referral code."""
        
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        user_id = user_info.get("user_id")
        user__id = str(user_info.get("_id"))
        admin_id = str(user_info.get("_id"))
        
        try:
            data = request.get_json()
            
            referrer_name = data.get("referrer_name", "")
            discount_amount = data.get("discount_amount", 10)
            
            result = CouponService.generate_referral_code(
                business_id=business_id,
                user_id=user_id,
                user__id=user__id,
                referrer_name=referrer_name,
                discount_amount=discount_amount
            )
            
            if result.get("success"):
                return prepared_response(
                    status=True,
                    status_code="CREATED",
                    message="Referral code generated successfully",
                    data=result
                )
            else:
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message=result.get("error", "Failed to generate referral code")
                )
                
        except Exception as e:
            Log.error(f"[GenerateReferralCode] Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to generate referral code",
                errors=[str(e)]
            )