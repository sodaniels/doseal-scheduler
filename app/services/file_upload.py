import os
from flask import request, jsonify
import requests
import base64
import json
import mimetypes

from flask_smorest import abort
from app.constants.service_code import SERVICE_CODE

class UploadService:
    def __init__(self, filename) :
        self.filename = filename


        
    def upload_file(file_path):
        """Upload a file to the specified session ID and API URL after validating the file."""
        
        # Check if the file exists
        # if not os.path.isfile(file_path):
        #     print("File not found!")
        #     abort(402, message="File not found")
        #     return
        # Retrieve the file from the request
        if 'file' not in request.files:
            return jsonify({"status": "error", "message": "No file part in the request"}), 400

        file = request.files['file']

        # Check if the file type is allowed
        # filename = os.path.basename(file_path)
        # if not allowed_file(filename):
        #     print(f'File type not allowed. Allowed types: {SERVICE_CODE["ALLOWED_EXTENSIONS"]}')
        #     abort(406, message =f'File type not allowed. Allowed types: {SERVICE_CODE["ALLOWED_EXTENSIONS"]}')
        #     return
        

        # Check if the file size is within the allowed limit
        # file_size = os.path.getsize(file_path)
        # if filename.lower().endswith('pdf') and file_size > SERVICE_CODE["MAX_PDF_SIZE"]:
        #     print(f'PDF file size exceeds the limit of {SERVICE_CODE["MAX_PDF_SIZE"] / (1024 * 1024)} MB.')
        #     abort(406, message=f'PDF file size exceeds the limit of {SERVICE_CODE["MAX_PDF_SIZE"] / (1024 * 1024)} MB.')
        #     return
        # elif filename.lower() not in ['pdf'] and file_size > SERVICE_CODE["MAX_IMAGE_SIZE"]:
        #     print(f'Image file size exceeds the limit of {SERVICE_CODE["MAX_IMAGE_SIZE"] / (1024 * 1024)} MB.')
        #     abort(406, message = f'Image file size exceeds the limit of {SERVICE_CODE["MAX_IMAGE_SIZE"] / (1024 * 1024)} MB.')
        #     return

        # Encode file to base64
        # base64_file = encode_file_to_base64(file_path)
        
        # Determine the MIME type of the file
        # mime_type = mimetypes.guess_type(file_path)[0] or "application/octet-stream"


           # Read file content and encode as Base64
        file_content = file.read()
        file_base64 = base64.b64encode(file_content).decode('utf-8')

        # Generate the required payload structure
        payload = {
            "image": {
                "context": "document-front",
                "content": f"data:{file.content_type};base64,{file_base64}"
            }
        }
        
        return payload

        
        

@staticmethod
def allowed_file(filename):
    """Check if the file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in SERVICE_CODE["ALLOWED_EXTENSIONS"]
@staticmethod
def encode_file_to_base64(file_path):
        """Encode the file to base64."""
        with open(file_path, 'rb') as f:
            file_data = f.read()
            return base64.b64encode(file_data).decode('utf-8')