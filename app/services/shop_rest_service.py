import requests
import hashlib
import hmac
import json
import os


from flask import jsonify

from app.utils.helpers import generate_signature
from requests.exceptions import RequestException, Timeout, HTTPError
from app.utils.logger import Log # import logging


VERIFF_BASE_URL = os.getenv("VERIFF_BASE_URL")
VERIFF_API_KEY = os.getenv("VERIFF_LIVE_API_KEY") if os.getenv("APP_ENV") != "development" else os.getenv("VERIFF_API_KEY")
VERIFF_SHARED_SECRET_KEY = os.getenv("VERIFF_LIVE_SHARED_SECRET_KEY") if os.getenv("APP_ENV") != "development" else os.getenv("VERIFF_SHARED_SECRET_KEY")

class ApiService: 
    """
    A robust and reusable service for interacting with external APIs.
    """
    def __init__(self, timeout=10):
        """
        Initialize the ApiService with a base URL and optional timeout.

        :param base_url: The base URL of the external API.
        :param timeout: Request timeout in seconds (default is 10 seconds).
        """
        self.base_url = VERIFF_BASE_URL
        self.client_key = VERIFF_API_KEY
        self.secret_key = VERIFF_SHARED_SECRET_KEY.encode("utf-8")
        self.timeout = timeout
    def _generate_signature(self, payload):
        """
        Generate the `X-HMAC-SIGNATURE` header using HMAC-SHA256.

        :param payload: The request payload (as a dictionary or JSON string).
        :return: Hex-encoded HMAC-SHA256 signature prefixed with 'sha256='.
        """
        # VERIFF_SHARED_SECRET_KEY = os.getenv("VERIFF_SHARED_SECRET_KEY")
        VERIFF_SHARED_SECRET_KEY = os.getenv("VERIFF_LIVE_SHARED_SECRET_KEY") if os.getenv("APP_ENV") != "development" else os.getenv("VERIFF_SHARED_SECRET_KEY")
        
        # If payload is a dictionary, convert it to a compact JSON string
        if isinstance(payload, dict):
            payload = json.dumps(payload, separators=(",", ":"))

        # Encode the payload as UTF-8 bytes
        payload_bytes = payload.encode("utf-8")
        key_bytes = VERIFF_SHARED_SECRET_KEY.encode('utf-8')

        # Generate HMAC-SHA256 signature
        hash = hmac.new(key_bytes, payload_bytes, hashlib.sha256)
        
        x_hmac_signature = hash.hexdigest()

        return x_hmac_signature


    #------------------Prepare Request------------------------
    def _make_request(self, method, endpoint, payload=None, headers=None, params=None, **kwargs):
        """
        A private method to handle API requests for various HTTP methods.

        :param method: HTTP method ('GET', 'POST', 'PUT', 'DELETE').
        :param endpoint: API endpoint (relative to base_url).
        :param payload: JSON payload for the request body (for POST/PUT requests).
        :param headers: Optional headers to include in the request.
        :param params: Query parameters for GET/DELETE requests.
        :return: Response JSON or raises a meaningful exception.
        """
        url = f"{self.base_url}/v1/{endpoint}"
        Log.info(f"[api_service.py][ApiService] initiating request to: {url}")
        
        # Default headers
        request_headers = {
            "CONTENT-TYPE": "application/json",
            "X-AUTH-CLIENT": self.client_key,
        }
        
        x_hmac_signature = self._generate_signature(payload)
        
        # Extract optional arguments from kwargs
        use_hmac = kwargs.get('use_hmac', False)  # Default to False if not provided
        is_get_request = kwargs.get('is_get_request') # Default to None if not provided
        
        # Conditionally add the HMAC signature
        if use_hmac:
            request_headers["X-HMAC-SIGNATURE"] = x_hmac_signature
            
        if is_get_request:
            x_hmac_signature_ = generate_signature(payload)
            request_headers["X-HMAC-SIGNATURE"] = x_hmac_signature_
             
         # Merge with optional headers
        if headers:
            request_headers.update(headers)
      
        try:
            response = requests.request(
                method=method,
                url=url,
                json = None if use_hmac or is_get_request else payload, 
                data=payload if use_hmac else None,
                headers=request_headers,
                params=params,
                timeout=self.timeout,
            )
            Log.info("headers: %s", request_headers)
            response.raise_for_status()  # Raise an HTTPError for bad responses (4xx or 5xx)
            return response.json()  # Return the JSON response
        except Timeout:
            raise Exception(f"Request to {url} timed out after {self.timeout} seconds.")
        except HTTPError as http_err:
            raise Exception(f"HTTP error occurred: {http_err}.")
        except RequestException as req_err:
            raise Exception(f"Error occurred while making the request: {req_err}.")
    #-------------------MAKE A GET REQUESTS-----------------------------------
    def get(self, endpoint, params=None, headers=None):
        """
        Send a GET request to the specified API endpoint.

        :param endpoint: API endpoint (relative to base_url).
        :param params: Query parameters to include in the request.
        :param headers: Optional headers to include in the request.
        :return: Response JSON or raises a meaningful exception.
        """
        return self._make_request("GET", endpoint, params=params, headers=headers)
    #-------------------POST REQUESTS-----------------------------------
    def post_veriff_sessions(self, endpoint, payload=None, headers=None, use_hmac=False):
        """
        Send a POST request to the specified API endpoint.

        :param endpoint: API endpoint (relative to base_url).
        :param payload: JSON payload to send in the request body.
        :param headers: Optional headers to include in the request.
        :return: Response JSON or raises a meaningful exception.
        """
        return self._make_request("POST", endpoint, payload=payload, headers=headers, use_hmac=use_hmac)
    
    #-------------------PATCH REQUESTS-----------------------------------
    def patch_veriff_sessions(self, endpoint, payload=None, headers=None, use_hmac=False):
        """
        Send a PATCH request to the specified API endpoint.

        :param endpoint: API endpoint (relative to base_url).
        :param payload: JSON payload to send in the request body.
        :param headers: Optional headers to include in the request.
        :return: Response JSON or raises a meaningful exception.
        """
        return self._make_request("PATCH", endpoint, payload=payload, headers=headers, use_hmac=use_hmac)
    
       #-------------------MAKE A GET EMAIL VALIDATION REQUESTS-----------------------------------
    def get_veriff_sessions(self, endpoint, payload=None, headers=None, is_get_request=False):
        """
        Send a GET request to the specified API endpoint.

        :param endpoint: API endpoint (relative to base_url).
        :param payload: JSON payload to send in the request body.
        :param headers: Optional headers to include in the request.
        :return: Response JSON or raises a meaningful exception.
        ________________________________________________________________
        """
        return self._make_request("GET", endpoint, payload=payload, headers=headers, is_get_request=is_get_request)
    #-------------------MAKE A DELETE REQUESTS-----------------------------------
    def delete_veriff_session(self, endpoint, payload=None, headers=None, is_get_request=False):
        """
        Send a DELETE request to the specified API endpoint.

        :param endpoint: API endpoint (relative to base_url).
        :param params: Query parameters to include in the request.
        :param headers: Optional headers to include in the request.
        :return: Response JSON or raises a meaningful exception.
        """
        return self._make_request("DELETE", endpoint, payload=payload, headers=headers, is_get_request=is_get_request)