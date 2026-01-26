import os
import cloudinary
import cloudinary.uploader

def init_cloudinary():
    cloudinary.config(
        cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
        api_key=os.getenv("CLOUDINARY_API_KEY"),
        api_secret=os.getenv("CLOUDINARY_API_SECRET"),
        secure=True
    )

def upload_image_file(file_storage, folder: str, public_id: str | None = None) -> dict:
    """
    Uploads a Werkzeug FileStorage to Cloudinary and returns {url, public_id, raw}.
    """
    init_cloudinary()

    options = {
        "folder": folder,
        "resource_type": "image",
        "overwrite": True,
    }
    if public_id:
        options["public_id"] = public_id

    # file_storage is request.files["image"]
    result = cloudinary.uploader.upload(file_storage, **options)

    return {
        "url": result.get("secure_url"),
        "public_id": result.get("public_id"),
        "raw": result
    }

def upload_video_file(file_obj, folder: str, public_id: str):
    """
    Uploads a video file to Cloudinary and returns:
      {"url": <secure_url>, "public_id": <public_id>, "raw": <full response>}
    """
    res = cloudinary.uploader.upload(
        file_obj,
        folder=folder,
        public_id=public_id,
        resource_type="video",
        overwrite=True,
        secure=True,
    )

    return {
        "url": res.get("secure_url") or res.get("url"),
        "public_id": res.get("public_id"),
        "raw": res,
    }