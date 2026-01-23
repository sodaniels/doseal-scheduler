# utils/hubtel_utils.py

import base64
import hmac
import hashlib
from flask import request
from ...utils.logger import Log
from ...config import Config


def get_hubtel_auth_token():
    """
    Generate Hubtel Basic Auth token.
    Equivalent to: Buffer.from(`${username}:${password}`).toString("base64")
    
    Returns:
        String - Base64 encoded auth token
    """
    username = Config.HUBTEL_USERNAME
    password = Config.HUBTEL_PASSWORD
    
    if not username or not password:
        Log.error("[get_hubtel_auth_token] Hubtel credentials not configured")
        return None
    
    # Create the Base64 encoded string
    auth_string = f"{username}:{password}"
    auth_bytes = auth_string.encode('utf-8')
    auth_b64 = base64.b64encode(auth_bytes).decode('utf-8')
    
    return auth_b64

def validate_hubtel_callback_amount(callback_amount, expected_amount, tolerance=0.01):
    """
    Validate that callback amount matches expected amount.
    
    Compares the amount received in the Hubtel callback with the amount
    stored in the payment record. Allows for small differences due to
    rounding or currency conversion.
    
    Args:
        callback_amount: Amount from Hubtel callback (float, int, or string)
        expected_amount: Expected amount from payment record (float, int, or string)
        tolerance: Allowed difference in amount (default 0.01 for 1 cent/pesewa)
        
    Returns:
        Bool - True if amounts match within tolerance, False otherwise
        
    Examples:
        >>> validate_hubtel_callback_amount(916.07, 916.07)
        True
        >>> validate_hubtel_callback_amount(916.07, 916.08, tolerance=0.01)
        True
        >>> validate_hubtel_callback_amount(916.07, 920.00)
        False
        >>> validate_hubtel_callback_amount("916.07", 916.07)
        True
        >>> validate_hubtel_callback_amount(None, 916.07)
        False
    """
    log_tag = "[validate_hubtel_callback_amount]"
    
    try:
        # Handle None/empty values
        if callback_amount is None or expected_amount is None:
            Log.warning(f"{log_tag} One or both amounts are None")
            return False
        
        # Convert to float
        try:
            callback_amount = float(callback_amount)
        except (ValueError, TypeError) as e:
            Log.error(f"{log_tag} Invalid callback_amount: {callback_amount} - {str(e)}")
            return False
        
        try:
            expected_amount = float(expected_amount)
        except (ValueError, TypeError) as e:
            Log.error(f"{log_tag} Invalid expected_amount: {expected_amount} - {str(e)}")
            return False
        
        # Calculate absolute difference
        difference = abs(callback_amount - expected_amount)
        
        # Check if within tolerance
        is_valid = difference <= tolerance
        
        if is_valid:
            if difference == 0:
                Log.info(f"{log_tag} Amount exact match: {callback_amount}")
            else:
                Log.info(f"{log_tag} Amount valid within tolerance: {callback_amount} ≈ {expected_amount} (diff: {difference})")
        else:
            Log.warning(f"{log_tag} Amount mismatch: {callback_amount} != {expected_amount} (diff: {difference}, tolerance: {tolerance})")
        
        return is_valid
        
    except Exception as e:
        Log.error(f"{log_tag} Error validating amount: {str(e)}", exc_info=True)
        return False
    
def verify_hubtel_callback(payload):
    """
    Verify Hubtel callback/webhook structure and data.
    
    Validates that the callback contains all required fields and has proper structure.
    
    Hubtel callback structure:
    {
        "ResponseCode": "0000",
        "Status": "Success",
        "Message": "...",
        "Data": {
            "ClientReference": "HUB-123456789",
            "CheckoutId": "...",
            "TransactionId": "...",
            "Amount": 916.07,
            ...
        }
    }
    
    Args:
        payload: Dict - The callback payload
        
    Returns:
        Bool - True if valid, False otherwise
    """
    log_tag = "[verify_hubtel_callback]"
    
    try:
        # Check if payload is a dictionary
        if not isinstance(payload, dict):
            Log.warning(f"{log_tag} Payload is not a dictionary. Type: {type(payload)}")
            return False
        
        # Check for required top-level fields
        required_fields = ['ResponseCode', 'Data']
        
        for field in required_fields:
            if field not in payload:
                Log.warning(f"{log_tag} Missing required field: {field}")
                return False
        
        # Validate ResponseCode exists and is a string
        response_code = payload.get('ResponseCode')
        if not response_code or not isinstance(response_code, str):
            Log.warning(f"{log_tag} Invalid ResponseCode: {response_code}")
            return False
        
        # Validate Data object exists and is a dictionary
        data = payload.get('Data')
        if not isinstance(data, dict):
            Log.warning(f"{log_tag} Data is not a dictionary. Type: {type(data)}")
            return False
        
        # Check for required fields in Data
        required_data_fields = ['ClientReference']
        
        for field in required_data_fields:
            if field not in data:
                Log.warning(f"{log_tag} Missing required field in Data: {field}")
                return False
        
        # Validate ClientReference
        client_reference = data.get('ClientReference')
        if not client_reference or not isinstance(client_reference, str):
            Log.warning(f"{log_tag} Invalid ClientReference: {client_reference}")
            return False
        
        # Additional validation for successful payments
        if response_code == "0000":
            # For successful payments, validate additional fields
            if not data.get('TransactionId'):
                Log.warning(f"{log_tag} Success callback missing TransactionId")
                # Don't fail, just warn - some callbacks might not have it yet
            
            if not data.get('Amount'):
                Log.warning(f"{log_tag} Success callback missing Amount")
        
        Log.info(f"{log_tag} Valid callback for reference: {client_reference}")
        return True
        
    except Exception as e:
        Log.error(f"{log_tag} Error validating callback: {str(e)}", exc_info=True)
        return False

def parse_hubtel_callback(payload):
    """
    Parse and extract Hubtel callback data into a structured format.
    
    Args:
        payload: Dict - The callback payload
        
    Returns:
        Dict - Parsed callback data with all relevant fields
    """
    log_tag = "[parse_hubtel_callback]"
    
    try:
        if not verify_hubtel_callback(payload):
            Log.error(f"{log_tag} Invalid callback payload")
            return None
        
        data = payload.get('Data', {})
        
        parsed = {
            # Top-level fields
            'response_code': payload.get('ResponseCode'),
            'status': payload.get('Status'),
            'message': payload.get('Message', ''),
            
            # Data fields
            'client_reference': data.get('ClientReference'),
            'checkout_id': data.get('CheckoutId'),
            'sales_invoice_id': data.get('SalesInvoiceId'),
            'transaction_id': data.get('TransactionId'),
            'amount': data.get('Amount'),
            'charges': data.get('Charges', 0),
            'description': data.get('Description'),
            
            # Customer details
            'customer_phone': data.get('CustomerPhoneNumber'),
            'customer_name': data.get('CustomerName'),
            'customer_email': data.get('CustomerEmail'),
            
            # Payment details
            'payment_details': data.get('PaymentDetails', {}),
            
            # Status flags
            'is_success': payload.get('ResponseCode') == "0000",
            'is_failed': payload.get('ResponseCode') != "0000",
        }
        
        Log.info(f"{log_tag} Parsed callback for reference: {parsed['client_reference']}")
        return parsed
        
    except Exception as e:
        Log.error(f"{log_tag} Error parsing callback: {str(e)}", exc_info=True)
        return None
    
def validate_hubtel_credentials():
    """
    Validate that all required Hubtel credentials are configured.
    
    Returns:
        Tuple (is_valid: bool, missing_fields: list)
    """
    
    required_fields = {
        'HUBTEL_CLIENT_ID': Config.HUBTEL_USERNAME,
        'HUBTEL_CLIENT_SECRET': Config.HUBTEL_PASSWORD,
        'HUBTEL_MERCHANT_ACCOUNT_NUMBER': Config.HUBTEL_MERCHANT_ACCOUNT_NUMBER,
        'HUBTEL_CALLBACK_URL': Config.HUBTEL_CALLBACK_URL,
    }
    
    missing = [field for field, value in required_fields.items() if not value]
    
    return len(missing) == 0, missing

def get_hubtel_response_code_message(response_code):
    """Get human-readable message for response codes."""
    response_codes = {
        "0000": "Success - Payment completed successfully",
        "1001": "Failed - Payment cancelled by user",
        "1002": "Failed - Insufficient funds",
        "1003": "Failed - Invalid account",
        "1004": "Failed - Payment timeout",
        "1005": "Failed - Transaction declined",
        "1006": "Failed - Invalid amount",
        "1007": "Failed - Duplicate transaction",
        "1008": "Failed - Service unavailable",
        "9999": "Failed - Unknown error",
    }
    return response_codes.get(response_code, f"Unknown response code: {response_code}")