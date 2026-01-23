import requests
import os
from requests.exceptions import RequestException, Timeout, HTTPError
import logging as Log


from src.configs.hosts_config import (
    API_HOSTS
)

class RequestUtility:
    def __init__(self):
        self.env = os.getenv("APP_ENV", 'development')
        self.base_url = "http://localhost:9090"
        self.status_code = None
        self.rs_json = None
        self.timeout = 60  # seconds

    def _make_request(self, method, endpoint, payload=None, headers=None, params=None, files=None, expected_status_code=200):
        url = f'{self.base_url}/{endpoint.lstrip("/")}'
        Log.info(f"[RequestUtility][_make_request] {method} to {url}")

        request_headers = headers.copy() if headers else {}
        if not files:
            request_headers.setdefault("Content-Type", "application/json")

        try:
            response = requests.request(
                method=method,
                url=url,
                json=payload if not files else None,
                data=payload if files else None,
                files=files,
                headers=request_headers,
                params=params,
                timeout=self.timeout
            )
            self.status_code = response.status_code
            try:
                self.rs_json = response.json()
            except Exception:
                self.rs_json = response.text

            assert response.status_code == expected_status_code, (
                f"Bad Status code. Expected {expected_status_code}, "
                f"Actual status code {response.status_code}. "
                f"URL: {url}, Response: {self.rs_json}"
            )
            Log.info(f"API response: {self.rs_json}")
            return response
        except Timeout:
            Log.error(f"Request to {url} timed out after {self.timeout} seconds.")
            raise
        except RequestException as req_err:
            Log.error(f"RequestException for {url}: {req_err}")
            raise

    def post(self, endpoint, payload=None, headers=None, header_credentials_required=False, header_credentials_session_required=False, expected_status_code=200, files=None, **kwargs):
        headers = headers or {}
        if header_credentials_required:
            partner_headers = {
                "PartnerId": os.getenv("INTERMEX_PARTNER_ID"),
                "ChannelId": os.getenv("INTERMEX_CHANNEL_ID"),
                "LanguageId": os.getenv("INTERMEX_LANGUAGE_ID"),
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_OCP_APIM_SUBSCRIPTION_KEY"),
            }
            headers.update(partner_headers)
        if header_credentials_session_required:
            session_headers = {
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_TOKEN_SUBSCRIPTION_KEY"),
            }
            headers.update(session_headers)
        kwargs.pop("header_credentials_required", None)
        kwargs.pop("header_credentials_session_required", None)
        return self._make_request("POST", endpoint, payload=payload, headers=headers, files=files, expected_status_code=expected_status_code, **kwargs)

    def patch(self, endpoint, payload=None, headers=None, header_credentials_required=False, header_credentials_session_required=False, expected_status_code=200, files=None, **kwargs):
        headers = headers or {}
        if header_credentials_required:
            partner_headers = {
                "PartnerId": os.getenv("INTERMEX_PARTNER_ID"),
                "ChannelId": os.getenv("INTERMEX_CHANNEL_ID"),
                "LanguageId": os.getenv("INTERMEX_LANGUAGE_ID"),
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_OCP_APIM_SUBSCRIPTION_KEY"),
            }
            headers.update(partner_headers)
        if header_credentials_session_required:
            session_headers = {
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_TOKEN_SUBSCRIPTION_KEY"),
            }
            headers.update(session_headers)
        kwargs.pop("header_credentials_required", None)
        kwargs.pop("header_credentials_session_required", None)
        return self._make_request("PATCH", endpoint, payload=payload, headers=headers, files=files, expected_status_code=expected_status_code, **kwargs)

    def put(self, endpoint, payload=None, headers=None, header_credentials_required=False, header_credentials_session_required=False, expected_status_code=200, files=None, **kwargs):
        headers = headers or {}
        if header_credentials_required:
            partner_headers = {
                "PartnerId": os.getenv("INTERMEX_PARTNER_ID"),
                "ChannelId": os.getenv("INTERMEX_CHANNEL_ID"),
                "LanguageId": os.getenv("INTERMEX_LANGUAGE_ID"),
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_OCP_APIM_SUBSCRIPTION_KEY"),
            }
            headers.update(partner_headers)
        if header_credentials_session_required:
            session_headers = {
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_TOKEN_SUBSCRIPTION_KEY"),
            }
            headers.update(session_headers)
        kwargs.pop("header_credentials_required", None)
        kwargs.pop("header_credentials_session_required", None)
        return self._make_request("PUT", endpoint, payload=payload, headers=headers, files=files, expected_status_code=expected_status_code, **kwargs)

    def delete(self, endpoint, payload=None, headers=None, header_credentials_required=False, header_credentials_session_required=False, expected_status_code=200, **kwargs):
        headers = headers or {}
        if header_credentials_required:
            partner_headers = {
                "PartnerId": os.getenv("INTERMEX_PARTNER_ID"),
                "ChannelId": os.getenv("INTERMEX_CHANNEL_ID"),
                "LanguageId": os.getenv("INTERMEX_LANGUAGE_ID"),
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_OCP_APIM_SUBSCRIPTION_KEY"),
            }
            headers.update(partner_headers)
        if header_credentials_session_required:
            session_headers = {
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_TOKEN_SUBSCRIPTION_KEY"),
            }
            headers.update(session_headers)
        kwargs.pop("header_credentials_required", None)
        kwargs.pop("header_credentials_session_required", None)
        return self._make_request("DELETE", endpoint, payload=payload, headers=headers, expected_status_code=expected_status_code, **kwargs)

    def get(self, endpoint, params=None, headers=None, header_credentials_required=False, header_credentials_session_required=False, expected_status_code=200, **kwargs):
        headers = headers or {}
        if header_credentials_required:
            partner_headers = {
                "PartnerId": os.getenv("INTERMEX_PARTNER_ID"),
                "ChannelId": os.getenv("INTERMEX_CHANNEL_ID"),
                "LanguageId": os.getenv("INTERMEX_LANGUAGE_ID"),
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_OCP_APIM_SUBSCRIPTION_KEY"),
            }
            headers.update(partner_headers)
        if header_credentials_session_required:
            session_headers = {
                "Ocp-Apim-Subscription-Key": os.getenv("INTERMEX_TOKEN_SUBSCRIPTION_KEY"),
            }
            headers.update(session_headers)
        kwargs.pop("header_credentials_required", None)
        kwargs.pop("header_credentials_session_required", None)
        return self._make_request("GET", endpoint, params=params, headers=headers, expected_status_code=expected_status_code, **kwargs)