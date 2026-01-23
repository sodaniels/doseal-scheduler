import time
import json
import os
from typing import List, Dict, Optional, Iterable
from ...utils.logger import Log # import logging
from flask import jsonify, request, g
from pymongo.errors import PyMongoError
from typing import Dict, Any
from ...utils.logger import Log # import logging
from ...constants.service_code import (
    SMS_PROVIDER, 
)
from ...utils.json_response import prepared_response
from ...services.notification_sms import (
    send_bulk_sms_twilio, send_sms_twilio, fetch_message_status
)

class SmsGatewayService:
    def __init__(self, text, provider=None, to_numbers: List[str]=None, to: str = None):
        self.to_numbers = to_numbers
        self.to = to
        self.text = text
        self.provider = provider if provider !=None else SMS_PROVIDER["TWILIO"]
        
        
    def send_sms(self):
        log_tag = f'[sms_gateway_service.py][SmsGatewayService][send_sms]'
        
        if self.provider == 'twilio':
            
            # when to is not a single
            if self.to is None:
                Log.info(f"{log_tag} Please enter the number to send.")
                return prepared_response(False, "VALIDATION_ERROR", f"Please enter the number to send.") 
            
            Log.info(f"{log_tag} sending single sms")
            return send_sms_twilio(self.to, self.text)
        
        if self.provider == "shop":
            pass
        
    def send_bulk_sms(self, message_id=None, business_id=None):
        log_tag = f'[sms_gateway_service.py][SmsGatewayService][send_bulk_sms][{message_id}][{business_id}]'
        
        if self.provider == 'twilio':
            
            # when to_numbers is not a list
            if self.to_numbers is None:
                Log.info(f"{log_tag} Please contact must be a list")
                return prepared_response(False, "VALIDATION_ERROR", f"Please contact must be a list") 
            
            Log.info(f"{log_tag} sending bulk sms")
            return send_bulk_sms_twilio(self.to_numbers, self.text, message_id)
        
        if self.provider == "shop":
            pass
        
    def fetch_message_status(self, sid):
        log_tag = f'[sms_gateway_service.py][SmsGatewayService][send_sms]'
        
        if self.provider == 'twilio':
            
            # when to is not a single
            if sid is None:
                Log.info(f"{log_tag} SID is required")
                return prepared_response(False, "VALIDATION_ERROR", f"SID is required.") 
            
            Log.info(f"{log_tag} retrieving sms status")
            return fetch_message_status(sid)
        
        if self.provider == "shop":
            pass
        
        