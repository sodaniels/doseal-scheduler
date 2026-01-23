import os
import uuid
import boto3
from werkzeug.utils import secure_filename
from flask import request
from urllib.parse import urlparse
from ..utils.logger import Log # import logging

from dotenv import load_dotenv


from app.utils.logger import Log  # import logging
from app.constants.service_code import ALLOWED_EXTENSIONS

# Load environment variables from .env file
load_dotenv()

# Initialize S3 client
session = boto3.session.Session()

s3_client = session.client(
    service_name='s3',
    region_name=os.getenv('DO_SPACES_REGION'),
    endpoint_url=os.getenv('DO_SPACES_ENDPOINT'),
    aws_access_key_id=os.getenv('DO_SPACES_KEY'),
    aws_secret_access_key=os.getenv('DO_SPACES_SECRET')
)

DO_SPACES_BUCKET = os.getenv('DO_SPACES_BUCKET')
DO_SPACES_ORIGIN = os.getenv('DO_SPACES_ORIGIN')


# Maximum file size limit: 10 MB (10 * 1024 * 1024 bytes)
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB in bytes

# Directory to store uploaded images (inside the main directory)
UPLOAD_FOLDER = os.path.join(os.getcwd(), 'static', 'uploads')

# Function to check if the file has a valid extension
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_file(file, business_id):
    """
    This function handles the image upload process.
    It saves the image to the UPLOAD_FOLDER and returns the image URL and actual path.

    Args:
        file (werkzeug.FileStorage): The image file to be uploaded.

    Returns:
        tuple: (image_url, actual_path) 
    """
    client_ip = request.remote_addr
    Log.info(f"[file_upload.py][upload_file]********* file upload request from IP: {client_ip}")
    
    # Check file size
    if file and len(file.read()) > MAX_FILE_SIZE:
        raise ValueError("File size exceeds the 10MB limit.")
    
    # Reset file pointer after size check
    file.seek(0)

    if file and allowed_file(file.filename):
        # Generate a unique filename
        filename = f"{uuid.uuid4().hex}.{file.filename.rsplit('.', 1)[1].lower()}"
        
        # Define the user directory
        udir = str(business_id) 
        dir_path = os.path.join(UPLOAD_FOLDER, udir)
        
        # Create the directory if it doesn't exist
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        # Define the full file path
        file_path = os.path.join(dir_path, filename)

        # Save the file
        file.save(file_path)

        # Construct the file URL (request host + file path)
        host_url = request.host_url  # Get the base URL of the request
        file_url = f"{host_url}static/uploads/{udir}/{filename}"

        # Return the URL for usage in the response and the actual file path for server-side operations
        return file_url, file_path  # Return both the URL and the actual filesystem path
    else:
        raise ValueError("Invalid file type. Allowed types are: png, jpg, jpeg, gif, webp, pdf, docx.")
    
def upload_files(files, business_id):
    """
    This function handles the multiple image upload process.
    It saves the images to the UPLOAD_FOLDER and returns a list of image URLs and their actual paths.

    Args:
        files (werkzeug.FileStorage): The list of image files to be uploaded.

    Returns:
        list: A list of dictionaries with image URL and actual file path.
    """
    client_ip = request.remote_addr
    Log.info(f"[file_upload.py][upload_files]********* file upload request from IP: {client_ip}")

    uploaded_images = []
    
    # Iterate over all files in the 'files' object
    for file in files:
        if file:
            # Check file size (read file content first to check its size)
            file_content = file.read()
            if len(file_content) > MAX_FILE_SIZE:
                raise ValueError("File size exceeds the 3MB limit.")
            
            # Reset file pointer after size check
            file.seek(0)

            if allowed_file(file.filename):
                # Generate a unique filename
                filename = f"{uuid.uuid4().hex}.jpg"
                
                # Define the user directory
                udir = str(business_id)
                dir_path = os.path.join(UPLOAD_FOLDER, udir)

                # Create the directory if it doesn't exist
                if not os.path.exists(dir_path):
                    os.makedirs(dir_path)

                # Define the full file path
                file_path = os.path.join(dir_path, filename)

                # Save the file
                file.save(file_path)

                # Construct the image URL (request host + image name)
                host_url = request.host_url  # Get the base URL of the request
                image_url = f"{host_url}static/uploads/{udir}/{filename}"

                # Append the file's URL and file path as a dictionary
                uploaded_images.append({"url": image_url, "file_path": file_path})
            else:
                raise ValueError("Invalid file type. Allowed types are: png, jpg, jpeg, gif, webp.")

    return uploaded_images
  
def delete_old_image(file_path):
    """
    Given an image URL, delete the corresponding file from local storage.
    
    Args:
        image_url (str): The URL of the old image file.
    """

    # Check if the file exists, and if so, delete it
    if os.path.exists(file_path):
        os.remove(file_path)
        print(f"Deleted the file: {file_path}")
    else:
        print(f"File not found: {file_path}")
    
#upload file to DO bucket        
def upload_file_to_bucket(file_path, remote_path):
    """
    Uploads a file to DigitalOcean Spaces and returns the public URL.

    :param file_path: Local path to the file to upload.
    :param remote_path: Path inside the bucket (e.g., 'folder/filename.jpg').
    :return: Public URL of the uploaded file.
    """
    try:
        s3_client.upload_file(file_path, DO_SPACES_BUCKET, remote_path)
        file_url = f"{DO_SPACES_ORIGIN}/{remote_path}"
        Log.info(f"file_url: {file_url}")
        return file_url
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return None

#upload file to DO bucket with unique filename
def upload_file_to_bucket_unique_filename(file_path, remote_path):
    """
    Uploads a file to DigitalOcean Spaces and returns both
    the public URL and the unique storage path.

    :param file_path: Local path to the file to upload.
    :param remote_path: Base path inside the bucket (e.g., 'folder/filename.jpg').
    :return: dict with 'url' (public URL) and 'path' (remote storage key).
    """
    try:
        # Extract folder and extension
        folder = os.path.dirname(remote_path)
        _, ext = os.path.splitext(remote_path)

        # Generate unique filename
        unique_name = f"{uuid.uuid4().hex}{ext}"

        # Build final remote path (with unique filename)
        final_remote_path = os.path.join(folder, unique_name).replace("\\", "/")

        # Upload file
        s3_client.upload_file(file_path, DO_SPACES_BUCKET, final_remote_path)

        # Public URL
        file_url = f"{DO_SPACES_ORIGIN}/{final_remote_path}"
        Log.info(f"Uploaded to: {file_url}")

        return {"url": file_url, "path": final_remote_path}

    except Exception as e:
        print(f"❌ Upload failed: {e}")
        return None




