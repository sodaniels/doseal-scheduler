import requests
import logging
import time
from datetime import datetime
import os
from requests.exceptions import RequestException, Timeout, HTTPError
from flask import jsonify
from ...utils.logger import Log
from ...constants.service_code import ACCOUNT_TYPES
from ...services.shop_api_service import ShopApiService
from ...utils.json_response import prepared_response

class VolumePaymentGatewayService:
    """
    A service for processing payments.
    """
    def __init__(self, tenant_id, timeout=10):
        """
        Initialize the ApiService with a base URL and optional timeout.
        :param timeout: Request timeout in seconds (default is 10 seconds).
        """
        # test configuration
        self.shop_mode = os.getenv("SHOP_MODE")
        self.shop_service = ShopApiService(tenant_id)
        
        self.client_url = os.getenv('SHOP_BASE_URL') if self.shop_mode == 'production' else os.getenv("TEST_BASE_URL")
        self.timeout = timeout  # Timeout for requests

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
        url = f"{self.client_url}/{endpoint}"
        log_tag = '[volume_payment_gateway_service.py][VolumePaymentGatewayService]'
        
        Log.info(f"{log_tag} initiating request to: {url}")
        
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
            raise Exception(f" {log_tag} Request to {url} timed out after {self.timeout} seconds.")
        except HTTPError as http_err:
            raise Exception(f"{log_tag} HTTP error occurred: {http_err}.")
        except RequestException as req_err:
            raise Exception(f"{log_tag} Error occurred while making the request: {req_err}.")
    # DEFAULT METHODS    
    def get(self, endpoint, params=None, headers=None):
        """
        Send a GET request to the specified API endpoint.
        """
        return self._make_request("GET", endpoint, params=params, headers=headers)

    def post(self, endpoint, payload=None, headers=None):
        """
        Send a POST request to the specified API endpoint.
        """
        return self._make_request("POST", endpoint, payload=payload, headers=headers)

    def put(self, endpoint, payload=None, headers=None):
        """
        Send a PUT request to the specified API endpoint.
        """
        return self._make_request("PUT", endpoint, payload=payload, headers=headers)
    # DEFAULT METHODS  
    
    def process_volume_transaction(self, receiving_country, sending_country, sender_firstname,
		sender_lastname, sender_currency, description, sender_phoneNumber, external_id, amount):
        """
        Processes a volume transaction by sending a POST request to the payment API.

        This method initiates a debit transaction by making an authenticated request
        to the external shop API with the given sender and transaction details.

        :param receiving_country: The country where the funds will be received.
        :param sending_country: The country from where the funds are being sent.
        :param sender_firstname: First name of the sender.
        :param sender_lastname: Last name of the sender.
        :param sender_currency: Currency being used by the sender.
        :param description: A brief description or note for the transaction.
        :param sender_phoneNumber: Phone number of the sender (used for identification/notification).
        :param external_id: A unique identifier for the transaction from the client system.
        :param amount: The monetary amount to be sent.
        :return: The response from the volume transaction API, or an error response if the request fails.
        """
        try:
            log_tag = '[shop_api_service.py][process_volume_transaction]'
            # Retrieve the token
            token = self.shop_service.token()

            if token:
                # Prepare the headers with the token
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                }

                # Log request details
                Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/api/payments/volume/ ...")

                # Format the request payload
                payload = {
                    "currency": sender_currency,
                    "receiving_country": receiving_country,
                    "sending_country": sending_country,
                    "sender_firstname": sender_firstname,
                    "sender_lastname": sender_lastname,
                    "description": description,
                    "mobile_number": sender_phoneNumber,
                    "external_id": external_id,
                    "amount": amount,
                    "callback_url": f'{self.client_url}/api/v1/volume/payment/callback',
                }

                # Log payload
                Log.info(f"{log_tag} payload: {payload}")

                start_time = time.time()

                response = self.post("api/payments/volume/", payload=payload, headers=headers)

                # Record end time and calculate the duration
                end_time = time.time()
                duration = end_time - start_time

                Log.info(f"{log_tag} Processing transaction Debit request completed in {duration:.2f} seconds")
                
                Log.info(f"{log_tag} Processing transaction Debit: {response}")
                
                return response
            else:
                Log.info(f"{log_tag} Could not retrieve token")
                return prepared_response(False, "UNAUTHORIZED", f"Could not retrieve token.")
            
        except Exception as e:
            Log.error(f"Error while sending SMS: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred. : {str(e)}")

