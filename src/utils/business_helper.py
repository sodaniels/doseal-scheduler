import os
from src.utils.generic_utilities import generate_business_payload
from src.utils.requests_utility import RequestUtility

from app.utils.redis import (
    set_redis, get_redis
)

class BusinessHelper(object):
    
    def __init__(self):
        self.request_utility = RequestUtility()
    
    def create_business(self, tenant_id=None, business_name=None, start_date=None, business_contact=None, 
                        country=None, city=None, state=None, postcode=None, currency=None, alternate_contact_number=None, 
                        time_zone=None, first_name=None, last_name=None, username=None, password=None, email=None, 
                        store_url=None, package=None, return_url=None, website=None, **kwargs):
        
        business_payload = generate_business_payload()
        
        if not tenant_id:
            tenant_id = business_payload["tenant_id"]
        if not business_name:
            business_name = business_payload["business_name"]
        if not start_date:
            start_date = business_payload["start_date"]
        if not business_contact:
            business_contact = business_payload["business_contact"]
        if not country:
            country = business_payload["country"]
        if not city:
            city = business_payload["city"]
        if not state:
            state = business_payload["state"]
        if not postcode:
            postcode = business_payload["postcode"]
        if not currency:
            currency = business_payload["currency"]
        if not alternate_contact_number:
            alternate_contact_number = business_payload["alternate_contact_number"]
        if not time_zone:
            time_zone = business_payload["time_zone"]
        if not first_name:
            first_name = business_payload["first_name"]
        if not last_name:
            last_name = business_payload["last_name"]
        if not username:
            username = business_payload["username"]
        if not password:
            password = business_payload["password"]
        if not email:
            email = business_payload["email"]
        if not store_url:
            store_url = business_payload["store_url"]
        if not package:
            package = business_payload["package"]
        if not return_url:
            return_url = business_payload["return_url"]
        if not website:
            website = business_payload["website"]
            
        payload = dict()
        payload["tenant_id"] = tenant_id
        payload["business_name"] = business_name
        payload["start_date"] = start_date
        payload["business_contact"] = business_contact
        payload["country"] = country
        payload["city"] = city
        payload["state"] = state
        payload["postcode"] = postcode
        payload["currency"] = currency
        payload["alternate_contact_number"] = alternate_contact_number
        payload["time_zone"] = time_zone
        payload["first_name"] = first_name
        payload["last_name"] = last_name
        payload["username"] = username
        payload["password"] = password
        payload["email"] = email
        payload["store_url"] = store_url
        payload["package"] = package
        payload["website"] = website
        payload["return_url"] = return_url
        
        payload.update(kwargs)
        
        response = self.request_utility.post('register', payload=payload)
        
        response_data = response.json()
        # Add email to the response data
        response_data["email"] = email
        
        set_redis('automated_test_email', email)
        set_redis('automated_test_password', password)

        
        return response_data
        