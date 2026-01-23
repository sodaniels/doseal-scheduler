import os
import re
import secrets
import random
import string
import urllib.parse
from ..extensions.db import db
from datetime import datetime
from typing import Optional
from bson import ObjectId
from pymongo.collection import Collection
from pymongo import ReturnDocument


def generate_client_id(length=32):
    """Generate a random client_id of the specified length (default 32 characters)."""
    characters = string.ascii_letters + string.digits
    return ''.join(secrets.choice(characters) for _ in range(length))

def generate_client_secret(length=100):
    """Generate a random client_secret of the specified length (default 100 characters)."""
    characters = string.ascii_letters + string.digits  # Exclude special characters
    return ''.join(secrets.choice(characters) for _ in range(length))

def generate_temporary_password(length=100):
    """Generate a random password of the specified length (default 100 characters)."""
    characters = string.ascii_letters + string.digits  # Exclude special characters
    return ''.join(secrets.choice(characters) for _ in range(length))

# Function to generate a secure reset token
def generate_reset_token(base_url, token):
    # Create a secure random token
    # Construct the reset URL
    query_params = {"token": token}
    reset_url = f"{base_url}reset-password?{urllib.parse.urlencode(query_params)}"
    return reset_url

def generate_confirm_email_token(return_url, token):
    # Create a secure random token
    # Construct the reset URL
    base_url = os.getenv("BACK_END_BASE_URL")
    # return_url = os.getenv("FRONT_END_BASE_URL") + '/confirm-account-status'
    query_params = {"token": token, "return_url": return_url }
    reset_url = f"{base_url}/confirm-account?{urllib.parse.urlencode(query_params)}"
    return reset_url

def generate_return_url_with_payload(return_url, query_params):
    """This function generates the return url with payload

    Args:
        return_url (_type_): _description_
        query_params (_type_): _description_

    Returns:
        _type_: _description_
    """
    return_url_payload = f"{return_url}?{urllib.parse.urlencode(query_params)}"
    return return_url_payload

def generate_store_code(prefix_length=3, number_length=8):
    # Generate a random 3-letter prefix (you can adjust the length as needed)
    prefix = ''.join(random.choices(string.ascii_uppercase, k=prefix_length))
    
    # Generate a random 8-digit number
    random_number = ''.join(random.choices(string.digits, k=number_length))
    
    # Combine the random prefix and random number
    return f"{prefix}-{random_number}"

def generate_gift_card_code(length=16):
    """
    Generate a random alphanumeric string for a gift card code.

    Args:
    - length: The length of the gift card code to generate. Default is 16.

    Returns:
    - A random alphanumeric string that serves as the gift card code.
    """
    # Characters allowed in the gift card code (alphanumeric)
    characters = string.ascii_uppercase + string.digits
    
    # Generate the gift card code by randomly selecting characters
    gift_card_code = ''.join(random.choice(characters) for _ in range(length))
    
    return gift_card_code

def generate_coupons(num_coupons=10, code_length=8):
    """
    Generate a list of unique coupon codes.

    Args:
    - num_coupons: Number of coupon codes to generate (default is 10).
    - code_length: Length of each coupon code (default is 8).

    Returns:
    - A list of generated coupon codes.
    """
    coupons = set()  # Using a set to avoid duplicates
    
    while len(coupons) < num_coupons:
        # Generate a random coupon code with uppercase letters and digits
        coupon_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=code_length))
        coupons.add(coupon_code)  # Add coupon to the set (duplicates will be ignored)
    
    return list(coupons)

def generate_agent_id():
    # Generate an 8-digit number as a string
    return str(random.randint(10000000, 99999999))

def generate_otp():
    '''Generate a random 6-digit code'''
    return random.randint(100000, 999999)

def generate_promo_code():
    # Generate a random alphanumeric string of length 6 
    promo_code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return promo_code

def clean_phone_number(phone_number):
    # Remove all occurrences of '(', ')', and '-'
    cleaned_number = re.sub(r'[\(\)-]', '', phone_number)
    return cleaned_number

def generate_registration_verification_token(base_url, agent_id, token):
    # Create a secure random token
    # Construct the reset URL
    query_params = {"token": token, "user_id": agent_id}
    reset_url = f"{base_url}agent/api/v1/registration/verify-email?{urllib.parse.urlencode(query_params)}"
    return reset_url

def generate_subscriber_registration_verification_token(base_url, subscriber_id, token):
    # Create a secure random token
    # Construct the reset URL
    query_params = {"token": token, "user_id": subscriber_id}
    reset_url = f"{base_url}subscriber/api/v1/registration/verify-email?{urllib.parse.urlencode(query_params)}"
    return reset_url

def generate_return_url_with_payload(return_url, query_params):
    """This function generates the return url with payload

    Args:
        return_url (_type_): _description_
        query_params (_type_): _description_

    Returns:
        _type_: _description_
    """
    return_url_payload = f"{return_url}?{urllib.parse.urlencode(query_params)}"
    return return_url_payload

def generate_internal_reference(type="DR"):
    # Get current date and time in the required format
    current_date = datetime.utcnow()
    formatted_date = current_date.strftime('%Y%m%d%H%M%S')

    # Generate a random 6-digit number
    random_number = random.randint(100000, 999999)

    # Create the unique ID
    unique_id = f'{type}_{formatted_date}{random_number}'
    return unique_id

def generate_secure_referral_code(length=6):
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))

def generate_sku(
    business_id: str,
    prefix: str = "DL",
    width: int = 10,
    sequence_name: Optional[str] = None,
) -> str:
    """
    Generate a unique, sequential SKU for a given business.

    Pattern: <PREFIX><NUMBER>
    Example: DL0000000001, DL0000000002, ...

    Uses a `sku_counters` collection in MongoDB:
        { _id, business_id, sequence_name, prefix, seq }

    Args:
        business_id: Business ID as string or ObjectId.
        prefix: SKU prefix (default "DL").
        width: Zero-padding width for the numeric part (default 10).
        sequence_name: Optional logical name ("product", "variant", etc.).
                      Default: "product".

    Returns:
        A unique SKU string.
    """
    if not business_id:
        raise ValueError("business_id is required to generate SKU.")

    if not isinstance(business_id, ObjectId):
        try:
            business_id = ObjectId(business_id)
        except Exception as e:
            raise ValueError(f"Invalid business_id: {business_id}") from e

    if not sequence_name:
        sequence_name = "product"

    # 🔴 IMPORTANT: use your wrapper's get_collection
    counters = db.get_collection("sku_counters")

    counter_doc = counters.find_one_and_update(
        {
            "business_id": business_id,
            "sequence_name": sequence_name,
            "prefix": prefix,
        },
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )

    seq_number = counter_doc["seq"]
    sku = f"{prefix}{seq_number:0{width}d}"
    return sku





