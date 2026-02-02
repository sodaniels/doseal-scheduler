import requests
import logging
import time
from datetime import datetime
import os
from requests.exceptions import RequestException, Timeout, HTTPError
from flask import jsonify
from ..utils.logger import Log
from ..constants.service_code import ACCOUNT_TYPES

class ApiService:
    """
    A robust and reusable service for interacting with external APIs.
    """
    def __init__(self, base_url, timeout=10):
        """
        Initialize the ApiService with a base URL and optional timeout.
        :param timeout: Request timeout in seconds (default is 10 seconds).
        """
        self.base_url = base_url # base url
        self.timeout = timeout  # Timeout for requests


    def _make_request(self, method, endpoint, payload=None, headers=None, params=None, loggable=None, **kwargs):
        """
        A private method to handle API requests for various HTTP methods.

        :param method: HTTP method ('GET', 'POST', 'PUT', 'DELETE').
        :param endpoint: API endpoint (relative to base_url).
        :param payload: JSON payload for the request body (for POST/PUT requests).
        :param headers: Optional headers to include in the request.
        :param params: Query parameters for GET/DELETE requests.
        :return: Response JSON or raises a meaningful exception.
        """
        url = f"{self.base_url}/{endpoint}"
        
        if loggable:
            Log.info(f"[api_service.py][ApiService] initiating request to: {url}")
        
        # Default headers
        request_headers = {
            "Content-Type": "application/json",
        }

        if headers:
            request_headers.update(headers)
        
        try:
            response = requests.request(
                method=method,
                url=url,
                json=payload,  # Send as JSON body for POST/PUT
                headers=request_headers,
                params=params,  # For query parameters (GET/DELETE)
                timeout=self.timeout,
                **kwargs  # Allow additional parameters
            )
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
            return response.json()  # Return the JSON response
        except Timeout:
            raise Exception(f"Request to {url} timed out after {self.timeout} seconds.")
        except HTTPError as http_err:
            raise Exception(f"HTTP error occurred: {http_err}.")
        except RequestException as req_err:
            raise Exception(f"Error occurred while making the request: {req_err}.")
             
    def get(self, endpoint, params=None, loggable=None, headers=None):
        """
        Send a GET request to the specified API endpoint.
        """
        return self._make_request("GET", endpoint, params=params, loggable=loggable, headers=headers)

    def post(self, endpoint, payload=None,loggable=None, headers=None):
        """
        Send a POST request to the specified API endpoint.
        """
        return self._make_request("POST", endpoint, payload=payload, loggable=loggable, headers=headers)

    def put(self, endpoint, payload=None, loggable=None, headers=None):
        """
        Send a PUT request to the specified API endpoint.
        """
        return self._make_request("PUT", endpoint, payload=payload,loggable=loggable, headers=headers)

    def delete(self, endpoint, params=None, loggable=None, headers=None):
        """
        Send a DELETE request to the specified API endpoint.
        """
        return self._make_request("DELETE", endpoint, params=params,loggable=loggable, headers=headers)

  
    def get_post_code_address(self, user_id, post_code, country_iso2):
        """
        This method retrieves a list of banks for the specified tenant.
        
        :param tenant_id: Tenant ID used to fetch the API token.
        :return: The response from the bank API, which contains a list of available banks.
        """
        try:
            log_tag = f'[shop_api_service.py][get_post_code_address][{user_id}]'

            headers = {
                    "Content-Type": "application/json"
                }

            country_code = country_iso2.lower()
            
            searchTerm = post_code.lower()
            noSpacesSearchterm = searchTerm.replace(" ", "")
            
            api_key = os.getenv("POSTCODER_API_KEY")
            
            
            endpoint = f'{api_key}/address/{country_code}/{noSpacesSearchterm}?identifier=SignupForm'
            
            Log.info(f"{log_tag} Initiating [POST] request to https://ws.postcoder.com")

            
            response = self.get(endpoint, loggable=False, headers=headers)
            
            if response:
                Log.info(f"{log_tag} postcode addresses retrieved successfully")
                return response
            else:
                Log.error(f"{log_tag} Error: Unable to fetch post code address")
                return {
                    "success": False,
                    "status_code": 400,
                    "message": "Could not fetch post code address"
                }
        except Exception as e:
            Log.error(f"Error while retrieving post code address: {str(e)}")
            return {
                    "success": False,
                    "status_code": 400,
                    "message": "An error occurred"
                }
        

