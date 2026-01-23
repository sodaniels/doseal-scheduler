import os
from src.utils.generic_utilities import generate_business_payload
from src.utils.intermex.requests_utility import RequestUtility
from app.models.people_model import Agent
from app.utils.redis import (
    get_redis, set_redis
)

class ApiServiceHelper(object):
    
    def __init__(self):
        self.request_utility = RequestUtility()
    
    def create_business_(self, tenant_id=None, business_name=None, start_date=None, business_contact=None, 
                        country=None, city=None, state=None, postcode=None, currency=None, alternate_contact_number=None, 
                        time_zone=None, first_name=None, last_name=None, username=None, password=None, email=None, 
                        store_url=None, package=None, return_url=None, website=None, **kwargs):
        
        business_payload = generate_business_payload()
        
        if not tenant_id:
            tenant_id = 1
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

        
        return response_data
        
    def registration_initiate(self, payload, bearer_token=None, expected_status_code=200):

            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            
            response = self.request_utility.post(
                f'intermex/api/v1/registration-initiate', 
                payload=payload,
                headers=headers,
                expected_status_code=expected_status_code,
                header_credentials_required = True,
            )
            
            response_data = response.json()

            
            return response_data
       
    def post(self, payload, bearer_token=None, endpoint=None, intermex_token=None,  expected_status_code=200):

            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
                
            if intermex_token is not None:
                headers["Intermex-Token"] = intermex_token
            
            response = self.request_utility.post(
                endpoint, 
                payload=payload,
                headers=headers,
                expected_status_code=expected_status_code,
                header_credentials_required = True,
            )
            
            response_data = response.json()

            
            return response_data
       
    def get(self, params, bearer_token=None, endpoint=None, intermex_token=None, 
            session_token=None, expected_status_code=200):

            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
                
            if intermex_token is not None:
                headers["Intermex-Token"] = intermex_token
                
            if session_token is not None:
                headers["Session-Token"] = session_token
            
            response = self.request_utility.get(
                endpoint, 
                params=params,
                headers=headers,
                expected_status_code=expected_status_code,
                header_credentials_required = True,
            )
            
            response_data = response.json()

            
            return response_data
       
    def patch(self, payload, bearer_token=None, endpoint=None, intermex_token=None, expected_status_code=200):

            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
                
            if intermex_token is not None:
                headers["Intermex-Token"] = intermex_token
            
            response = self.request_utility.patch(
                endpoint, 
                payload=payload,
                headers=headers,
                expected_status_code=expected_status_code,
                header_credentials_required = True,
            )
            
            response_data = response.json()

            
            return response_data
       
    def delete(self, payload, bearer_token=None, endpoint=None,intermex_token=None, headers={}, expected_status_code=200):
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
                
            if intermex_token is not None:
                headers["Intermex-Token"] = intermex_token
            
            response = self.request_utility.delete(
                endpoint, 
                payload=payload,
                headers=headers,
                expected_status_code=expected_status_code,
                header_credentials_required = True,
            )
            
            response_data = response.json()

            
            return response_data
         
        
        
        
        
        
    def registration_choose_pin(self, agent_id=None, pin=None, bearer_token=None, expected_status_code=200, **kwargs):
            
            payload = dict()
            
            payload["agent_id"] = agent_id
            payload["pin"] = pin
            
            payload.update(kwargs)
            
            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            
            response = self.request_utility.post(
                'registration/choose-pin', 
                payload=payload, 
                headers=headers,
                expected_status_code=expected_status_code
            )
            
            response_data = response.json()
            
            return response_data
      
    def registration_basic_kyc(self, agent_id=None, business_name=None,business_email=None,
                               business_address=None, contact_person_fullname=None,
                               contact_person_phone_number=None, bearer_token=None, 
                               expected_status_code=200, **kwargs):
            
            payload = dict()
            
            payload["agent_id"] = agent_id
            payload["business_name"] = business_name
            payload["business_email"] = business_email
            payload["business_address"] = business_address
            payload["contact_person_fullname"] = contact_person_fullname
            payload["contact_person_phone_number"] = contact_person_phone_number
            
            payload.update(kwargs)
            
            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            
            response = self.request_utility.post(
                'registration/basic-kyc', 
                payload=payload, 
                headers=headers,
                expected_status_code=expected_status_code
            )
            
            response_data = response.json()
            
            return response_data
      
    def registration_get_agent(self, agent_id=None, bearer_token=None, 
                               expected_status_code=200, **kwargs):
            
            params = dict()
            
            params["agent_id"] = agent_id
            
            params.update(kwargs)
            
            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            
            response = self.request_utility.get(
                'registration/agent', 
                params=params, 
                headers=headers,
                expected_status_code=expected_status_code
            )
            
            response_data = response.json()
            
            return response_data
      
    def registration_initiate_email_verification(self, agent_id=None, return_url=None, bearer_token=None, 
                                                 expected_status_code=200, **kwargs):
            
            payload = dict()
            
            payload["agent_id"] = agent_id
            payload["return_url"] = return_url
            
            payload.update(kwargs)
            
            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            
            response = self.request_utility.post(
                'registration/initiate-email-verification', 
                payload=payload, 
                headers=headers,
                expected_status_code=expected_status_code
            )
            
            response_data = response.json()
            
            return response_data
      
    def registration_update_director(self, 
                                     agent_id=None, fullname=None, bearer_token=None, 
                                     id_type=None, phone_number=None, id_number=None,
                                     id_back_image=None, id_front_image=None,
                                                 expected_status_code=200, **kwargs):
            
            payload = dict()
            
            payload["agent_id"] = agent_id
            payload["fullname"] = fullname if fullname else None
            payload["id_type"] = id_type if id_type else None
            payload["phone_number"] = phone_number if phone_number else None
            payload["id_number"] = id_number if id_number else None
            payload["id_back_image"] = id_back_image if id_back_image else None
            payload["id_front_image"] = id_front_image if id_front_image else None
            
            payload.update(kwargs)
            
            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            
            response = self.request_utility.post(
                'registration/director', 
                payload=payload, 
                headers=headers,
                expected_status_code=expected_status_code
            )
            
            response_data = response.json()
            
            return response_data
      
    def registration_edd_questionnaire(self, 
                                     agent_id=None, fullname=None, bearer_token=None, 
                                     id_type=None, phone_number=None, id_number=None,
                                     id_back_image=None, id_front_image=None,
                                                 expected_status_code=200, **kwargs):
            
            payload = dict()
            
            payload["agent_id"] = agent_id
            payload["fullname"] = fullname if fullname else None
            payload["id_type"] = id_type if id_type else None
            payload["phone_number"] = phone_number if phone_number else None
            payload["id_number"] = id_number if id_number else None
            payload["id_back_image"] = id_back_image if id_back_image else None
            payload["id_front_image"] = id_front_image if id_front_image else None
            
            payload.update(kwargs)
            
            headers = {}
            
            if bearer_token:
                headers["Authorization"] = f"Bearer {bearer_token}"
            
            response = self.request_utility.post(
                'registration/update-edd-questionnaire', 
                payload=payload, 
                headers=headers,
                expected_status_code=expected_status_code
            )
            
            response_data = response.json()
            
            return response_data
      