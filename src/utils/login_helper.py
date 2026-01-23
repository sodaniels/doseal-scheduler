from src.utils.generic_utilities import generate_login_payload
from src.utils.requests_utility import RequestUtility

class LoginHelper(object):
    
    def __init__(self):
        self.request_utility = RequestUtility()
    
    def login_user(self, password=None, email=None):
        
        business_payload = generate_login_payload()
        
        if not password:
            password = business_payload["password"]
            
        if not email:
            email = business_payload["email"]
            
        payload = dict()
        
        payload["password"] = password
        payload["email"] = email
        
        response = self.request_utility.post('login', payload=payload)
        
        response_data = response.json()
        
        return response_data
        
    def agent_login_user(self):
        
        business_payload = generate_login_payload()
        
        if not country_iso_2:
            country_iso_2 = business_payload["country_iso_2"]
            
        if not username:
            username = business_payload["username"]
            
        payload = dict()
        
        payload["country_iso_2"] = country_iso_2
        payload["username"] = username
        
        response = self.request_utility.post('login/initiate', payload=payload)
        
        response_data = response.json()
        
        return response_data
       
       
    def login_initiate(self, username=None, country_iso_2=None, expected_status_code=200, **kwargs):
            
            payload = dict()
            
            payload["username"] = username
            payload["country_iso_2"] = country_iso_2
            payload.update(kwargs)
            
            response = self.request_utility.post(
                'login/initiate', 
                payload=payload, 
                expected_status_code=expected_status_code
            )
            
            response_data = response.json()
            
            return response_data
      
    def login_execute(self, username=None, country_iso_2=None, otp=None, expected_status_code=200, **kwargs):
                
                payload = dict()
                
                payload["username"] = username
                payload["country_iso_2"] = country_iso_2
                payload["otp"] = otp
                
                payload.update(kwargs)
                
                response = self.request_utility.post(
                    'login/execute', 
                    payload=payload, 
                    expected_status_code=expected_status_code
                )
                
                response_data = response.json()
                
                return response_data
        