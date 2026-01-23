import re
import os

from werkzeug.datastructures import FileStorage
from werkzeug.exceptions import BadRequest
from werkzeug.datastructures import FileStorage
import pycountry
from bson import ObjectId
from datetime import datetime
from zoneinfo import ZoneInfo

from marshmallow import (
    Schema, fields, validate, ValidationError, 
    validates, validates_schema
)

def validate_phone(value):
    if not isinstance(value, str):
        raise ValidationError("Phone number must be a string.")
    if len(value) < 10 or len(value) > 15:
        raise ValidationError("Phone number must be between 10 and 15 characters.")
    if not value.isdigit():
        raise ValidationError("Phone number must only contain digits.")
    return value

def validate_excel(value):
    """
    Custom validation for Excel files to ensure the uploaded file is a valid Excel document.
    This function checks for both .xls and .xlsx file extensions.
    """
    if value and not isinstance(value, FileStorage):
        raise ValidationError("The uploaded file must be a valid file.")

    if value:
        # Get the file extension
        file_extension = os.path.splitext(value.filename)[1].lower()

        # Validate the file extension
        if file_extension not in ['.xls', '.xlsx']:
            raise ValidationError("The file must be an Excel document (.xls or .xlsx).")

    return value

# Custom Validator for Tax (if required)
def validate_tax(value):
    if value and not re.match(r'^\d+(\.\d{1,2})?$', value):  # Ensure tax is a valid decimal number
        raise ValidationError("Tax must be a valid number with up to two decimal places.")
    return value

def validate_image(value):
    """
    Custom validation for image field to ensure it's a file, not just text.
    """
    if value and not isinstance(value, FileStorage):
        raise ValidationError("Image must be a valid file.")
    
    return value

def validate_future_on(value):
    if value:
        try:
            # Validate the date format and convert it to a datetime object
            expiry_date = datetime.strptime(value, '%Y-%m-%d')
            
            # Check if the expiry date is in the future
            if expiry_date < datetime.now():
                raise ValidationError("Date date has already passed, it must be a future date.")
        except ValueError:
            raise ValidationError("Invalid Date, must be in YYYY-MM-DD format.")

def validate_future_datetime_on(value: str):
    """
    Validate that `value` is a future date or datetime.

    Accepted formats:
      - 'YYYY-MM-DD'
      - 'YYYY-MM-DD HH:MM'
      - 'YYYY-MM-DD HH:MM:SS'
      - ISO 8601: 'YYYY-MM-DDTHH:MM[:SS][.ffffff][±HH:MM]' or trailing 'Z'

    If no timezone info is present, interpret in APP_TIMEZONE (default 'UTC').
    Date-only inputs are treated as midnight (00:00) of that day.
    """
    if not value:
        return  # nothing to validate

    tz = ZoneInfo(os.getenv("APP_TIMEZONE", "UTC"))
    raw = str(value).strip()

    # Try ISO-8601 first (normalize trailing Z)
    dt = None
    try:
        iso_candidate = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(iso_candidate)
        except Exception:
            # Fallback: try common patterns
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError
    except Exception:
        raise ValidationError(
            "Invalid date/time. Use YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS] (ISO 8601 also supported)."
        )

    # Attach timezone if naive
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)

    now = datetime.now(tz)

    # Must be strictly in the future
    if dt <= now:
        raise ValidationError("Date/time has already passed; it must be a future date/time.")

def validate_future_datetime_on_including_today(value: str):
    """
    Accepts:
      - YYYY-MM-DD
      - YYYY-MM-DD HH:MM
      - YYYY-MM-DD HH:MM:SS
      - ISO 8601 (incl. ...Z)
    Allows **today** (any time). Rejects dates strictly before today.
    """
    # Fingerprint message to confirm THIS function is running
    # (Comment out after verifying)
    # print("[validate_future_datetime_on] using TODAY-ALLOWED variant")

    if not value:
        return

    tz = ZoneInfo(os.getenv("APP_TIMEZONE", "UTC"))
    raw = str(value).strip()

    # Parse
    dt = None
    iso_candidate = raw.replace("Z", "+00:00")
    try:
        try:
            dt = datetime.fromisoformat(iso_candidate)
        except Exception:
            for fmt in (
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d %H:%M",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%dT%H:%M",
                "%Y-%m-%d",
            ):
                try:
                    dt = datetime.strptime(raw, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            raise ValueError
    except Exception:
        raise ValidationError(
            "Invalid date/time. Use YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS] (ISO 8601 also supported)."
        )

    # Attach timezone if naive
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)

    now = datetime.now(tz)

    # ✅ Allow same calendar day; reject only if strictly before today
    if dt.date() < now.date():
        raise ValidationError("Date/time has already passed; it must be today or a future date.")

    return True



def validate_past_date(value):
    if value:
        try:
            # Validate the date format and convert it to a datetime object
            manufactured_date = datetime.strptime(value, '%Y-%m-%d')
            
            # Check if the manufactured date is in the past
            if manufactured_date >= datetime.now():
                raise ValidationError("Date must be in the past.")
        except ValueError:
            raise ValidationError("Invalid Date, must be in YYYY-MM-DD format.")

def validate_date_format(value):
    if value:
        try:
            # Validate the date format and convert it to a datetime object
            datetime.strptime(value, '%Y-%m-%d')  # Ensure it follows YYYY-MM-DD format
        except ValueError:
            raise ValidationError("Invalid date format, must be in YYYY-MM-DD format.")
        
# Custom validator function to check if a string is a valid MongoDB ObjectId
def validate_objectid(value):
    if not ObjectId.is_valid(value):
        raise ValidationError(f"{value} is not a valid ID. Ensure you add a valid Item ID.")
       
def validate_store_url(value):
    if not isinstance(value, str):
        raise ValidationError("Store URL must be a string.")
    if len(value) < 5:
        raise ValidationError("Store URL must be at least 5 characters.")
    if not value.islower():
        raise ValidationError("Store URL must be all lowercase.")
    if ' ' in value:
        raise ValidationError("Store URL must not contain spaces.")
    if not re.match(r'^[a-z0-9]+$', value):
        raise ValidationError("Store URL must not contain special characters.")
    return value

def validate_password(value):
    if not isinstance(value, str):
        raise ValidationError("Password must be a string.")
    if len(value) < 8:
        raise ValidationError("Password must be at least 8 characters.")
    if not re.search(r'[A-Z]', value):
        raise ValidationError("Password must contain at least 1 uppercase letter.")
    if not re.search(r'[a-z]', value):
        raise ValidationError("Password must contain at least 1 lowercase letter.")
    if not re.search(r'[0-9]', value):
        raise ValidationError("Password must contain at least 1 digit.")
    if any(char in value for char in ['<', '>', '"', "'", '&']):
        raise ValidationError("Password must not contain any of the following characters: <, >, \", ', &.")
    return value

def create_permission_fields():
        """
        This function creates a validation rule for permission fields like view, add, edit, and delete.
        Ensures they are either '0' or '1'.
        """
        return validate.OneOf([0, 1])

def validate_iso2(value):
    """Validate that the given ISO 2-letter country code is valid."""
    if not pycountry.countries.get(alpha_2=value.upper()):
        raise ValidationError("Invalid ISO 2 code")

def validate_iso3(value):
    """Validate that the given ISO 3-letter country code is valid."""
    if not pycountry.countries.get(alpha_3=value.upper()):
        raise ValidationError("Invalid ISO 3 code")
    
def validate_payment_details(data):
    payment_mode = data.get('payment_mode')
    
    if not payment_mode:
        raise ValidationError("Payment mode is required")

    # Validate Wallet payment details
    if payment_mode.lower() == "wallet":
        missing_fields = []
        if not data.get("recipient_phone_number"):
            missing_fields.append("recipient_phone_number")
        if not data.get("mno"):
            missing_fields.append("mno")
        if missing_fields:
            raise ValidationError(f"For Wallet payment mode, the following field(s) are required: {', '.join(missing_fields)}.")
    
    # Validate Bank payment details
    elif payment_mode.lower() == "bank":
        required_fields = ["bank_name", "account_name", "account_number", "routing_number"]
        missing_fields = [field for field in required_fields if not data.get(field)]
        if missing_fields:
            raise ValidationError(f"For Bank payment mode, the following field(s) are required: {', '.join(missing_fields)}.")     

def validate_dob(dob):
    # Check if the length is within the defined range (min: 1, max: 20)
    if not (1 <= len(dob) <= 20):
        raise ValidationError("Date of Birth should be in the format YYYY-MM-DD")
    
    # Try to parse the date string into a datetime object
    try:
        # Expected date format: YYYY-MM-DD
        birth_date = datetime.strptime(dob, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("Invalid Date of Birth format. Please use the format YYYY-MM-DD.")
    
    # Calculate the person's age
    today = datetime.today()
    age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))

    # Check if the person is at least 18 years old
    if age < 18:
        raise ValidationError("You must be at least 18 years old.")
    
        # Check if the person is not older than 100 years
    if age > 100:
        raise ValidationError("You cannot be older than 100 years.")
    
     # Validate if the month and day are correct (e.g., February should not have 30 days)
    try:
        datetime(birth_date.year, birth_date.month, birth_date.day)  # This will raise an error for invalid month/day
    except ValueError:
        raise ValidationError("Invalid Date: Month and Day are not valid.")

    return dob

# Custom validation function to ensure the pin is numeric
def validate_pin(value):
    if not re.match(r'^\d+$', str(value)):  # Ensure the pin is composed of only digits
        raise ValidationError("PIN must be numeric.")
    if len(str(value)) < 4 or len(str(value)) > 12:  # Ensure length is between 4 and 12 digits
        raise ValidationError("PIN must be between 4 and 12 digits.")
      
def validate_strong_password(value):
    PASSWORD_REGEX = r"^((?=.*\d)(?=.*[a-z])(?=.*[A-Z]).{8,20})$"
    PASSWORD_REQUIREMENTS_MESSAGE = "At least 8 characters, one capital letter, one lowercase and one number."
    
    if not re.match(PASSWORD_REGEX, value):
        raise ValidationError(PASSWORD_REQUIREMENTS_MESSAGE)
    




