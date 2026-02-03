
from decimal import Decimal, InvalidOperation
from flask import current_app, g, jsonify

from ...models.subscriber_model import Subscriber
from ...models.people_model import Agent
from ...models.admin.super_superadmin_model import Admin
from ...models.business_model import Business
from ...models.base_model import BaseModel

from ..logger import Log # import logging
from ...constants.service_code import (
    AGENT_PRE_TRANSACTION_VALIDATION_CHECKS,
    SUBSCRIBER_PRE_TRANSACTION_VALIDATION_CHECKS,
    SYSTEM_USERS
)
from ..json_response import prepared_response

from ...services.wallet_service import (
    place_hold,
    capture_hold,
    release_hold,
    refund_capture,
    get_agent_account
)
from ..agent_balance_keys import (
    keys_for_funding, 
    keys_for_hold, 
    keys_for_capture, 
    keys_for_release, 
    keys_for_refund
)


class PreProcessCheck(BaseModel):
    
    def __init__(self, business_id, account_type, admin_id):
        self.admin_id = admin_id
        self.business_id = business_id
        self.account_type = account_type
        
    ##############ACCOUNT PRE TRANSACTION CHECKS##################
    #1. perform pre-transaction checks
    def initial_processs_checks(self):
        """
        Performs comprehensive pre-transaction validation checks for an agent account.
        
        This method validates that an agent account meets all required conditions before
        allowing transaction processing. It checks multiple account status requirements
        and returns all validation errors at once for better user experience.
        
        Returns:
            tuple: A tuple containing (response_dict, status_code) where:
                - response_dict: JSON response with success status, message, and any errors
                - status_code: HTTP status code (200 for success, 400/404/500 for errors)
        
        Validation Checks Performed:
            1. Agent existence verification
            2. Account registration completion
            3. Account verification status
            4. PIN setup confirmation
            5. Basic KYC completion
            6. Business email verification
            7. Director information upload
            8. EDD questionnaire completion
        
        Raises:
            Exception: Any unexpected errors are caught and returned as INTERNAL_SERVER_ERROR
        
        Example Usage:
            ```python
            transaction_validator = TransactionValidator(agent_id="12345")
            response, status_code = transaction_validator.initial_transaction_checks()
            
            if transaction_validator is not None:
                return transaction_validator
            ```
        """
        
        log_tag = '[pre_process_checks.py][initial_processs_checks]'
        
        # check if business exist before proceeding to initiate transaction
        try:
            Log.info(f"{log_tag} checking if admin exist before performing action")
            business = Business.get_business_by_id(
                business_id=self.business_id,
            )
            if not business:
                Log.info(f"{log_tag} Business with ID: {self.business_id} does not exist")
                return prepared_response(False, "NOT_FOUND", f"Business with ID: {self.business_id} does not exist")
        except Exception as e:
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
        
        
        # check if admin exist if not business owner or superadmin before proceeding to initiate transaction
        if self.account_type not in (SYSTEM_USERS["SUPER_ADMIN"], SYSTEM_USERS["SYSTEM_OWNER"], SYSTEM_USERS["BUSINESS_OWNER"]):  
            try:
                Log.info(f"{log_tag} checking if admin exist before proceeding to initiate transaction")
                admin = Admin.get_by_id(
                    admin_id=self.admin_id,
                    business_id=self.business_id, 
                    is_logging_in=True
                )
                if not admin:
                    Log.info(f"{log_tag} Admin with ID: {self.admin_id} does not exist")
                    return prepared_response(False, "NOT_FOUND", f"Admin with ID: {self.admin_id} does not exist")
            except Exception as e:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred: {e}")
            
            
        try:
            agent = Agent.get_by_id(self.agent_id)
            errors = []
            required_fields = []
            
            # Check if agent exists
            if not agent:
                Log.info(f"{log_tag} Agent does not exist.")
                return prepared_response(False, "NOT_FOUND", "Agent does not exist.")
            
            # Get account_status
            account_status = agent.get("account_status")
            
            # Check if account_status is None
            if account_status is None:
                message = "The account registration is not complete!"
                Log.info(f"{log_tag} {message}")
                return prepared_response(False, "BAD_REQUEST", message)
            
            # Perform all validation checks
            # Check if all the required information needed for onboarding was provided during registration
            for check in AGENT_PRE_TRANSACTION_VALIDATION_CHECKS:
                status_item = next(
                    (value for item in account_status for key, value in item.items() if key == check['key']),
                    None
                )
                
                if not status_item or not status_item.get("status"):
                    errors.append(check['message'])
                    required_fields.append(check['key'])
                    Log.info(f"{log_tag} {check['message']}")
            
            # If there are validation errors, return them all
            if errors:
                return prepared_response(
                    False, 
                    "BAD_REQUEST", 
                    "Validation error(s) found. Please address all issues.", 
                    errors, 
                    required_fields, 
                    self.agent_id
                )
                
            # All pre-transaction checks passed. proceeding to initiate transaction.
            Log.info(f"{log_tag} All pre-transaction checks passed. proceeding to initiate transaction.")
            return None
            
            
        except Exception as e:
            Log.info(f"{log_tag} An unexpected error occurred. {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")
        
    #2 check if outlet has enough stock for make the transaction
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    















