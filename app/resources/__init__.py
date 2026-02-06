#POS Admin Resources
from .doseal.admin.super_superadmin_resource import (
    blp_admin_role,
    blp_system_admin_user,
    # blp_admin_expense,
    blp_expense
)
from .doseal.admin.admin_transaction_resource import blp_admin_transaction
from .doseal.admin.admin_notice_board_resource import blp_notice_board
from .doseal.admin.admin_messaging_resource import blp_messaging
from .doseal.admin.admin_agent_management_resource import blp_agent_management
from .doseal.admin.admin_commission_resource import blp_commission
from .doseal.admin.admin_payable_resource import blp_payable
from .doseal.admin.admin_promo_resource import blp_promo
from .doseal.admin.admin_setup_resource import (
    blp_unit, blp_store, blp_category, blp_sub_category, blp_brand, blp_variant, blp_tax,
    blp_warranty, blp_supplier, blp_tag, blp_gift_card, blp_outlet, blp_business_location,
    blp_composite_variant
)
from .doseal.admin.admin_discount_resource import (
    blp_discount, blp_selling_price_group
)
from .doseal.admin.admin_pos_resource import pos_blp
from .doseal.admin.admin_sale_resource import sale_blp
from .doseal.admin.admin_stock_resource import stock_blp
from .doseal.admin.admin_cash_resource import cash_blp
from .doseal.admin.admin_purchase_resource import purchase_blp
from .doseal.admin.admin_product_resource import blp_product
from .doseal.admin.report.admin_reports_resource import (
    blp_reports, blp_sales_reports, blp_stock_reports,
    blp_customer_reports, blp_operational, blp_performance,
    blp_inventory_optimisation
)
from .doseal.admin.payments.payment_resource import payment_blp
from .doseal.admin.admin_coupon_resource import coupon_blp
from .doseal.admin.report.financial_reports_resource import (
    blp_financial_reports
)
from .doseal.admin.admin_package_resource import blp_package
from .doseal.admin.admin_subscription_resource import blp_subscription
from .doseal.webhooks.payment_webhook_resource import payment_webhook_blp
from .doseal.admin.admin_customer_resource import (
    blp_customer, blp_customer_group
)
from .doseal.admin.product_import_resource import blp_product_import
# Instnmny Resources
from .doseal.admin.admin_business_resource import (
    blp_business_auth, blp_admin_preauth
)
from .doseal.register_resource import blp as blp_user
from .doseal.auth_resource import blp as blp_login
from .doseal.business_oauth_resource import blp as blp_auth
from .doseal.essentials_resource import blp_essentials, blp_preauth
from .doseal.transaction_resource import blp_transaction
#Instntmny Subscriber Only
from .doseal.subscribers.subscriber_authenticaiton import blp_subscriber_registration
from .doseal.subscribers.subscriber_login import blp_subscriber_login
from .doseal.subscribers.subscriber_benefiary_resource import blp_subscriber_beneficiary
from .doseal.subscribers.subscriber_transaction_resource import blp_subscriber_transaction
from .doseal.billpay_resource import blp_billpay

#socials
from .social.oauth_facebook_resource import blp_meta_oauth
from .social.facebook_webhook_resource import blp_fb_webhook
from .social.scheduled_posts_resource import blp_scheduled_posts
from .social.oauth_x_resource import blp_x_oauth
from .social.oauth_tiktok_resource import blp_tiktok_oauth
from .social.social_posts_resource import blp_social_posts
from .social.oauth_linkedin_resource import blp_linkedin_oauth
from .social.oauth_youtube_resource import blp_youtube_oauth
from .social.oauth_youtube_resource import blp_youtube_oauth
from .social.oauth_whatsapp_resource import blp_whatsapp_oauth
from .social.send_now_resource import blp_send_now
from .social.oauth_pinterest_resource import blp_pinterest_oauth
from .social.social_publish_resource import blp_unified_publish
from .social.social_drafts_resources import blp_drafts
from .social.schwriter_resource import blp_schwriter
from .social.schwriter_batch_resource import blp_schwriter_batch
from .social.facebook_insights_resource import blp_meta_impression
from .social.instagram_insights_resource import blp_instagram_insights


__all__ = [
    #-------------------
    #SUBSCRIBER ROUTES
    #-------------------
    "blp_subscriber_registration",
    "blp_subscriber_login",
    "blp_subscriber_beneficiary",
    "blp_subscriber_transaction",
    "blp_billpay",
    #-------------------
    #SOCIALS ROUTES
    #-------------------
    "blp_meta_oauth",
    "blp_fb_webhook",
    "blp_scheduled_posts",
    "blp_x_oauth",
    "blp_tiktok_oauth",
    "blp_social_posts",
    "blp_linkedin_oauth",
    "blp_youtube_oauth",
    "blp_youtube_oauth",
    "blp_whatsapp_oauth",
    "blp_send_now",
    "blp_pinterest_oauth",
    "blp_unified_publish",
    "blp_drafts",
    "blp_schwriter",
    "blp_schwriter_batch",
    "blp_meta_impression",
    "blp_instagram_insights",
    #-------------------
    #ADMIN ROUTES
    #-------------------
    "blp_admin_preauth",
    "blp_admin_role",
    "blp_system_admin_user",
    # "blp_admin_expense",
    "blp_admin_transaction",
    "blp_notice_board",
    "blp_messaging",
    "blp_agent_management",
    "blp_commission",
    "blp_payable",
    "blp_promo",
    "blp_unit",
    "blp_store",
    "blp_category",
    "blp_sub_category",
    "blp_brand",
    "blp_variant",
    "blp_tax",
    "blp_warranty",
    "blp_supplier",
    "blp_tag",
    "blp_gift_card",
    "blp_outlet",
    "blp_business_location",
    "blp_expense",
    "blp_discount",
    "blp_selling_price_group",
    "blp_composite_variant",
    "pos_blp",
    "sale_blp",
    "stock_blp",
    "cash_blp",
    "purchase_blp",
    "blp_product",
    "blp_reports",
    "blp_sales_reports",
    "blp_stock_reports",
    "blp_customer_reports",
    "blp_financial_reports",
    "blp_performance",
    "blp_operational",
    "blp_inventory_optimisation",
    "coupon_blp",
    "blp_package",
    "blp_subscription",
    "payment_webhook_blp",
    "payment_blp",
    "blp_product_import",
]



