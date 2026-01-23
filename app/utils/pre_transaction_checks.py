
from decimal import Decimal, InvalidOperation
from flask import current_app, g, jsonify

from ..models.subscriber_model import Subscriber
from ..models.people_model import Agent

from .logger import Log # import logging
from ..constants.service_code import (
    AGENT_PRE_TRANSACTION_VALIDATION_CHECKS,
    SUBSCRIBER_PRE_TRANSACTION_VALIDATION_CHECKS
)
from .json_response import prepared_response

from ..services.wallet_service import (
    place_hold,
    capture_hold,
    release_hold,
    refund_capture,
    get_agent_account
)
from .agent_balance_keys import (
    keys_for_funding, 
    keys_for_hold, 
    keys_for_capture, 
    keys_for_release, 
    keys_for_refund
)


class PreTransactionCheck:
    
    def __init__(self, business_id, agent_id=None, subscriber_id=None,):
        self.agent_id = agent_id
        self.business_id = business_id
        self.subscriber_id = subscriber_id
        
    ##############AGENT PRE TRANSACTION CHECKS##################
    #perform pre-transaction checks
    def initial_transaction_checks(self):
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
        
        log_tag = '[PreTransactionCheck][pre_transaction_checks]'
            
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
        
    # check if agent has enough balance to cover transaction
    def agent_has_sufficient_available(self, amount) -> bool:
        """Check whether the agent's *available* balance is sufficient for a requested amount.
        This is a **pre-flight** check that reads the agent account (via
        `get_agent_account(business_id, agent_id)`), parses money values using
        `Decimal`, logs both the available balance and requested amount to two
        decimal places, and returns `True` iff `available >= amount`.

        The authoritative enforcement still happens inside the wallet operation
        (e.g., `place_hold`), which runs in a transaction and prevents negative
        """
        log_tag = "[pre_transaction_checks][agent_has_sufficient_availables]"
        try:
            doc = get_agent_account(business_id=self.business_id, agent_id=self.agent_id)
            if not doc:
                Log.warning(f"{log_tag} account not found for business_id={self.business_id} agent_id={self.agent_id}")
                return False

            available_raw = doc.get("available")
            if available_raw is None:
                Log.warning(f"{log_tag} 'available' field missing in account doc")
                return False

            # Parse amounts safely
            available = Decimal(str(available_raw))
            needed    = Decimal(str(amount)).quantize(Decimal("0.01"))

            # Nice logging (no int() on money)
            Log.info(f"available: {available:,.2f}")
            Log.info(f"amount:    {needed:,.2f}")

            return available >= needed

        except (InvalidOperation, ValueError, TypeError) as e:
            Log.error(f"{log_tag} invalid numeric value(s): {e}")
            return False
        except Exception as e:
            Log.error(f"{log_tag} unexpected error while comparing amounts: {e}")
            return False

    ##############SUBSCRIBER PRE TRANSACTION CHECKS##################
    
    def initial_subscriber_transaction_checks(self):
        """
        Performs comprehensive pre-transaction validation checks for a subscriber account.

        This method validates that a subscriber account meets all required conditions before
        allowing transaction processing. It checks multiple account status requirements
        and returns all validation errors at once for better user experience.

        Returns:
            tuple | None: A tuple (response_dict, status_code) from `prepared_response`
                        when there are errors, or None when all checks pass.

        Validation Checks Performed (driven by SUBSCRIBER_PRE_TRANSACTION_VALIDATION_CHECKS):
            1. Subscriber existence verification
            2. Account registration completion
            3. Account verification status
            4. PIN setup confirmation
            5. Basic KYC completion
            6. Email verification
            7. Required document uploads
            8. Any extra onboarding steps (EDD, etc.)

        Raises:
            Exception: Any unexpected errors are caught and returned as INTERNAL_SERVER_ERROR

        Example Usage:
            validator = TransactionValidator(subscriber_id="12345")
            result = validator.initial_subscriber_transaction_checks()
            if result is not None:
                return result  # (response_dict, status_code) from prepared_response
            # proceed with transaction...
        """
        log_tag = "[PreTransactionCheck][subscriber_pre_checks]"
        try:
            # 1) Fetch subscriber (replace with your actual accessor)
            subscriber = Subscriber.get_by_id(
                business_id=self.business_id, 
                subscriber_id=self.subscriber_id
            )

            errors = []
            required_fields = []

            # 2) Existence
            if not subscriber:
                Log.info(f"{log_tag} Subscriber does not exist. id={self.subscriber_id}")
                return prepared_response(False, "NOT_FOUND", "Subscriber does not exist.")

            # 3) Account status presence
            account_status = subscriber.get("account_status")
            if account_status is None:
                message = "The account registration is not complete!"
                Log.info(f"{log_tag} {message} id={self.subscriber_id}")
                return prepared_response(False, "BAD_REQUEST", message)

            # 4) Run all configured checks
            # Expected structure of account_status: list[ { key: { status: bool, ... } }, ... ]
            for check in SUBSCRIBER_PRE_TRANSACTION_VALIDATION_CHECKS:
                status_item = next(
                    (value for item in account_status for key, value in item.items() if key == check["key"]),
                    None
                )
                if not status_item or not status_item.get("status"):
                    errors.append(check["message"])
                    required_fields.append(check["key"])
                    Log.info(f"{log_tag} {check['message']} id={self.subscriber_id}")

            # 5) Aggregate validation errors
            if errors:
                return prepared_response(
                    False,
                    "BAD_REQUEST",
                    "Validation error(s) found. Please address all issues.",
                    errors,
                    required_fields,
                    self.subscriber_id
                )

            # 6) Success — all checks passed
            Log.info(f"{log_tag} All pre-transaction checks passed. id={self.subscriber_id}")
            return None

        except Exception as e:
            Log.info(f"{log_tag} An unexpected error occurred. {str(e)} id={getattr(self, 'subscriber_id', None)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    
    















