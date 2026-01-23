import bcrypt
import jwt
import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from twilio.rest import Client

from redis import Redis
from functools import wraps
from flask_smorest import Blueprint, abort
from flask.views import MethodView
from flask import jsonify, request, g
from pymongo.errors import PyMongoError
from marshmallow import ValidationError
#helper functions
from ....utils.crypt import encrypt_data, decrypt_data, hash_data
from ....utils.extracts import extract_contacts_from_excel
#helper functions
from .admin_business_resource import token_required
from ....models.instntmny.messaging_model import Contacts
from ....models.instntmny.messages_model import Message
from ....utils.logger import Log # import logging
from ....constants.service_code import (
    HTTP_STATUS_CODES,
)
from ....utils.json_response import prepared_response
from ....services.notification_sms import (
    send_bulk_sms_twilio, fetch_message_status
)
from ....services.gateways.sms_gateway_service import SmsGatewayService

from ....schemas.doseal.messaging_schema import (
    ContactUPloadSchema, ContactsSchema, ScheduleSendSchema, GetParamsSchema,
    QuickSendSchema, MessageStatusSchema
)
from ....utils.background import run_bg
from ....services.bg_jobs import send_sms_batch_async
from ....services.bg_schedule_jobs import send_sms_batch_at_async



blp_messaging= Blueprint("Messaging", __name__, description="Messaging Management")


@blp_messaging.route("/contacts-upload", methods=["POST", "GET"])
class MessagingContactUploadResource(MethodView):
    @token_required
    @blp_messaging.doc(
        summary="Set or update contacts for a business",
        description="""
            This endpoint allows you to upload or update contacts under a business.
            - **POST**: Provide the `business_id` and `file` in the form data.
            - The file should be an Excel file with a 'contact' column.
            - The contacts in the file will be extracted and stored in the business.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Only Bearer token authentication is required
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": {
                        "type": "object",
                        "properties": {
                            "business_id": {"type": "string", "description": "ID of the business"},
                            "file": {"type": "string", "format": "binary", "description": "Excel file containing contact information"}
                        },
                        "required": ["business_id", "file"]
                    }
                }
            }
        },
        responses={
            200: {
                "description": "Contacts uploaded and updated successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "message": "Contacts uploaded and updated successfully"
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Missing or invalid Bearer token"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "Failed to upload contacts",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
    @blp_messaging.arguments(ContactUPloadSchema, location="form")
    @blp_messaging.response(200, ContactUPloadSchema)
    def post(self, item_data):
        """Set or update contacts from the uploaded Excel file."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        user_id = str(user_info.get("user_id"))
        user__id = user_info.get("_id")
        
        log_tag = f'[admin_messaging_resource.py][MessagingContactUploadResource][post][{client_ip}][{user_id}]'
        
        try:
            
            item_data["business_id"] = user_info.get("business_id")
            item_data["created_by"] = user__id
            item_data["user__id"] = user__id
            item_data["user_id"] = user_id
            
            # Check if the messaging list already exists based on business_id and name
            Log.info(f"{log_tag}[{client_ip}]checking if messaging list already exists")
            if Contacts.check_item_exists_business_id(item_data["business_id"], key="name", value=item_data["name"]):
                return prepared_response(False, "CONFLICT", "Messaging List with this name already exists.")
            
            # Extract the file from the request
            file = request.files.get('file')  # The file field in the form
            if not file:
                return prepared_response(False, "BAD_REQUEST", "No file uploaded.")

            # Extract contacts from the uploaded Excel file
            contacts_list = extract_contacts_from_excel(file)
            
            # If no contacts are extracted, return an error
            if not contacts_list:
                return prepared_response(False, "BAD_REQUEST", "No valid contacts found in the file.")
            
            item_data["contacts"] = contacts_list
            
            # Create a new Contacts instance and save it
            contact = Contacts(**item_data)
            
            try:
                Log.info(f"{log_tag} committing messaging contacts")
                start_time = time.time()
                contact_id = contact.save()
                end_time = time.time()

                Log.info(f"{log_tag} completed in {end_time - start_time:.2f} sec")

                if contact_id:
                    return prepared_response(True, "CREATED", f"Contacts uploaded and updated successfully.")
                
                Log.info(f"{log_tag} messaging contact")
                return prepared_response(False, "BAD_REQUEST", f"Failed to create messaging contact")

            except PyMongoError as e:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred while creating messaging contact. {str(e)}")
            except Exception as e:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")



        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error processing file: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to process contacts with error: {str(e)}")
 
@blp_messaging.route("/contacts", methods=["GET"])
class MessagingContactResource(MethodView):
   @token_required
   @blp_messaging.doc(
        summary="Retrieve contacts for a business",
        description="""
            This endpoint allows you to retrieve contacts uploaded under a business.
            - **GET**: Provide `business_id` to retrieve contacts.
            - The request requires an `Authorization` header with a Bearer token.
        """,
        security=[{"Bearer": []}],  # Only Bearer token authentication is required
        responses={
            200: {
                "description": "Contacts retrieved successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "success": True,
                            "status_code": 200,
                            "data": [
                                {
                                    "contact": "1234567890",
                                    "name": "John Doe"
                                },
                                {
                                    "contact": "9876543210",
                                    "name": "Alice Smith"
                                }
                            ]
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Missing or invalid Bearer token"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "Failed to retrieve contacts",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        }
    )
   @blp_messaging.arguments(ContactsSchema, location="query")
   @blp_messaging.response(200, ContactsSchema)
   def get(self, item_data):
        """Retrieve contacts for a business."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        business_id = str(user_info.get("business_id"))
        page = item_data.get("page", None)
        per_page = item_data.get("per_page", None)
        
        log_tag = f'[admin_messaging_resource.py][MessagingContactResource][get][{client_ip}][{business_id}]'
        
        try:
            Log.info(f"{log_tag}[{business_id}] retrieving contacts")
            
            # Retrieve contacts from the Contacts collection based on business_id
            contacts = Contacts.get_all(business_id=business_id, page=page, per_page=per_page)

            # If no contacts are found, return a 404
            if not contacts:
                return prepared_response(False, "NOT_FOUND", "No contacts found for this business.")

            # Return the contacts as a response
            return jsonify({
                "success": True,
                "status_code": 200,
                "data": contacts 
            }), 200

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error retrieving contacts: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to retrieve contacts with error: {str(e)}")

@blp_messaging.route("/quick-send", methods=["POST", "GET"])
class QuickSendResource(MethodView):

    # POST quick send
    @token_required
    @blp_messaging.arguments(QuickSendSchema, location="form")
    @blp_messaging.response(201, QuickSendSchema)
    @blp_messaging.doc(
        summary="Create a new sender",
        description="""
            This endpoint allows you to create a new sender. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new sender by providing details such as agent id, full name, phone number, and other required fields.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": QuickSendSchema,
                    "example": {
                        "agent_id": "60a6b938d4d8c24fa0804d62",
                        "full_name": "John Doe",
                        "phone_number": "987-654-3210",
                        "dob": "1990-01-01",
                        "id_type": "Passport",
                        "id_number": "1234567890",
                        "id_expiry": "2030-01-01"
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Sender created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Sender created successfully",
                            "status_code": 200,
                            "success": True
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid authentication token"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "An unexpected error occurred",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def post(self, sender_data):
        """Handle the POST request to create a new sender."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = '[admin_messaging_resource.py][QuickSendResource][post]'
        contact = None

        # Assign user_id and business_id from current user
        sender_data["user_id"] = user_info.get("_id")
        business_id = user_info.get("business_id")
        contact_id = sender_data.get("contact_id")
        sender_data["business_id"] = business_id
        sender_data["user__id"] = user_info.get("_id")
        sender_data["created_by"] = user_info.get("_id")
        admin_id = str(user_info.get("_id"))
        
        message_txt = sender_data.get("message")
        contact_id = sender_data.get("contact_id")
        
        date_str = datetime.now(ZoneInfo("Europe/London")).date().isoformat()
        
                
        # check if the message entry already exists
        try:
            Log.info(f"{log_tag} checking if message already exists")
            if Message.check_item_exists(business_id=business_id, date=date_str, message=message, contact_id=str(contact_id)):
                Log.info(f"{log_tag} This message entry already exist.")
                return prepared_response(False, "CONFLICT", f"This message entry already exist.") 
        except Exception as e:
            Log.info(f"{log_tag} error checking if message already exists. {str(e)}")
        
        # Ensure contact exist for the account
        try:
            Log.info(f"{log_tag} Retrieving beneficiary information.")
            contact = Contacts.get_by_id(
                contact_id=contact_id,
                business_id=business_id,
            )
            Log.info(f"{log_tag} new contact: {contact}")
            
            if contact is None:
                return prepared_response(False, "NOT_FOUND", f"Contact do not exist for this user.") 
            
        except Exception as e:
            Log.info(f"{log_tag} error retrieving contact information: {str(e)}")
            
        # sender_data["status"] = status
        sender_data["date"] = date_str

        
        # Create a new message instance
        message = Message(**sender_data)

        # Try saving the message to the database
        try:
            Log.info(f"{log_tag}[{client_ip}] committing message")
            start_time = time.time()

            message_id = message.save()

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{message_id}] committing message completed in {duration:.2f} seconds")

            # if message was not saved
            if message_id is None:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Failed to create message.")
                
                
            Log.info(f"{log_tag}[{client_ip}][{message_id}] committed message")
            
            contacts = contact.get("contacts")
            # Log.info(f"{log_tag}[{client_ip}] sending sms to contacts: {contacts}")
            Log.info(f"{log_tag}[{client_ip}] queued background SMS to {len(contacts)} contacts")
            
            try:
                # 🔥 Kick off background send (non-blocking)
                run_bg(
                    send_sms_batch_async,
                    message_id=message_id,
                    business_id=str(business_id),
                    text=message_txt,
                    contacts=contacts,
                )
                
                # Return quickly to the client (avoid waiting for Twilio)
                return jsonify({
                    "success": True,
                    "status_code": 200,
                    "message": "Message created and sending has been queued.",
                    "message_id": message_id,
                    "queued": True,
                    "contacts": len(contacts),
                })
            except Exception as e:
                Log.info(f"{log_tag}[{client_ip}][{message_txt}] error sending sms: {e}")
                prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error occurred while sending sms. {str(e)}")
            
            
        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{message_txt}] error committing sender: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error occurred while creating message. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error committing message: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

@blp_messaging.route("/schedule-send", methods=["POST", "GET"])
class ScheduleSendResource(MethodView):
    # POST messages
    @token_required
    @blp_messaging.arguments(ScheduleSendSchema, location="form")
    @blp_messaging.response(201, ScheduleSendSchema)
    def post(self, sender_data):
        """Handle the POST request to schedule and queue an SMS batch for later send."""
        from zoneinfo import ZoneInfo
        from pymongo.errors import PyMongoError

        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = '[admin_messaging_resource.py][ScheduleSendResource][post]'
        contact_doc = None

        # Assign user and business context
        sender_data["user_id"] = user_info.get("_id")
        business_id = user_info.get("business_id")
        contact_id = sender_data.get("contact_id")
        sender_data["business_id"] = business_id
        sender_data["user__id"] = user_info.get("_id")
        sender_data["created_by"] = user_info.get("_id")

        # Extract payload
        message_txt   = sender_data.get("message")
        schedule_raw  = sender_data.get("schedule_date")  # e.g. "2025-10-01 16:30"
        tz_name       = os.getenv("APP_TIMEZONE", "Europe/London")
        tz            = ZoneInfo(tz_name)

        # Parse schedule date (same logic as in bg job)
        def _parse_dt(value: str) -> datetime:
            raw = (value or "").strip()
            if not raw:
                return datetime.now(tz)
            try:
                iso = raw.replace("Z", "+00:00")
                dt = datetime.fromisoformat(iso)
            except Exception:
                dt = None
            if dt is None:
                for fmt in ("%Y-%m-%d %H:%M:%S",
                            "%Y-%m-%d %H:%M",
                            "%Y-%m-%dT%H:%M:%S",
                            "%Y-%m-%dT%H:%M",
                            "%Y-%m-%d"):
                    try:
                        dt = datetime.strptime(raw, fmt)
                        break
                    except Exception:
                        pass
            if dt is None:
                # Bad input → reject clearly
                return None
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=tz)
            return dt

        send_at_dt = _parse_dt(schedule_raw)
        if send_at_dt is None:
            return prepared_response(False, "BAD_REQUEST", "Invalid schedule_date. Use YYYY-MM-DD or YYYY-MM-DD HH:MM[:SS] (ISO 8601 also supported)."), 400

        # Use scheduled date for dedupe hash (your model hashes 'date')
        date_str = send_at_dt.date().isoformat()
        sender_data["date"] = date_str

        # Dedupe against same contact/message/date
        try:
            Log.info(f"{log_tag} checking if message already exists")
            if Message.check_item_exists(business_id=business_id, date=send_at_dt, message=message_txt, contact_id=str(contact_id)):
                Log.info(f"{log_tag} This message entry already exists.")
                return prepared_response(False, "CONFLICT", "This message entry already exists.")
        except Exception as e:
            Log.info(f"{log_tag} error checking if message already exists. {str(e)}")

        # Fetch contact
        try:
            Log.info(f"{log_tag} Retrieving contact information.")
            contact_doc = Contacts.get_by_id(contact_id=contact_id, business_id=business_id)
            if not contact_doc:
                return prepared_response(False, "NOT_FOUND", "Contact does not exist for this user."), 404
        except Exception as e:
            Log.info(f"{log_tag} error retrieving contact information: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", "Error retrieving contact."), 500

        # Persist the scheduled message
        try:
            Log.info(f"{log_tag}[{client_ip}] committing message")
            t0 = time.time()
            msg_model = Message(**sender_data)
            message_id = msg_model.save()
            dt = time.time() - t0
            Log.info(f"{log_tag}[{client_ip}][{message_id}] committed in {dt:.2f}s")
            if not message_id:
                return prepared_response(False, "INTERNAL_SERVER_ERROR", "Failed to create message."), 500
        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}][{message_txt}] DB error committing message: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error occurred while creating message. {str(e)}"), 500
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] unexpected error committing message: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}"), 500

        # Queue background job to send at scheduled time (non-blocking)
        contacts = contact_doc.get("contacts") or []
        try:
            
            Log.info(f"{log_tag}[{client_ip}][{message_id}] scheduling SMS for {send_at_dt.isoformat()} to {len(contacts)} recipients")

            run_bg(
                send_sms_batch_at_async,
                message_id=str(message_id),
                business_id=str(business_id),
                text=message_txt,
                contacts=contacts,
                send_at=send_at_dt.isoformat(),
                tz_name=tz_name,
            )
        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}][{message_id}] failed to queue background SMS: {e}")
            # We still created the message; tell caller scheduling failed
            return prepared_response(
                False, "INTERNAL_SERVER_ERROR",
                f"Message created but scheduling failed: {e}"
            ), 500

        # Respond immediately; do not block for sending
        Log.info(f"{log_tag}[{client_ip}][{message_id}] Message created and sending has been queued.")
        return jsonify({
            "success": True,
            "status_code": 200,
            "message": "Message created and sending has been queued.",
            "message_id": str(message_id),
            "scheduled_for": send_at_dt.isoformat(),
            "queued": True,
            "recipients": len(contacts),
        })

@blp_messaging.route("/messages", methods=["POST", "GET"])
class MessagingContactResource(MethodView):
    
    # GET messages
    @token_required
    @blp_messaging.arguments(GetParamsSchema, location="form")
    @blp_messaging.response(200, GetParamsSchema)
    @blp_messaging.doc(
        summary="Create a new sender",
        description="""
            This endpoint allows you to create a new sender. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new sender by providing details such as agent id, full name, phone number, and other required fields.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": GetParamsSchema,
                    "example": {
                        "agent_id": "60a6b938d4d8c24fa0804d62",
                        "full_name": "John Doe",
                        "phone_number": "987-654-3210",
                        "dob": "1990-01-01",
                        "id_type": "Passport",
                        "id_number": "1234567890",
                        "id_expiry": "2030-01-01"
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Sender created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Sender created successfully",
                            "status_code": 200,
                            "success": True
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid authentication token"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "An unexpected error occurred",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def get(self, sender_data):
        """Handle the GET request to create a new sender."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = '[admin_messaging_resource.py][SenderResource][get]'

        # Assign user_id and business_id from current user
        sender_data["user_id"] = user_info.get("user_id")
        business_id = user_info.get("business_id")
        page = sender_data.get("page")
        per_page = sender_data.get("per_page")
        
        # Try retrieving the messages to the database
        try:
            Log.info(f"{log_tag}[{client_ip}] retrieving messages")
            start_time = time.time()

            messages = Message.get_all(business_id=business_id, page=page, per_page=per_page)

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}] retrieving messages completed in {duration:.2f} seconds")

            # if message was not saved
            if messages is None:
                return prepared_response(False, "NOT_FOUND", f"No messages was found.")
                
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": messages
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}] error retrieving sender: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error occurred while creating message. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error retrieving message: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")


@blp_messaging.route("/message-status", methods=["GET"])
class MessagingStatusResource(MethodView):
    
    # GET messages
    @token_required
    @blp_messaging.arguments(MessageStatusSchema, location="query")
    @blp_messaging.response(200, MessageStatusSchema)
    @blp_messaging.doc(
        summary="Create a new sender",
        description="""
            This endpoint allows you to create a new sender. The request requires an `Authorization` header with a Bearer token.
            - **POST**: Create a new sender by providing details such as agent id, full name, phone number, and other required fields.
        """,
        requestBody={
            "required": True,
            "content": {
                "multipart/form-data": {
                    "schema": MessageStatusSchema,
                    "example": {
                        "agent_id": "60a6b938d4d8c24fa0804d62",
                        "full_name": "John Doe",
                        "phone_number": "987-654-3210",
                        "dob": "1990-01-01",
                        "id_type": "Passport",
                        "id_number": "1234567890",
                        "id_expiry": "2030-01-01"
                    }
                }
            },
        },
        responses={
            201: {
                "description": "Sender created successfully",
                "content": {
                    "application/json": {
                        "example": {
                            "message": "Sender created successfully",
                            "status_code": 200,
                            "success": True
                        }
                    }
                }
            },
            400: {
                "description": "Invalid request data",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 400,
                            "message": "Invalid input data"
                        }
                    }
                }
            },
            401: {
                "description": "Unauthorized request",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 401,
                            "message": "Invalid authentication token"
                        }
                    }
                }
            },
            500: {
                "description": "Internal Server Error",
                "content": {
                    "application/json": {
                        "example": {
                            "success": False,
                            "status_code": 500,
                            "message": "An unexpected error occurred",
                            "error": "Detailed error message here"
                        }
                    }
                }
            }
        },
        security=[{"Bearer": []}],  # Bearer token authentication is required
    )
    def get(self, item_data):
        """Handle the GET request to create a new sender."""
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        log_tag = '[admin_messaging_resource.py][MessagingStatusResource][get]'

        business_id = user_info.get("business_id")
        sid = item_data.get("sid")
        # Try retrieving the messages to the database
        try:
            Log.info(f"{log_tag}[{client_ip}] retrieving messages")
            start_time = time.time()

            sms_gateway_service = SmsGatewayService(
                text="",
                provider="twilio",
            )
            
            messages = sms_gateway_service.fetch_message_status(sid)

            end_time = time.time()
            duration = end_time - start_time
            
            Log.info(f"{log_tag}[{client_ip}][{business_id}] retrieving messages completed in {duration:.2f} seconds")

            # if message was not saved
            if messages is None:
                return prepared_response(False, "NOT_FOUND", f"No messages was found.")
                
            return jsonify({
                "success": True,
                "status_code": HTTP_STATUS_CODES["OK"],
                "data": messages
            }), HTTP_STATUS_CODES["OK"]

        except PyMongoError as e:
            Log.info(f"{log_tag}[{client_ip}] error retrieving sender: {e}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"Error occurred while creating message. {str(e)}")

        except Exception as e:
            Log.info(f"{log_tag}[{client_ip}] error retrieving message: {str(e)}")
            return prepared_response(False, "INTERNAL_SERVER_ERROR", f"An unexpected error occurred. {str(e)}")

