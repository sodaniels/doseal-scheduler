import requests
import os
import json
import logging as Log


from src.configs.hosts_config import (
    API_HOSTS
)

class RequestUtility(object):
    
    def __init__(self):
        self.env = os.getenv("APP_ENV", 'development')
        self.base_url = "http://localhost:9090"
        self.expected_status_code = 200
    
    def assert_status_code(self, url, expected_status_code):
        # Compare actual status code with the expected one
        assert self.status_code == expected_status_code, f"Bad Status code." \
            f" Expected {expected_status_code}, Actual status code {self.status_code}"\
            f" URL: {url}, Response Json: {self.rs_json}"
    
    def post(self, endpoint, payload=None, headers=None, expected_status_code=200):
        
        if not headers:
            headers = {"Content-Type": "application/x-www-form-urlencoded"}
        
        url = f'{self.base_url}/api/v1/{endpoint}'
        
        print(f"payload: {payload}")  # Log the payload for debugging
        
        # Send the POST request
        rs_api = requests.post(url=url, data=payload, headers=headers)
        self.status_code = rs_api.status_code
        
        # Assign the response JSON
        self.rs_json = rs_api.json()
        
        # Assert status code based on the expected value passed to the method
        self.assert_status_code(url, expected_status_code)
        
        # Log the response for debugging
        print(f"API response: {self.rs_json}")
        
        return rs_api
    
    def get(self, endpoint, params=None, headers=None, expected_status_code=200):
        """
        Send a GET request to the specified endpoint with optional query parameters and headers.
        
        :param endpoint: API endpoint to send the GET request to.
        :param params: Optional dictionary of query parameters to include in the GET request.
        :param headers: Optional dictionary of headers to include in the GET request.
        :param expected_status_code: The expected HTTP status code (default is 200).
        :return: The response object from the GET request.
        """
        
        if not headers:
            headers = {"Content-Type": "application/json"}  # Default header for JSON response

        url = f'{self.base_url}/api/v1/{endpoint}'
        
        # Log the query parameters for debugging
        print(f"params: {params}")  # Log the query params if provided

        # Send the GET request
        rs_api = requests.get(url=url, params=params, headers=headers)
        self.status_code = rs_api.status_code
        
        # Assign the response JSON
        self.rs_json = rs_api.json()
        
        # Assert status code based on the expected value passed to the method
        self.assert_status_code(url, expected_status_code)
        
        # Log the response for debugging
        print(f"API response: {self.rs_json}")
        
        return rs_api
