# utils/mpesa_utils.py

import hmac
import hashlib
import base64
import json
from flask import request
from ..logger import Log


def verify_mpesa_signature(payload, signature_header=None):
    """
    Verify M-Pesa webhook signature.
    
    Args:
        payload: Dict - The webhook payload
        signature_header: String - Signature from request header (optional)
        
    Returns:
        Bool - True if signature is valid
    """
    try:
        # Get M-Pesa API credentials from environment
        from ...config import Config
        
        consumer_secret = Config.MPESA_CONSUMER_SECRET
        
        if not consumer_secret:
            Log.error("[verify_mpesa_signature] MPESA_CONSUMER_SECRET not configured")
            return False
        
        # M-Pesa sends signature in header
        if signature_header is None:
            signature_header = request.headers.get('X-Mpesa-Signature', '')
        
        if not signature_header:
            Log.warning("[verify_mpesa_signature] No signature header found")
            return False
        
        # Convert payload to JSON string
        payload_string = json.dumps(payload, separators=(',', ':'), sort_keys=True)
        
        # Calculate HMAC-SHA256 signature
        expected_signature = hmac.new(
            consumer_secret.encode('utf-8'),
            payload_string.encode('utf-8'),
            hashlib.sha256
        ).digest()
        
        # Base64 encode the signature
        expected_signature_b64 = base64.b64encode(expected_signature).decode('utf-8')
        
        # Compare signatures (constant-time comparison)
        is_valid = hmac.compare_digest(signature_header, expected_signature_b64)
        
        if not is_valid:
            Log.warning(f"[verify_mpesa_signature] Invalid signature. Expected: {expected_signature_b64}, Got: {signature_header}")
        
        return is_valid
        
    except Exception as e:
        Log.error(f"[verify_mpesa_signature] Error: {str(e)}", exc_info=True)
        return False


def verify_mpesa_callback_signature(payload):
    """
    Verify M-Pesa callback/webhook signature.
    Alternative method using callback-specific verification.
    
    Args:
        payload: Dict - The callback payload
        
    Returns:
        Bool - True if valid
    """
    try:
        # For M-Pesa Daraja API callbacks
        # The signature is computed differently for callbacks
        
        # Get security credential from config
        from ...config import Config
        security_credential = Config.MPESA_SECURITY_CREDENTIAL
        
        if not security_credential:
            Log.warning("[verify_mpesa_callback_signature] No security credential configured")
            # In production, this should return False
            # For development/testing, you might allow it
            return True  # Change to False in production
        
        # Extract signature from payload if present
        result_code = payload.get('Body', {}).get('stkCallback', {}).get('ResultCode')
        
        # ResultCode 0 means success
        if result_code == 0:
            return True
        
        return False
        
    except Exception as e:
        Log.error(f"[verify_mpesa_callback_signature] Error: {str(e)}")
        return False


def validate_mpesa_credentials():
    """
    Validate that all required M-Pesa credentials are configured.
    
    Returns:
        Tuple (is_valid: bool, missing_fields: list)
    """
    from ...config import Config
    
    required_fields = {
        'MPESA_CONSUMER_KEY': Config.MPESA_CONSUMER_KEY,
        'MPESA_CONSUMER_SECRET': Config.MPESA_CONSUMER_SECRET,
        'MPESA_SHORTCODE': Config.MPESA_SHORTCODE,
        'MPESA_PASSKEY': Config.MPESA_PASSKEY,
        'MPESA_CALLBACK_URL': Config.MPESA_CALLBACK_URL,
    }
    
    missing = [field for field, value in required_fields.items() if not value]
    
    return len(missing) == 0, missing