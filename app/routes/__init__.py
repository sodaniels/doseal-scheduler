#Blueprints for Admin only
from ..resources import (
    blp_business_auth,
    blp_preauth,
    blp_admin_preauth,
    blp_admin_role,
    blp_system_admin_user,
    # blp_admin_expense,
    blp_admin_transaction,
    blp_notice_board,
    blp_messaging,
    blp_commission,
    blp_agent_management,
    blp_essentials,
    blp_payable,
    blp_promo,
    blp_unit, 
    blp_store, 
    blp_category, 
    blp_sub_category, 
    blp_brand, 
    blp_variant, 
    blp_tax,
    blp_warranty, 
    blp_supplier, 
    blp_tag, 
    blp_gift_card, 
    blp_outlet, 
    blp_business_location,
    blp_expense,
    blp_discount, 
    blp_selling_price_group,
    blp_customer,
    blp_customer_group,
    blp_composite_variant,
    pos_blp,
    sale_blp,
    stock_blp,
    cash_blp,
    purchase_blp,
    blp_product,
    blp_reports,
    blp_sales_reports,
    blp_stock_reports,
    blp_customer_reports,
    blp_financial_reports,
    blp_performance,
    blp_operational,
    blp_inventory_optimisation,
    coupon_blp,
    blp_package,
    blp_subscription,
    payment_webhook_blp,
    payment_blp,
    blp_product_import,
)


# Blueprints for Doseal Subscriber only
from ..resources import (
    blp_subscriber_registration,
    blp_subscriber_login,
    blp_subscriber_beneficiary,
    blp_subscriber_transaction,
    blp_billpay,
    #socials
    blp_meta_oauth,
    blp_fb_webhook,
    blp_scheduled_posts,
    blp_x_oauth,
    blp_tiktok_oauth,
    blp_linkedin_oauth,
    blp_social_posts,
)


from ..controllers.internal_controller import (
    get_confirm_account, 
    post_send_sms, 
    twilio_status_webhook,
)
from app.controllers.callback_controller import (
    process_volume_transaction_callback,
    process_transaction_third_party_callback,
    process_intermex_transaction_callback,
    #PAYMENT WEBHOOKS
    process_hubtel_payment_webhook
)
from app.decorators.ip_decorator import restrict_ip
from app.constants.service_code import ALLOWED_IPS


#Subscrivber Routes 
def register_social_routes(app, api):
    blueprints = [
        blp_preauth,
        blp_business_auth,
        blp_system_admin_user,
        blp_admin_role,
        blp_essentials,
        blp_scheduled_posts,
        blp_meta_oauth,
        blp_x_oauth,
        blp_tiktok_oauth,
        blp_linkedin_oauth,
        blp_social_posts,
        blp_fb_webhook,
    ]

    for blueprint in blueprints:
        api.register_blueprint(blueprint, url_prefix="/api/v1")

    # Internal endpoints
    app.add_url_rule('/confirm-account', 'get_confirm_account', get_confirm_account, methods=['GET'])
    app.add_url_rule('/api/v1/send-sms', 'post_send_sms', post_send_sms, methods=['POST'])

    # Callback endpoints (with IP restriction)
    app.add_url_rule(
        '/api/v1/transactions/callback/zeemoney',
        'process_volume_transaction_callback',
        restrict_ip(ALLOWED_IPS)(process_volume_transaction_callback),
        methods=['POST']
    )

    app.add_url_rule(
        '/api/v1/transactions/zeepay-third-party/callback',
        'process_transaction_third_party_callback',
        restrict_ip(ALLOWED_IPS)(process_transaction_third_party_callback),
        methods=['POST']
    )

    # Root route
    @app.route('/')
    def index():
        return {"message": "Welcome to the Scheduler API"}


# Admin Routes
def register_admin_routes(app, api):
    blueprints = [
        blp_preauth,
        blp_business_auth,
        blp_package,
        blp_admin_role,
        blp_system_admin_user,
        # blp_admin_expense,
        # blp_admin_transaction,
        # blp_notice_board,
        # blp_messaging,
        # blp_commission,
        # blp_agent_management,
        # blp_payable,
        # blp_promo,
        blp_unit, 
        blp_store, 
        blp_category, 
        blp_sub_category, 
        blp_brand, 
        blp_variant, 
        blp_tax,
        blp_warranty, 
        blp_supplier, 
        blp_tag, 
        blp_gift_card, 
        blp_outlet, 
        blp_business_location,
        blp_expense,
        blp_discount, 
        blp_selling_price_group,
        blp_customer,
        blp_customer_group,
        blp_composite_variant,
        blp_product,
        pos_blp,
        sale_blp,
        stock_blp,
        cash_blp,
        purchase_blp,
        blp_reports,
        blp_sales_reports,
        blp_stock_reports,
        blp_customer_reports,
        blp_financial_reports,
        blp_performance,
        blp_operational,
        blp_inventory_optimisation,
        coupon_blp,
        blp_subscription,
        payment_webhook_blp,
        payment_blp,
        blp_product_import,
        
    ]

    for blueprint in blueprints:
        api.register_blueprint(blueprint, url_prefix="/api/v1")

    # Internal endpoints
    app.add_url_rule('/confirm-account', 'get_confirm_account', get_confirm_account, methods=['GET'])
    app.add_url_rule('/api/v1/send-sms', 'post_send_sms', post_send_sms, methods=['POST'])
    
    app.add_url_rule('/api/v1/webhooks/twilio/status', 'twilio_status_webhook', twilio_status_webhook, methods=['POST'])
    
    # process hubtel payment webhook
    # app.add_url_rule(
    #     '/webhooks/payment/hubtel',
    #     'process_intermex_transaction_callback',
    #     restrict_ip(ALLOWED_IPS)(process_hubtel_payment_webhook),
    #     methods=['POST']
    # )
    
    # Callback endpoints (with IP restriction)
    # app.add_url_rule(
    #     '/api/v1/transactions/callback',
    #     'process_intermex_transaction_callback',
    #     restrict_ip(ALLOWED_IPS)(process_intermex_transaction_callback),
    #     methods=['POST']
    # )
    
    
    

    # Callback endpoints (with IP restriction)
   
    # Root route
    @app.route('/')
    def index():
        return {"message": "POS Service Online — API is healthy and ready to receive requests."}

