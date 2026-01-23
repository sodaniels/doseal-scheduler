class RequestMaker:
    def __init__(self, **kwargs):
        self.__payment_mode = kwargs.get("payment_mode")
        self.__source = kwargs.get("source")
        self.__destination = kwargs.get("destination")
        self.__receive_amount = kwargs.get("receive_amount")
        self.__send_amount = kwargs.get("send_amount")
        self.__tenant_id = kwargs.get("tenant_id")
        self.__transfer_type = kwargs.get("transfer_type")
        self.__beneficiary_account = kwargs.get("beneficiary_account")
        self.__sender_account = kwargs.get("sender_account")
        self.__extra = kwargs.get("extra")
        self.__amount_details = kwargs.get("amount_details")
        self.__receiver_info = kwargs.get("receiver_info")
        self.__fraud_kyc = kwargs.get("fraud_kyc")
        self.__payment_type = kwargs.get("payment_type")
        self.__description = kwargs.get("description")
        self.__mno = kwargs.get("mno")
        self.__referrer = kwargs.get("referrer")
        self.__details = kwargs.get("details")
        self.__incentive = kwargs.get("incentive")
        self.__callback_url = kwargs.get("callback_url")
        self.__recipient_account = kwargs.get("recipient_account")
        self.__routing_number = kwargs.get("routing_number")
        self.__bank_name = kwargs.get("bank_name")
        self.__business_id = kwargs.get("business_id")
        self.__sender_id = kwargs.get("sender_id")
        self.__beneficiary_id = kwargs.get("beneficiary_id")
        self.__agent_id = kwargs.get("agent_id")
        self.__user_id = kwargs.get("user_id")
        self.__user__id = kwargs.get("user__id")
        self.__subscriber_id = kwargs.get("subscriber_id")
        self.__username = kwargs.get("username")
        self.__medium = kwargs.get("medium")
        self.__transaction_type = kwargs.get("transaction_type")
        self.__account_id = kwargs.get("account_id")

    # Getter methods
    def get_payment_mode(self):
        return self.__payment_mode

    def get_send_amount(self):
        return self.__send_amount

    def get_source(self):
        return self.__source

    def get_destination(self):
        return self.__destination

    def get_receive_amount(self):
        return self.__receive_amount

    def get_tenant_id(self):
        return self.__tenant_id

    def get_transfer_type(self):
        return self.__transfer_type

    def get_beneficiary_account(self):
        return self.__beneficiary_account

    def get_sender_account(self):
        return self.__sender_account

    def get_extra(self):
        return self.__extra

    def get_amount_details(self):
        return self.__amount_details

    def get_fraud_kyc(self):
        return self.__fraud_kyc

    def get_payment_type(self):
        return self.__payment_type

    def get_description(self):
        return self.__description

    def get_mno(self):
        return self.__mno

    def get_referrer(self):
        return self.__referrer

    def get_details(self):
        return self.__details

    def get_callback_url(self):
        return self.__callback_url

    def get_recipient_account(self):
        return self.__recipient_account

    def get_routing_number(self):
        return self.__routing_number

    def get_bank_name(self):
        return self.__bank_name
    
    def get_business_id(self):
        return self.__business_id
    
    def get_sender_id(self):
        return self.__sender_id
    
    def get_beneficiary_id(self):
        return self.__beneficiary_id
    
    def get_agent_id(self):
        return self.__agent_id
    
    def get_user_id(self):
        return self.__user_id
    
    def get_user__id(self):
        return self.__user__id
    
    def get_subscriber_id(self):
        return self.__subscriber_id
    
    def get_created_by(self):
        return self.__user__id
    
    def get_username(self):
        return self.__username
    
    def get_medium(self):
        return self.__medium
    
    def get_transaction_type(self):
        return self.__transaction_type
    
    def get_account_id(self):
        return self.__account_id
    
    
        
