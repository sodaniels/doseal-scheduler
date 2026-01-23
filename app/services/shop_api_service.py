import requests
import json
import logging
import time
from datetime import datetime
import os
from requests.exceptions import RequestException, Timeout, HTTPError
from flask import jsonify
from ..utils.logger import Log
from ..constants.service_code import ACCOUNT_TYPES
from ..utils.generators import (
    clean_phone_number
)
from ..utils.json_response import prepared_response

class ShopApiService:
    """
    A robust and reusable service for interacting with external APIs.
    """
    def __init__(self, tenant_id, timeout=10):
        """
        Initialize the ApiService with a base URL and optional timeout.
        :param timeout: Request timeout in seconds (default is 10 seconds).
        """
        # test configuration
        self.shop_mode = os.getenv("SHOP_MODE")
        
        self.client_url = os.getenv('SHOP_BASE_URL') if self.shop_mode == 'production' else os.getenv("TEST_BASE_URL")
        self.tenant_id = tenant_id if self.shop_mode == 'production' else "86"
        self.timeout = timeout  # Timeout for requests

    def _set_tenant_data(self, data):
        """
        Updates the request data with tenant-specific information based on the tenant_id.
        """
        tenant_mapping = {
            "1": ("SHOP_UK_", "UK"),
            "5": ("SHOP_BARBADOS_", "Barbados"),
            "8": ("SHOP_CIV_", "Ivory Coast"),
            "17": ("SHOP_ZAMBIA_", "Zambia"),
            "19": ("SHOP_SIERRA_LEONE_", "Sierra Leone"),
            "20": ("SHOP_CANADA_", "Canada"),
            "86": ("SHOP_INTERNAL_QA_", "Internal QA"),
        }

        tenant_prefix, tenant_name = tenant_mapping.get(str(self.tenant_id), ("SHOP_", "Default"))
        
        cient_id = os.getenv(f"{tenant_prefix}CLIENT_ID")
        
        Log.info(f"[shop_api_service.py][_set_tenant_data] request from tenant: {cient_id}")
        
        data.update({
            "client_id": os.getenv(f"{tenant_prefix}CLIENT_ID"),
            "client_secret": os.getenv(f"{tenant_prefix}CLIENT_SECRET"),
            "username": os.getenv(f"{tenant_prefix}USERNAME"),
            "password": os.getenv(f"{tenant_prefix}PASSWORD"),
        })

    def _make_request(self, method, endpoint, payload=None, headers=None, params=None, **kwargs):
        """
        A private method to handle API requests for various HTTP methods.

        :param method: HTTP method ('GET', 'POST', 'PUT', 'DELETE').
        :param endpoint: API endpoint (relative to base_url).
        :param payload: JSON payload for the request body (for POST/PUT requests).
        :param headers: Optional headers to include in the request.
        :param params: Query parameters for GET/DELETE requests.
        :return: Response JSON or a meaningful exception.
        """
        url = f"{self.client_url}/{endpoint}"
        Log.info(f"[api_service.py][ShopApiService] initiating request to: {url}")

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
            
            Log.debug(f"[api_service.py][_make_request] response: {response.status_code}")
            
            if response.text.strip() == "":
                # Empty body — treat it gracefully
                Log.warning(f"[api_service.py][_make_request] Empty response body received.")
                return {}

            # Try to parse JSON safely
            try:
                return response.json()
            except json.JSONDecodeError:
                Log.error(f"[api_service.py][_make_request] Non-JSON response: {response.text}")
                raise Exception(f"Non-JSON response received: {response.text}")

        except Timeout:
            raise Exception(f"Request to {url} timed out after {self.timeout} seconds.")
        except HTTPError as http_err:
            # Optionally, log the actual response content
            Log.error(f"HTTP error response: {response.text}")
            raise Exception(f"HTTP error occurred: {http_err}.")
        except RequestException as req_err:
            raise Exception(f"Error occurred while making the request: {req_err}.")
    
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

    def delete(self, endpoint, params=None, headers=None):
        """
        Send a DELETE request to the specified API endpoint.
        """
        return self._make_request("DELETE", endpoint, params=params, headers=headers)
    # DEFAULT METHODS  
    def token(self):
        """
        Retrieves an OAuth token based on the provided tenant_id.
        :param tenant_id: ID of the tenant (e.g., 1, 5, 17, etc.)
        :return: Access token or error message.
        """
        log_tag = '[shop_api_service.py][token]'
        
        response = None
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        data = {
            "grant_type": os.getenv("SHOP_GRANT_TYPE"),
        }
        
        try:
            Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/oauth/token ...")

            # Determine the configuration based on tenant_id
            self._set_tenant_data(data)

            start_time = time.time()

            Log.info(f"{log_tag} making request for token")

            # Send the POST request
            response = requests.post(f"{self.client_url}/oauth/token", json=data, headers=headers)

            end_time = time.time()

            Log.info(f"{log_tag}... Response Received")
            Log.info(f"{log_tag} Time Taken: {end_time - start_time} seconds")
            
            json_reponse = response.json()
            
            if json_reponse.get("code") == 401:
                response_res = {
                    "status_code": 401,
                    "message": "Unauthenticated"
                }
                Log.info(f"{log_tag} json_reponse: {json_reponse}")
                return response_res

            if response.status_code == 200:
                json_response = response.json()
                Log.info(f"{log_tag} Token value set ...")
                return json_response.get("access_token")
            else:
                Log.error(f"{log_tag} Error: {response.status_code}, {response.text}")
                return response.text
        except requests.exceptions.RequestException as e:
            Log.error(f"{log_tag} Error: {e}")
            return str(e)

    def send_sms(self, phone, message, additional_param=None):
        """
        This method sends an SMS to the specified phone number.
        :param phone: The recipient's phone number.
        :param message: The message to send.
        :param tenant_id: Tenant ID for fetching the API token.
        :return: The response from the SMS API.
        """
        try:
            log_tag = '[shop_api_service.py][send_sms]'
            # Retrieve the token
            token = self.token()

            if token:
                # Remove the "+" sign from the phone number (clean it)
                cleaned_phone = phone.replace("+", "")
                recipients = [cleaned_phone]  # Create a list of recipients

                # Prepare the headers with the token
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                }

                # Log request details
                Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/api/instntmny-local/in-house/send-sms/ ...")
                Log.info(f"{log_tag} ... Request: {{'message': {message}, 'recipient': {recipients}}}")

                # Format the request payload
                payload = {
                    "message": message,
                    "recipient": recipients,
                }

                # Log payload
                Log.info(f"{log_tag} payload: {payload}")

                start_time = time.time()

                response = self.post("api/instntmny-local/in-house/send-sms/", payload=payload, headers=headers)

                # Record end time and calculate the duration
                end_time = time.time()
                duration = end_time - start_time

                Log.info(f"{log_tag} Sending SMS request completed in {duration:.2f} seconds")
                
                Log.info(f"{log_tag} Sending SMS response: {response}")
                
                return response
            else:
                response_body = {
                    "success": False,
                    "status_code": 401,
                    "message": "Could not retrieve token"
                }
                Log.info(f"{log_tag} Could not retrieve token")
                return response_body
                
        except Exception as e:
            Log.error(f"Error while sending Debit request:")
            response_body = {
                "success": False,
                "status_code": 500,
                "message": "An error occurred",
            }
            return response_body

    def get_banks(self):
        """
        This method retrieves a list of banks for the specified tenant.
        
        :param tenant_id: Tenant ID used to fetch the API token.
        :return: The response from the bank API, which contains a list of available banks.
        """
        try:
            log_tag = '[shop_api_service.py][get_banks]'
            # Retrieve the token
            token = self.token()

            if token:
                # Prepare the headers with the token
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                }

                # Log request details
                Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/api/payouts/banks/ ...")

                start_time = time.time()

                response = self.get("api/payouts/banks/",  headers=headers)

                # Record end time and calculate the duration
                end_time = time.time()
                duration = end_time - start_time

                Log.info(f"{log_tag} Retrieve Bank request completed in {duration:.2f} seconds")

                return response
        except Exception as e:
            Log.error(f"Error while retrieving banks: {str(e)}")
            return {"error": str(e)}

    def get_rates(self, from_currency, to_currency, account_type):
        """
        This method retrieves a list of banks for the specified tenant.
        
        :param tenant_id: Tenant ID used to fetch the API token.
        :return: The response from the bank API, which contains a list of available banks.
        """
        try:
            log_tag = '[shop_api_service.py][get_rates]'

            headers = {
                    "Content-Type": "application/json"
                }

            # Log request details
           
            start_time = time.time()
            
            # Get today's date in "yyyy-MM-dd" format
            date = datetime.now().strftime("%Y-%m-%d")

            # Convert currency codes to lowercase
            from_currency = str.lower(from_currency)
            to_currency = str.lower(to_currency)
            
            account_type = str.upper(account_type)
            
            Log.info(f"account_type: {account_type}")
            
            account_value = get_account_type_value(account_type)
            
            Log.info(f"account_value: {account_value}")
            
            url = f'https://rates.myzeepay.com/api/rates/{account_value}/{from_currency}/{to_currency}/{date}'
            
            Log.info(f"{log_tag} Initiating [POST] request to {url}")

            
            response = requests.get(url, headers=headers)
            
            Log.info(f"response: {response.status_code}")
            
            if response.status_code == 200:
                rates = response.json()

                Log.info(f"{log_tag}[{date}] Rates fetched successfully.")
                rates["success"] = True
                rates["status_code"] = response.status_code
                rates.pop("code", None)
                return rates
            
            if response.status_code == 403:
                Log.info(f"{log_tag} Could not retrieve rates. Permission denied on SHOP")
                json_response = dict()
                json_response["success"] = False
                json_response["code"] = response.status_code
                json_response["message"] = "Could not retrieve rates. Permission denied on SHOP"
                
                return json_response
            else:
                Log.error(f"{log_tag} Error: Unable to fetch rates.")
                return {
                    "success": False,
                    "code": 400,
                    "message": "Could not retrieve rates"
                }

        except Exception as e:
            Log.error(f"Error while retrieving rate: {str(e)}")
            return {
                    "success": False,
                    "code": 500,
                    "error": str(e),
                    "message": "Could not retrieve rates"
                }

    def post_account_validation_wallet(self, receiving_country, account_number, payment_type, mno):
        """
        This method retrieves a list of banks for the specified tenant.
        
        :param tenant_id: Tenant ID used to fetch the API token.
        :return: The response from the bank API, which contains a list of available banks.
        """
        try:
            log_tag = '[shop_api_service.py][post_account_validation_wallet]'
            # Retrieve the token
            token = self.token()

            if token is None:
                Log.info(f"{log_tag} No token was retreived. {token}" )
                return jsonify({
                    "success": False,
                    "status_code": 401,
                    "message": "No token was retreived"
                })
                
            # Prepare the headers with the token
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
            }

            # Log request details
            Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/api/payouts/account-verification/ ...")

            start_time = time.time()
            
            request_body = {
                "service_type": payment_type,
                "mobile_number": account_number,
                "receiving_country": receiving_country,
                "mno": mno if mno else None
            }
            
            Log.info(f"{log_tag} request_body: {request_body}")

            response = self.post("api/payouts/account-verification/", request_body,  headers=headers)

            # Record end time and calculate the duration
            end_time = time.time()
            duration = end_time - start_time

            Log.info(f"{log_tag} Account validation completed in {duration:.2f} seconds")
            Log.info(f"{log_tag} response: {response}")

            return response
        except Exception as e:
            Log.error(f"Error while validating account: {str(e)}")
            return {"error": str(e)}

    def post_account_validation_bank(self, receiving_country, account_number, payment_type, routing_number):
        """
        This method retrieves a list of banks for the specified tenant.
        
        :param tenant_id: Tenant ID used to fetch the API token.
        :return: The response from the bank API, which contains a list of available banks.
        """
        try:
            log_tag = '[shop_api_service.py][post_account_validation_bank]'
            # Retrieve the token
            token = self.token()

            if token:
                # Prepare the headers with the token
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {token}",
                }

                # Log request details
                Log.info(f"{log_tag} Initiating [POST] request to {self.client_url}/api/payouts/account-verification/ ...")

                start_time = time.time()
                
                request_body = {
                    "service_type": payment_type,
                    "account_number": account_number,
                    "receiving_country": receiving_country,
                    "routing_number": routing_number if routing_number else None
                }

                response = self.post("api/payouts/account-verification/", request_body,  headers=headers)

                # Record end time and calculate the duration
                end_time = time.time()
                duration = end_time - start_time

                Log.info(f"{log_tag} Account validation completed in {duration:.2f} seconds")

                return response
        except Exception as e:
            Log.error(f"Error while validating account: {str(e)}")
            return {"error": str(e)}

    def process_volume_transaction(self, receiving_country, sending_country, sender_firstname,
		sender_lastname, sender_currency, description, sender_phoneNumber, external_id, amount):
        """
        This method sends an SMS to the specified phone number.
        :param phone: The recipient's phone number.
        :param message: The message to send.
        :param tenant_id: Tenant ID for fetching the API token.
        :return: The response from the SMS API.
        """
        try:
            log_tag = '[shop_api_service.py][process_volume_transaction]'
            # Retrieve the token
            token = self.token()

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
            Log.error(f"Error while sending Debit request : {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An error occurred.")

    def get_biller_list(self, country_iso2):
        """
        Retrieve biller list from Shop API and filter by country ISO2 code.

        :param country_iso2: ISO2 code for the country (e.g., 'GH', 'NG').
        :return: Dict with success flag, code, and filtered data list, or raw response.
        """
        log_tag = "[shop_api_service.py][get_biller_list]"
        try:
            Log.info(f"{log_tag}[{country_iso2}][loading biller list]")

            # Get auth token (adapt if your token() needs args)
            token = self.token()
            if not token:
                return {
                    "success": False,
                    "code": 401,
                    "message": "Unable to retrieve auth token",
                }
            # Prepare headers
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            start_time = time.time()

            response = self.get("api/bill-payment/get-biller-list", headers=headers)

            duration = time.time() - start_time
            Log.info(f"{log_tag} Biller list request completed in {duration:.2f} seconds")
            
            # Log.info(f"{log_tag} biller response: {response}")

            biller_response = response

            if biller_response:
                data = biller_response.get("data")
                status = biller_response.get("status")

                if data is not None and status == 200:
                    total_array = []

                    for item in data:
                        if str.upper(country_iso2) == str.upper(item.get("countries")):
                            total_array.append(item)
                            
                    if total_array:
                        
                        response_data = {
                            "success": True,
                            "status_code": 200,
                            "data": total_array,
                        }
                        
                        
                        return jsonify(response_data)

                    return jsonify({
                        "success": True,
                        "status_code": 400,
                        "data": [],
                    })

            # Fallback: return whatever the API gave us
            return biller_response

        except Exception as error:
            Log.info(f"{log_tag}[error]\t.. {error}")
            # Node version re-throws, so we do the same:
            raise

    def post_billpay_account_validation(self, payload):
        """
        Validate a bill-payment account for a specific biller.
        This replicates the Node.js postBillpayAccountValidation logic.
        """

        log_tag = "[shop_api_service.py][validate_account]"
        try:
            Log.info(f"{log_tag} Validating account")

            # Retrieve authentication token
            token = self.token()
            if not token:
                return {
                    "success": False,
                    "code": 401,
                    "message": "Unable to retrieve auth token"
                }
                

            # Extract fields from payload
            destination_account = payload.get("destination_account")
            payer_name = payload.get("payer_name")
            receive_country = payload.get("receive_country")
            receive_currency = payload.get("receive_currency")
            send_country = payload.get("sender_country") or payload.get("send_country")
            send_currency = payload.get("send_currency")
            send_amount = float(payload.get("send_amount", 0))
            receive_amount = float(payload.get("receive_amount", 0))
            biller_id = payload.get("billpay_id") or payload.get("biller_id")
            reference = payload.get("reference")

            # Build the data object
            data = {
                "destination_account": destination_account,
                "payer_name": payer_name,
                "send_country": send_country,
                "send_currency": send_currency,
                "send_amount": send_amount,
                "receive_amount": receive_amount,
                "receive_country": receive_country,
                "receive_currency": receive_currency,
                "reference": reference,
                "callback_url": os.getenv("CALL_BACK_BASE_URL") + "/transactions/zeepay-third-party/callback",
            }

            Log.info(f"{log_tag} Payload => {data}")

            # Construct the target endpoint
            url = f"{self.client_url}/api/bill-payment/account-validation/{biller_id}"

            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }

            Log.info(f"{log_tag} Initiating [POST] {url}")

            start_time = time.time()

            # Make the POST request. If your service uses self.post(), use it:
            response = self.post(f"api/bill-payment/account-validation/{biller_id}", data,  headers=headers)

            duration = time.time() - start_time
            Log.info(f"{log_tag} Account validation completed in {duration:.2f} seconds")

            # If self.post returns a Response object → convert to JSON
            if hasattr(response, "json"):  
                return response.json()

            # Otherwise assume it's already a dict
            return response

        except Exception as error:
            Log.error(f"{log_tag} Error: {str(error)}")
            raise



def get_account_type_value(account_type):
    type = ACCOUNT_TYPES.get(account_type.upper())
    if type: 
        return type
    return None
