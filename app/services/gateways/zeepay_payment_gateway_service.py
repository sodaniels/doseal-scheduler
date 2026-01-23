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

class ZeepayPaymentGatewayService:
    """
    A service for processing P2P and Outbound payments.
    """
    def __init__(self, tenant_id, timeout=10):
        """
        Initialize the ApiService with a base URL and optional timeout.
        :param timeout: Request timeout in seconds (default is 10 seconds).
        """
        # test configuration
        self.tenant_id = tenant_id
        self.shop_mode = os.getenv("SHOP_MODE")
        self.shop_service = ShopApiService(tenant_id)
        
        self.callback_url = os.getenv("CALL_BACK_BASE_URL")
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
        log_tag = '[zeepay_payment_gateway_service.py][ZeepayPaymentGatewayService]'
        
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
    
    def payout(self,
           amount,
           send_amount,
           sender_country,
           sending_currency,
           sender_first_name,
           sender_last_name,
           receiver_first_name,
           receiver_last_name,
           service_type,
           receiver_msisdn,
           account_number,
           routing_number,
           receiver_country,
           receiver_currency,
           transaction_type,
           extr_id,
           mno=None,
           client_reference=None):
        """
        Initiates a payout transaction by sending a POST request to the payout API.

        :param amount: The amount to be paid to the receiver.
        :param send_amount: The amount sent by the sender.
        :param sender_country: Country from which the money is sent.
        :param sending_currency: Currency used by the sender.
        :param sender_first_name: First name of the sender.
        :param sender_last_name: Last name of the sender.
        :param receiver_first_name: First name of the receiver.
        :param receiver_last_name: Last name of the receiver.
        :param service_type: Type of service (e.g., bank, wallet).
        :param receiver_msisdn: Mobile number of the receiver.
        :param account_number: Receiver's account number.
        :param routing_number: Receiver's bank routing number (optional).
        :param receiver_country: Country where the receiver is located.
        :param receiver_currency: Currency expected by the receiver.
        :param transaction_type: Type of transaction (e.g., payout).
        :param mno: Mobile Network Operator.
        :param extr_id: External transaction ID.
        :param client_reference: Optional client reference ID.
        :return: Response from the payout API.
        """
        try:
            log_tag = '[zeepay_payment_gateway_service.py][payout]'
            self.shop_service = ShopApiService(self.tenant_id)
            token = self.shop_service.token()

            if token:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                }
                
                resource = "api/payouts"
                payload = {
                    "amount": amount,
                    "send_amount": send_amount,
                    "sender_country": sender_country,
                    "sending_currency": sending_currency,
                    "sender_first_name": sender_first_name,
                    "sender_last_name": sender_last_name,
                    "receiver_first_name": receiver_first_name,
                    "receiver_last_name": receiver_last_name,
                    "service_type": service_type,
                    "receiver_msisdn": receiver_msisdn,
                    "account_number": account_number,
                    "routing_number": routing_number,
                    "receiver_country": receiver_country,
                    "receiver_currency": receiver_currency,
                    "transaction_type": transaction_type,
                    "mno": mno,
                    "extr_id": extr_id,
                    "callback_url": f"{self.callback_url}/api/v1/transactions/zeepay-third-party/callback",
                }

                # Optionally include client_reference if provided
                if client_reference:
                    payload["client_reference"] = client_reference

                Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/{resource} ...")
                Log.info(f"{log_tag} Payload: {payload}")

                start_time = time.time()

                response = self.post(resource, payload=payload, headers=headers)

                duration = time.time() - start_time
                Log.info(f"{log_tag} Payout completed in {duration:.2f} seconds")
                Log.info(f"{log_tag} Payout response: {response}")

                return response
            else:
                Log.info(f"{log_tag} Could not retrieve token")
                return prepared_response(False, "UNAUTHORIZED", "Could not retrieve token.")
        except Exception as e:
            Log.error(f"{log_tag} Error during payout: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "An error occurred during payout.")

    def reverse_transaction(self, zeepay_id, reason):
        try:
            log_tag = '[zeepay_payment_gateway_service.py][reverse_transaction]'
            self.shop_service = ShopApiService(self.tenant_id)
            token = self.shop_service.token()

            if token:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                }
                
                resource = f"api/transactions/{zeepay_id}/reverse/{reason}?"
                payload = {
                    "zeepay_id": zeepay_id,
                    "reversalReason": reason,
                }
                
                Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/{resource} ...")
                Log.info(f"{log_tag} Payload: {payload}")

                start_time = time.time()

                response = self.put(resource, payload=payload, headers=headers)

                duration = time.time() - start_time
                Log.info(f"{log_tag} reverse_transaction completed in {duration:.2f} seconds")
                Log.info(f"{log_tag} reverse_transaction response: {response}")

                return response
            else:
                Log.info(f"{log_tag} Could not retrieve token")
                return prepared_response(False, "UNAUTHORIZED", "Could not retrieve token.")
        except Exception as e:
            Log.error(f"{log_tag} Error while reversing transaction: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred while reversing transaction. {str(e)}")
