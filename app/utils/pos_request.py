class RequestMaker:
    def __init__(self, **kwargs):
        self.__user__id = kwargs.get("user__id")
        self.__user_id = kwargs.get("user_id")
        self.__tenant_id = kwargs.get("tenant_id")
        self.__business_id = kwargs.get("business_id")
        self.__outlet_id = kwargs.get("outlet_id")
        self.__customer_id = kwargs.get("customer_id")
        self.__cashier_id = kwargs.get("cashier_id")
        self.__cash_session_id = kwargs.get("cash_session_id")
        self.__lines = kwargs.get("lines")
        self.__sku = kwargs.get("sku")
        self.__cart = kwargs.get("cart")
        self.__payment_method = kwargs.get("payment_method")
        self.__amount_paid = kwargs.get("amount_paid")
        self.__device_id = kwargs.get("device_id")
        self.__notes = kwargs.get("notes")
        self.__coupon_code = kwargs.get("coupon_code")
        self.__receipt_number = kwargs.get("receipt_number")
        self.__transaction_number = kwargs.get("transaction_number")

    # Getter methods
    def get_user__id(self):
        return self.__user__id
    def get_user_id(self):
        return self.__user_id
    def get_cashier_id(self):
        return self.__cashier_id
    def get_tenant_id(self):
        return self.__tenant_id
    def get_business_id(self):
        return self.__business_id
    def get_outlet_id(self):
        return self.__outlet_id
    def get_customer_id(self):
        return self.__customer_id
    def get_lines(self):
        return self.__lines
    def get_sku(self):
        return self.__sku
    def get_cart(self):
        return self.__cart
    def get_payment_method(self):
        return self.__payment_method
    def get_amount_paid(self):
        return self.__amount_paid
    def get_device_id(self):
        return self.__device_id
    def get_notes(self):
        return self.__notes
    def get_coupon_code(self):
        return self.__coupon_code
    def get_receipt_number(self):
        return self.__receipt_number
    def get_transaction_number(self):
        return self.__transaction_number
    def get_cash_session_id(self):
        return self.__cash_session_id
