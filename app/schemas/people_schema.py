import re
import uuid
import pymongo
import json
import phonenumbers
from marshmallow import (
    Schema, fields, validate, ValidationError, pre_load, validates
)
from werkzeug.datastructures import FileStorage
from app.extensions.db import db

from datetime import datetime

from ..utils.validation import (
    validate_phone, validate_tax, validate_image, validate_future_on, 
    validate_past_date,  validate_objectid, validate_pin, validate_iso2
)

# Custom validator to check if the phone number is from the correct country
def validate_phone_number(value, tenant_id):
    country_iso_3 = get_country_iso_3_for_tenant(tenant_id)
    if not country_iso_3:
        raise ValidationError("Invalid tenant ID or tenant not found.")
    
    try:
        phone_number = phonenumbers.parse(value, country_iso_3)
        if not phonenumbers.is_valid_number(phone_number):
            raise ValidationError(f"Phone number {value} is not valid for country {country_iso_3}.")
    except phonenumbers.phonenumberutil.NumberParseException:
        raise ValidationError(f"Phone number {value} could not be parsed for country {country_iso_3}.")

@pre_load
def validate_username(self, data, **kwargs):
        """
        This method will be executed before the actual deserialization happens.
        We use this to perform the validation for the phone number (username).
        """
        tenant_id = data.get('tenant_id')
        username = data.get('username')
        
        if tenant_id and username:
            validate_phone_number(username, tenant_id)  # Call custom phone number validation
        return data


# Fetch valid tenant IDs from MongoDB Tenant collection
def get_valid_tenant_ids():
    try:
        tenants_collection = db.get_collection("tenants")
        tenants = tenants_collection.find({}, {"_id": 0, "id": 1})
        return [tenant["id"] for tenant in tenants]
    except Exception:
        return []
# Fetch the country_iso_3 from the Tenant collection for the given tenant_id
def get_country_iso_3_for_tenant(tenant_id):
    """
    Query the Tenant collection to get the country_iso_3 for a given tenant_id.
    """
    tenants_collection = db.get_collection("tenants")
    tenant = tenants_collection.find_one({"id": tenant_id})
    print(tenant)
    if tenant:
        return tenant.get("country_iso_3")
    return None


def validate_image(value):
        """
        Custom validation for image field to ensure it's a file, not just text.
        """
        if value and not isinstance(value, FileStorage):
            raise ValidationError("Image must be a valid file.")
        
        return value


# System User schema
class SystemUserSchema(Schema):
    
    username = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "First Name is required", "invalid": "First Name"}
    )
    
    display_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Last Name is required", "invalid": "First Name"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    outlet = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Outlet is required"}
    )
    role = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Role ID is required", "invalid": "Role ID"}
    )
    
    password = fields.Str(
        required=True,
        load_only=True,
        validate=validate.Length(min=8, max=100),
        error_messages={"required": "Password is required", "min_length": "Password must be at least 8 characters"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  
    )
    
    admin_id = fields.Str(
        required=False,
        allow_none=True,
    )
    
    phone = fields.Str(
        required=True,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    ################################################################
   
    date_of_birth = fields.Str(
        required=False,
        validate=validate_past_date, 
        error_messages={"required": "Date of Birth is required", "invalid": "Date of Birth"}
    )
    
    gender = fields.Str(
        validate=validate.OneOf(["Male", "Female"]),
    )
    
    marital_status = fields.Str(
        validate=validate.OneOf(["Married", "Unmarried", "Divorced"]),
    )
    
    alternative_phone = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    
    family_contact_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    twitter_link = fields.Str(
        required=False,
        allow_none=True,
    )
    id_type = fields.Str(
        required=False,
        allow_none=True,
    )
    id_number = fields.Str(
        required=False,
        allow_none=True,
    )
    permanent_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    current_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    account_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    account_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    bank_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    sort_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    branch = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    tax_payer_id = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )

    
    last_logged_in = fields.DateTime(required=False)
    
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)

class SystemUserUpdateSchema(Schema):
    system_user_id = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=36),
        error_messages={"required": "Customer ID is required", "invalid": "Customer ID"}
    )
    username = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "First Name is required", "invalid": "First Name"}
    )
    display_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"required": "Last Name is required", "invalid": "First Name"}
    )
    
    image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,  # Add the custom validation for image
        error_messages={"invalid": "Image must be a valid file"}
    )
    outlet = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=100),
        error_messages={"required": "Outlet is required"}
    )
    role = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Role ID is required", "invalid": "Role ID"}
    )
    password = fields.Str(
        required=True,
        load_only=True,
        validate=validate.Length(min=8, max=100),
        error_messages={"required": "Password is required", "min_length": "Password must be at least 8 characters"}
    )
    status = fields.Str(
        validate=validate.OneOf(["Active", "Inactive"]),
        default="Active"  
    )
    
    admin_id = fields.Str(
        required=False,
        allow_none=True,
    )
    
    phone = fields.Str(
        required=False,
        validate=validate_phone,
        error_messages={"required": "Phone number is required", "invalid": "Invalid phone number"}
    )
    email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid email address"}
    )
    ################################################################
   
    date_of_birth = fields.Str(
        required=False,
        validate=validate_past_date, 
        error_messages={"required": "Date of Birth is required", "invalid": "Date of Birth"}
    )
    
    gender = fields.Str(
        validate=validate.OneOf(["Male", "Female"]),
    )
    
    marital_status = fields.Str(
        validate=validate.OneOf(["Married", "Unmarried", "Divorced"]),
    )
    
    alternative_phone = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    
    family_contact_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate_phone,
    )
    twitter_link = fields.Str(
        required=False,
        allow_none=True,
    )
    id_type = fields.Str(
        required=False,
        allow_none=True,
    )
    id_number = fields.Str(
        required=False,
        allow_none=True,
    )
    permanent_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    current_address = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=255),
    )
    account_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    account_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    bank_name = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    sort_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    branch = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    tax_payer_id = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=2, max=100),
    )
    
    last_logged_in = fields.DateTime(required=False)
    
    created_at = fields.DateTime(dump_only=True)
    updated_at = fields.DateTime(dump_only=True)
# System User schema

# System Agent schema
class AgentRegistrationInitSchema(Schema):
    username = fields.Str(
        required=True, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    agreed_terms_and_conditions = fields.Bool(
        required=True, 
        error_messages={"invalid": "agreed_terms_and_conditions is required."}
    )
    device_id = fields.Str(
        required=True, 
        error_messages={"invalid": "Device Id is required."}
    )
    location = fields.Str(
        required=True, 
        error_messages={"invalid": "Location is required."}
    )
    
  
class AgentRegistrationVerifyOTPSchema(Schema):
    username = fields.Str(
        required=True, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    otp = fields.Str(
        required=True, 
        validate=validate.Length(min=6, max=6),
        error_messages={"required": "OTP is required", "invalid": "Invalid OTP"}
    )
    device_checksum = fields.Str(
        required=True,
        error_messages={"required": "Device Checksum required", "invalid": "Invalid Device Checksum"}
    )
   
class AgentRegistrationChoosePinSchema(Schema):
    
    pin = fields.Str(
        required=True, 
        validate=validate_pin
    )
 
class AgentRegistrationBasicKYCSchema(Schema):
    business_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"invalid": "Invalid Business name"}
    )
    business_email = fields.Email(
        required=True,
        validate=validate.Length(min=1, max=60),
        error_messages={"invalid": "Invalid Business Email"}
    )
    
    business_address = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"invalid": "Invalid Business address"} # must be postcode address. Therefore, first call the postcode api and allow user to select address
    )
    
    contact_person_fullname = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"invalid": "Invalid Contact Person Name"}
    )
    
    contact_person_phone_number = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=15),
        error_messages={"invalid": "Invalid Contact Person Name"}
    )
    referral_code = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=6, max=8),
        error_messages={"invalid": "Invalid Referral Code"}
    )

class AgentRegistrationBusinessKYCSchema(Schema):
    
    agent_id = fields.Str(
        required=True,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Agent ID is required", "invalid": "Agent ID of the agent"}
    )
    business_name = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"invalid": "Invalid Business name"}
    )
    business_email = fields.Email(
        required=True,
        validate=validate.Length(min=1, max=60),
        error_messages={"invalid": "Invalid Business Email"}
    )
    
    business_address = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"invalid": "Invalid Business address"} # must be postcode address. Therefore, first call the postcode api and allow user to select address
    )
    
    contact_person_fullname = fields.Str(
        required=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"invalid": "Invalid Contact Person Name"}
    )
    
    contact_person_phone_number = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=15),
        error_messages={"invalid": "Invalid Contact Person Name"}
    )
 
 
class AgentRegistrationBusinessEmailSchema(Schema):
   
    return_url = fields.Str(
        required=True,
        error_messages={"required": "Return is required", "invalid": "Return of the agent"}
    )
  
class AgentRegistrationVerifyEmailSchema(Schema):
    
    token = fields.Str(
        required=True,
        error_messages={"required": "Token is required", "invalid": "Token of the regsitration session the agent"}
    )
    
    user_id = fields.Str(
        required=True,
        error_messages={"required": "User ID is required", "invalid": "User ID of the agent"}
    )
 
class AgentRegistrationDirectorSchema(Schema):
    
    fullname = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=200),
        error_messages={"invalid": "Invalid full name"}
    )
    
    phone_number = fields.Str(
        required=True,
        validate=validate.Length(min=10, max=17),
        error_messages={"invalid": "Invalid phone number"}
    )
    
    id_type = fields.Str( 
        required=False,
        allow_none=True,
        validate=validate.OneOf(["Passport", "Driving Licence", "National Identity Card"]),
        error_messages={"invalid": "Invalid ID type"}
    )
    
    id_number = fields.Str(
        required=False,
        allow_none=True,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid ID number"}
    )
    
    id_front_image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "ID Front must be a valid file"}
    )
    
    id_back_image = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "ID Back must be a valid file"}
    )
    proof_of_address = fields.Raw(
        required=False,
        allow_none=True,
        validate=validate_image,
        error_messages={"invalid": "Proof of address must be a valid file"}
    )
 
class AgentRegistrationUpdateEddQuestionnaireSchema(Schema):
    
    agent_id = fields.Str(
        required=False,
        allow_none=True,
    )
 
class AgentLoginInitSchema(Schema):
    
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate_iso2],
        error_messages={"required": "Country ISO2 is required", "invalid": "Invalid Country ISO2"}
    )
    username = fields.Str(
        required=True, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    device_id = fields.Str(
        required=True, 
        error_messages={"invalid": "Device Id is required."}
    )
    location = fields.Str(
        required=True, 
        error_messages={"invalid": "Location is required."}
    )
    pin = fields.Str(
        required=False, 
        allow_none=True
    )
    
class AgentLoginExecuteSchema(Schema):
    
    country_iso_2 = fields.Str(
        required=True,
        validate=[validate_iso2],
        error_messages={"required": "Country ISO2 is required", "invalid": "Invalid Country ISO2"}
    )
    username = fields.Str(
        required=True, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    otp = fields.Str(
        required=True, 
        validate=validate.Length(equal=6),
        error_messages={"required": "OTP is required", "invalid": "OTP is not valid"}
    )
    device_checksum = fields.Str(
        required=True, 
        error_messages={"required": "Device Checksum is required", "invalid": "Device Checksum is not valid"}
    )
    
     
    
    

 
     
class AgentSchema(Schema):
    
    @validates('directors')
    def validate_directors(self, directors):
        if directors:
            for director in directors:
                # Check if any field is provided, and if so, all must be provided
                if any(director.get(field) is not None for field in ["fullname", "phone_number", "id_type", "id_number", "id_front_image", "id_back_image"]):
                    missing_fields = [field for field in ["fullname", "phone_number", "id_type", "id_number", "id_front_image", "id_back_image"] if director.get(field) is None]
                    if missing_fields:
                        raise ValidationError(f"The following fields are required when any director field is provided: {', '.join(missing_fields)}")
        return directors


    tenant_id = fields.Int(
        required=False,
        validate=validate.OneOf(get_valid_tenant_ids()),  # Dynamically set the valid tenant IDs
        error_messages={"required": "Tenant ID is required", "invalid": "Invalid Tenant ID"}
    )
    
    business_id = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Business User ID"}
    )
    username = fields.Str(
        required=False, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    alt_phoneNumber = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=17),
        error_messages={"invalid": "Invalid alternate phone number"}
    )
    alt_email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid alternate email"}
    )
    first_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid first name"}
    )
    middle_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid middle name"}
    )
    last_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid last name"}
    )
    date_of_birth = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=10),  # Example length for date
        error_messages={"invalid": "Invalid date of birth"}
    )
    post_code = fields.Dict(
        required=False,
        error_messages={"invalid": "Invalid postal code object"}
    )
    identification = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
        ),
        required=False,
        allow_none=True,
    )
    device_uuid = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid device UUID"}
    )
    request = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid request"}
    )
    remote_iP = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid remote IP"}
    )
    last_login = fields.DateTime(
        required=False,
        default=datetime.utcnow,
        error_messages={"invalid": "Invalid last login time"}
    )
    referrer = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid referrer"}
    )
    referral_code = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid referral code"}
    )
    referrals = fields.List(fields.Str(), required=False, error_messages={"invalid": "Invalid referrals"})
    transactions = fields.Int(
        required=False,
        error_messages={"invalid": "Invalid number of transactions"}
    )
    balance = fields.Float(
        required=False,
        default=0,
        error_messages={"invalid": "Invalid balance"}
    )
    balance_update_status = fields.Str(
        required=False,
        validate=validate.OneOf(["BalanceCreated", "BalanceApproved"]),
        error_messages={"invalid": "Invalid balance update status"}
    )
    account_status = fields.List(
        fields.Dict(
            required=False,
            fields={
                "account_verified": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "choose_pin": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "basic_kyc_added": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "business_email_verified": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "uploaded_agent_id_info": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "uploaded_director_id_info": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "registration_completed": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "registration_completed": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "onboarding_in_progress": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                "onboarding_completed": fields.Dict(
                    required=False,
                    allow_none=True,
                    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
                ),
                
            }
        )
    )
    business = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            validate={
                "business_name": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=200),
                ),
                "business_email": fields.Email(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=60),
                ),
                "business_address": fields.Str( #business address must contain postCode in the object
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=200),
                ),
                "contact_person_fullname": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=100),
                ),
                "contact_person_phone_number": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=17),
                ),
            },
        ),
    )
    
    directors = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            validate={
                "fullname": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=200),
                ),
                "phone_number": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=10, max=17),
                ),
                "id_type": fields.Str( 
                    required=False,
                    allow_none=True,
                    validate=validate.OneOf(["Passport", "Driving Licence", "National Identity Card"]),
                ),
                "id_type": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate_future_on,
                ),
                "id_number": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=50),
                ),
                "id_front_image": fields.Raw(
                    required=False,
                    allow_none=True,
                    validate=validate_image,
                    error_messages={"invalid": "ID Front must be a valid file"}
                ),
                "id_front_image_file_path": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=200),
                ),
                "id_back_image": fields.Raw(
                    required=False,
                    allow_none=True,
                    validate=validate_image,
                    error_messages={"invalid": "ID back must be a valid file"}
                ),
                "id_back_image_file_path": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=200),
                ),
              
            },
        ),
    )
    
    uploads = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
            validate={
                "edd_questionnaire": fields.Raw(
                    required=False,
                    allow_none=True,
                    validate=validate_image,
                    error_messages={"invalid": "EDD Questionnaire must be a valid file"}
                ),
                "edd_questionnaire_file_path": fields.Str(
                    required=False,
                    allow_none=True,
                    validate=validate.Length(min=1, max=200),
                ),
              
            },
        ),
    )
    
    
    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
    update_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            valid_ids = get_valid_tenant_ids()
            self.fields["tenant_id"].validate.append(
                validate.OneOf(valid_ids, error="Invalid tenant ID.")
            )
        except Exception:
            pass  # You may log this if needed

class AgentUpdateSchema(Schema):
    agent_id = fields.Str(
        required=True,
        validate=validate.Length(min=8, max=8),
        error_messages={"invalid": "Agent ID must be a valid string"}
    )
    tenant_id = fields.Int(
        required=False,
        validate=validate.OneOf(get_valid_tenant_ids()),  # Dynamically set the valid tenant IDs
        error_messages={"required": "Tenant ID is required", "invalid": "Invalid Tenant ID"}
    )
    
    business_id = fields.Str(
        required=False,
        validate=[validate.Length(min=1, max=36), validate_objectid],
        error_messages={"required": "Business ID is required", "invalid": "Business User ID"}
    )
    username = fields.Str(
        required=False, 
        error_messages={"required": "Phone number (username) is required", "invalid": "Invalid phone number"}
    )
    alt_phoneNumber = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=20),
        error_messages={"invalid": "Invalid alternate phone number"}
    )
    alt_email = fields.Email(
        required=False,
        validate=validate.Length(max=100),
        error_messages={"invalid": "Invalid alternate email"}
    )
    first_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid first name"}
    )
    middle_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid middle name"}
    )
    last_name = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=50),
        error_messages={"invalid": "Invalid last name"}
    )
    date_of_birth = fields.Str(
        required=False,
        validate=validate.Length(min=1, max=10),  # Example length for date
        error_messages={"invalid": "Invalid date of birth"}
    )
    post_code = fields.Dict(
        required=False,
        error_messages={"invalid": "Invalid postal code object"}
    )
    identification = fields.List(
        fields.Dict(
            required=False,
            allow_none=True,
        ),
        required=False,
        allow_none=True,
    )
    device_uuid = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid device UUID"}
    )
    request = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid request"}
    )
    remote_iP = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid remote IP"}
    )
    last_login = fields.DateTime(
        required=False,
        default=datetime.utcnow,
        error_messages={"invalid": "Invalid last login time"}
    )
    referrer = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid referrer"}
    )
    referral_code = fields.Str(
        required=False,
        error_messages={"invalid": "Invalid referral code"}
    )
    referrals = fields.List(fields.Str(), required=False, error_messages={"invalid": "Invalid referrals"})
    transactions = fields.Int(
        required=False,
        error_messages={"invalid": "Invalid number of transactions"}
    )
    balance = fields.Float(
        required=False,
        default=0,
        error_messages={"invalid": "Invalid balance"}
    )
    balance_update_status = fields.Str(
        required=False,
        validate=validate.OneOf(["BalanceCreated", "BalanceApproved"]),
        error_messages={"invalid": "Invalid balance update status"}
    )
    created_at = fields.DateTime(dump_only=True, default=datetime.utcnow)
    update_at = fields.DateTime(dump_only=True, default=datetime.utcnow)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            valid_ids = get_valid_tenant_ids()
            self.fields["tenant_id"].validate.append(
                validate.OneOf(valid_ids, error="Invalid tenant ID.")
            )
        except Exception:
            pass  # You may log this if needed
          
        
# System Agent schema
class BusinessIdQuerySchema(Schema):
    business_id = fields.Str(required=True,validate=validate_objectid,  description="The business_id of the store to fetch details.")

class SystemUserIdQuerySchema(Schema):
    system_user_id = fields.Str(required=True, validate=validate_objectid, description="System User ID of the System User to fetch detail.")

class AgentIdQuerySchema(Schema):
    agent_id = fields.Str(required=False, allow_none=True)
