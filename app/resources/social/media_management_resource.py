#app/resources/social/scheduled_posts_resources.py

from datetime import datetime, timezone
import uuid
import os

from flask.views import MethodView
from flask import request, jsonify, g
from flask_smorest import Blueprint
from ...constants.service_code import HTTP_STATUS_CODES
from ..doseal.admin.admin_business_resource import token_required
from ...utils.logger import Log
from ...utils.media.cloudinary_client import (
    upload_image_file, upload_video_file
)

blp_media_management = Blueprint("media_management", __name__)


# -------------------------------------------
# Helpers
# -------------------------------------------
def _utc_now() -> datetime:
    return datetime.now(timezone.utc)

# -------------------------------------------
# Upload: Image
# -------------------------------------------
@blp_media_management.route("/social/media/upload-image", methods=["POST"])
class UploadImageResource(MethodView):
    @token_required
    def post(self):
        log_tag = "[media_management_resource.py][UploadImageResource][post]"
        user = g.get("current_user", {}) or {}

        if "image" not in request.files:
            return jsonify({"success": False, "message": "image file is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        image = request.files["image"]
        if not image or image.filename == "":
            return jsonify({"success": False, "message": "invalid image"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        if not (image.mimetype or "").startswith("image/"):
            return jsonify({"success": False, "message": "file must be an image"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        if not business_id or not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        folder = f"social/{business_id}/{user_id}"
        public_id = uuid.uuid4().hex

        try:
            Log.info(f"{log_tag} Uploading image for business_id: {business_id}, user_id: {user_id}, filename: {image.filename}")
            uploaded = upload_image_file(image, folder=folder, public_id=public_id)
            raw = uploaded.get("raw") or {}
            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    "asset_id": uploaded.get("public_id"),
                    "public_id": uploaded.get("public_id"),
                    "asset_provider": "cloudinary",
                    "asset_type": "image",
                    "url": uploaded.get("url"),

                    "width": raw.get("width"),
                    "height": raw.get("height"),
                    "format": raw.get("format"),
                    "bytes": raw.get("bytes"),
                    "created_at": _utc_now().isoformat(),
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} upload failed: {e}")
            return jsonify({"success": False, "message": "upload failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------
# Upload: Video
# -------------------------------------------
@blp_media_management.route("/social/media/upload-video", methods=["POST"])
class UploadVideoResource(MethodView):
    @token_required
    def post(self):
        log_tag = "[media_management_resource.py][UploadVideoResource][post]"
        user = g.get("current_user", {}) or {}

        if "video" not in request.files:
            return jsonify({"success": False, "message": "video file is required"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        video = request.files["video"]
        if not video or video.filename == "":
            return jsonify({"success": False, "message": "invalid video"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        # allow octet-stream too (Postman sometimes sends it)
        mt = (video.mimetype or "").lower()
        if not (mt.startswith("video/") or mt == "application/octet-stream"):
            return jsonify({"success": False, "message": "file must be a video"}), HTTP_STATUS_CODES["BAD_REQUEST"]

        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        if not business_id or not user_id:
            return jsonify({"success": False, "message": "Unauthorized"}), HTTP_STATUS_CODES["UNAUTHORIZED"]

        folder = f"social/{business_id}/{user_id}"
        public_id = uuid.uuid4().hex

        try:
            Log.info(f"{log_tag} Uploading video for business_id: {business_id}, user_id: {user_id}, filename: {video.filename}")
            uploaded = upload_video_file(video, folder=folder, public_id=public_id)
            raw = uploaded.get("raw") or {}

            return jsonify({
                "success": True,
                "message": "uploaded",
                "data": {
                    "asset_id": uploaded.get("public_id"),
                    "public_id": uploaded.get("public_id"),
                    "asset_provider": "cloudinary",
                    "asset_type": "video",
                    "url": uploaded.get("url"),

                    # ✅ important for reels flows and platform rules
                    "bytes": raw.get("bytes"),

                    "duration": raw.get("duration"),
                    "format": raw.get("format"),
                    "width": raw.get("width"),
                    "height": raw.get("height"),
                    "created_at": _utc_now().isoformat(),
                }
            }), HTTP_STATUS_CODES["OK"]

        except Exception as e:
            Log.info(f"{log_tag} upload failed: {e}")
            return jsonify({"success": False, "message": "upload failed"}), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------
# List: All Media (Images & Videos)
# -------------------------------------------
@blp_media_management.route("/social/media/list", methods=["GET"])
class ListMediaResource(MethodView):
    """
    List all uploaded media (images and videos) for a business.
    
    Query Parameters:
        - type: Filter by media type ('image', 'video', 'all'). Default: 'all'
        - page: Page number (1-indexed). Default: 1
        - per_page: Items per page (max 100). Default: 20
        - sort_by: Sort field ('created_at', 'bytes', 'format'). Default: 'created_at'
        - sort_order: Sort order ('asc', 'desc'). Default: 'desc'
    
    Returns:
        List of media assets with metadata
    """
    
    @token_required
    def get(self):
        log_tag = "[media_management_resource.py][ListMediaResource][get]"
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        
        if not business_id or not user_id:
            return jsonify({
                "success": False, 
                "message": "Unauthorized"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
        
        # Query parameters
        media_type = request.args.get("type", "all").lower()
        page = request.args.get("page", 1, type=int)
        per_page = request.args.get("per_page", 20, type=int)
        sort_by = request.args.get("sort_by", "created_at")
        sort_order = request.args.get("sort_order", "desc")
        
        # Validate parameters
        if media_type not in ["image", "video", "all"]:
            media_type = "all"
        
        if page < 1:
            page = 1
        
        if per_page < 1:
            per_page = 20
        elif per_page > 100:
            per_page = 100
        
        if sort_order not in ["asc", "desc"]:
            sort_order = "desc"
        
        try:
            import cloudinary
            import cloudinary.api
            
            # The folder where media is stored
            folder_prefix = f"social/{business_id}/{user_id}"
            
            all_resources = []
            
            # Fetch images if needed
            Log.info(f"{log_tag} Listing media for business_id: {business_id}, user_id: {user_id}, type: {media_type}")
            if media_type in ["image", "all"]:
                try:
                    image_result = cloudinary.api.resources(
                        type="upload",
                        resource_type="image",
                        prefix=folder_prefix,
                        max_results=500,  # Cloudinary max per request
                    )
                    
                    for resource in image_result.get("resources", []):
                        all_resources.append({
                            "asset_id": resource.get("asset_id"),
                            "public_id": resource.get("public_id"),
                            "asset_provider": "cloudinary",
                            "asset_type": "image",
                            "url": resource.get("secure_url") or resource.get("url"),
                            "width": resource.get("width"),
                            "height": resource.get("height"),
                            "format": resource.get("format"),
                            "bytes": resource.get("bytes"),
                            "created_at": resource.get("created_at"),
                            "folder": resource.get("folder"),
                        })
                except Exception as e:
                    Log.warning(f"{log_tag} Error fetching images: {e}")
            
            # Fetch videos if needed
            if media_type in ["video", "all"]:
                try:
                    video_result = cloudinary.api.resources(
                        type="upload",
                        resource_type="video",
                        prefix=folder_prefix,
                        max_results=500,
                    )
                    
                    for resource in video_result.get("resources", []):
                        all_resources.append({
                            "asset_id": resource.get("asset_id"),
                            "public_id": resource.get("public_id"),
                            "asset_provider": "cloudinary",
                            "asset_type": "video",
                            "url": resource.get("secure_url") or resource.get("url"),
                            "width": resource.get("width"),
                            "height": resource.get("height"),
                            "format": resource.get("format"),
                            "bytes": resource.get("bytes"),
                            "duration": resource.get("duration"),
                            "created_at": resource.get("created_at"),
                            "folder": resource.get("folder"),
                        })
                except Exception as e:
                    Log.warning(f"{log_tag} Error fetching videos: {e}")
            
            # Sort resources
            reverse_sort = sort_order == "desc"
            
            if sort_by == "created_at":
                all_resources.sort(
                    key=lambda x: x.get("created_at") or "", 
                    reverse=reverse_sort
                )
            elif sort_by == "bytes":
                all_resources.sort(
                    key=lambda x: x.get("bytes") or 0, 
                    reverse=reverse_sort
                )
            elif sort_by == "format":
                all_resources.sort(
                    key=lambda x: x.get("format") or "", 
                    reverse=reverse_sort
                )
            
            # Pagination
            total_count = len(all_resources)
            total_pages = (total_count + per_page - 1) // per_page if total_count > 0 else 1
            
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_resources = all_resources[start_idx:end_idx]
            
            return jsonify({
                "success": True,
                "message": "Media retrieved successfully",
                "data": {
                    "media": paginated_resources,
                    "pagination": {
                        "current_page": page,
                        "per_page": per_page,
                        "total_count": total_count,
                        "total_pages": total_pages,
                        "has_next": page < total_pages,
                        "has_prev": page > 1,
                    },
                    "filters": {
                        "type": media_type,
                        "sort_by": sort_by,
                        "sort_order": sort_order,
                    },
                }
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            Log.error(f"{log_tag} Error listing media: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False, 
                "message": "Failed to retrieve media"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]

# -------------------------------------------
# Get: Single Media Details (Query Parameter)
# -------------------------------------------
@blp_media_management.route("/social/media/details", methods=["GET"])
class GetMediaResource(MethodView):
    """
    Get details of a single media asset.
    
    Query Parameters:
        - public_id: The Cloudinary public ID of the asset (REQUIRED)
        - type: Media type ('image' or 'video'). Default: 'image'
    
    Example:
        GET /social/media/details?public_id=social/123/456/abc123&type=image
    """
    
    @token_required
    def get(self):
        log_tag = "[media_management_resource.py][GetMediaResource][get]"
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        
        if not business_id or not user_id:
            return jsonify({
                "success": False, 
                "message": "Unauthorized"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
        
        # Get query parameters
        public_id = request.args.get("public_id", "").strip()
        media_type = request.args.get("type", "image").lower()
        
        if not public_id:
            return jsonify({
                "success": False, 
                "message": "public_id query parameter is required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if media_type not in ["image", "video"]:
            media_type = "image"
        
        Log.info(f"{log_tag} Getting media: {public_id}, type: {media_type}")
        
        try:
            import cloudinary
            import cloudinary.api
            
            Log.info(f"{log_tag} Fetching media details for public_id: {public_id}, media_type: {media_type}")
            # Security check: Ensure the public_id belongs to this user
            expected_prefix = f"social/{business_id}/{user_id}"
            if not public_id.startswith(expected_prefix):
                Log.warning(f"{log_tag} Access denied. Expected prefix: {expected_prefix}, Got: {public_id}")
                return jsonify({
                    "success": False, 
                    "message": "Media not found or access denied"
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            # Get resource details
            resource_type = "image" if media_type == "image" else "video"
            
            resource = cloudinary.api.resource(
                public_id,
                resource_type=resource_type,
            )
            
            result = {
                "asset_id": resource.get("asset_id"),
                "public_id": resource.get("public_id"),
                "asset_provider": "cloudinary",
                "asset_type": media_type,
                "url": resource.get("secure_url") or resource.get("url"),
                "width": resource.get("width"),
                "height": resource.get("height"),
                "format": resource.get("format"),
                "bytes": resource.get("bytes"),
                "created_at": resource.get("created_at"),
                "folder": resource.get("folder"),
            }
            
            # Add video-specific fields
            if media_type == "video":
                result["duration"] = resource.get("duration")
                result["frame_rate"] = resource.get("frame_rate")
                result["bit_rate"] = resource.get("bit_rate")
                result["audio"] = resource.get("audio")
            
            return jsonify({
                "success": True,
                "message": "Media retrieved successfully",
                "data": result
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str or "resource not found" in error_str:
                return jsonify({
                    "success": False, 
                    "message": "Media not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            Log.error(f"{log_tag} Error getting media: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False, 
                "message": "Failed to retrieve media"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]         
            

# -------------------------------------------
# Delete: Single Media (Query Parameter)
# -------------------------------------------
@blp_media_management.route("/social/media/delete", methods=["DELETE"])
class DeleteMediaResource(MethodView):
    """
    Delete a media asset from Cloudinary.
    
    Query Parameters:
        - public_id: The Cloudinary public ID of the asset (REQUIRED)
        - type: Media type ('image' or 'video'). Default: 'image'
    
    Example:
        DELETE /social/media/delete?public_id=social/123/456/abc123&type=image
    """
    
    @token_required
    def delete(self):
        log_tag = "[media_management_resource.py][DeleteMediaResource][delete]"
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        
        if not business_id or not user_id:
            return jsonify({
                "success": False, 
                "message": "Unauthorized"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
        
        # Get query parameters
        public_id = request.args.get("public_id", "").strip()
        media_type = request.args.get("type", "image").lower()
        
        if not public_id:
            return jsonify({
                "success": False, 
                "message": "public_id query parameter is required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if media_type not in ["image", "video"]:
            media_type = "image"
        
        Log.info(f"{log_tag} Deleting media: {public_id}, type: {media_type}")
        
        try:
            import cloudinary
            import cloudinary.uploader
            
            Log.info(f"{log_tag} Deleting media for public_id: {public_id}, media_type: {media_type}")
            # Security check: Ensure the public_id belongs to this user
            expected_prefix = f"social/{business_id}/{user_id}"
            if not public_id.startswith(expected_prefix):
                Log.warning(f"{log_tag} Access denied. Expected prefix: {expected_prefix}, Got: {public_id}")
                return jsonify({
                    "success": False, 
                    "message": "Media not found or access denied"
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            # Delete resource
            resource_type = "image" if media_type == "image" else "video"
            
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type,
            )
            
            if result.get("result") == "ok":
                Log.info(f"{log_tag} Media deleted successfully: {public_id}")
                
                return jsonify({
                    "success": True,
                    "message": "Media deleted successfully",
                    "data": {
                        "public_id": public_id,
                        "deleted": True,
                    }
                }), HTTP_STATUS_CODES["OK"]
            
            elif result.get("result") == "not found":
                return jsonify({
                    "success": False,
                    "message": "Media not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            else:
                Log.warning(f"{log_tag} Delete result: {result}")
                
                return jsonify({
                    "success": False,
                    "message": "Failed to delete media",
                    "data": result
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        except Exception as e:
            error_str = str(e).lower()
            if "not found" in error_str:
                return jsonify({
                    "success": False, 
                    "message": "Media not found"
                }), HTTP_STATUS_CODES["NOT_FOUND"]
            
            Log.error(f"{log_tag} Error deleting media: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False, 
                "message": "Failed to delete media"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]


# -------------------------------------------
# Delete: Multiple Media (Bulk Delete)
# -------------------------------------------
@blp_media_management.route("/social/media/bulk-delete", methods=["POST"])
class BulkDeleteMediaResource(MethodView):
    """
    Delete multiple media assets from Cloudinary.
    
    Body:
    {
        "public_ids": ["social/123/456/abc123", "social/123/456/def456"],
        "type": "image"  // or "video" or "all"
    }
    """
    
    @token_required
    def post(self):
        log_tag = "[media_management_resource.py][BulkDeleteMediaResource][post]"
        user = g.get("current_user", {}) or {}
        
        business_id = str(user.get("business_id") or "")
        user_id = str(user.get("_id") or "")
        
        if not business_id or not user_id:
            return jsonify({
                "success": False, 
                "message": "Unauthorized"
            }), HTTP_STATUS_CODES["UNAUTHORIZED"]
        
        body = request.get_json(silent=True) or {}
        public_ids = body.get("public_ids", [])
        media_type = body.get("type", "all").lower()
        
        if not public_ids or not isinstance(public_ids, list):
            return jsonify({
                "success": False, 
                "message": "public_ids array is required"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if len(public_ids) > 100:
            return jsonify({
                "success": False, 
                "message": "Maximum 100 items per request"
            }), HTTP_STATUS_CODES["BAD_REQUEST"]
        
        if media_type not in ["image", "video", "all"]:
            media_type = "all"
        
        Log.info(f"{log_tag} Bulk deleting {len(public_ids)} media items, type: {media_type}")
        
        try:
            import cloudinary
            import cloudinary.api
            
            Log.info(f"{log_tag} Fetching media details for bulk delete. Total requested: {len(public_ids)}")
            # Security check: Filter only public_ids belonging to this user
            expected_prefix = f"social/{business_id}/{user_id}"
            valid_public_ids = [
                pid for pid in public_ids 
                if isinstance(pid, str) and pid.strip().startswith(expected_prefix)
            ]
            
            invalid_count = len(public_ids) - len(valid_public_ids)
            if invalid_count > 0:
                Log.warning(f"{log_tag} {invalid_count} invalid public_ids filtered out")
            
            if not valid_public_ids:
                return jsonify({
                    "success": False, 
                    "message": "No valid media found to delete"
                }), HTTP_STATUS_CODES["BAD_REQUEST"]
            
            deleted = []
            failed = []
            
            # Delete images
            if media_type in ["image", "all"]:
                try:
                    result = cloudinary.api.delete_resources(
                        valid_public_ids,
                        resource_type="image",
                    )
                    
                    for pid, status in result.get("deleted", {}).items():
                        if status == "deleted":
                            deleted.append({"public_id": pid, "type": "image"})
                        elif status == "not_found":
                            # Don't add to failed yet, might be a video
                            pass
                        else:
                            failed.append({"public_id": pid, "type": "image", "reason": status})
                except Exception as e:
                    Log.warning(f"{log_tag} Error deleting images: {e}")
            
            # Delete videos
            if media_type in ["video", "all"]:
                try:
                    result = cloudinary.api.delete_resources(
                        valid_public_ids,
                        resource_type="video",
                    )
                    
                    for pid, status in result.get("deleted", {}).items():
                        if status == "deleted":
                            # Only add if not already deleted as image
                            if not any(d["public_id"] == pid for d in deleted):
                                deleted.append({"public_id": pid, "type": "video"})
                        elif status == "not_found":
                            # Only add to failed if not found in both image and video
                            if not any(d["public_id"] == pid for d in deleted):
                                if not any(f["public_id"] == pid for f in failed):
                                    failed.append({"public_id": pid, "type": "unknown", "reason": "not_found"})
                        else:
                            if not any(d["public_id"] == pid for d in deleted):
                                failed.append({"public_id": pid, "type": "video", "reason": status})
                except Exception as e:
                    Log.warning(f"{log_tag} Error deleting videos: {e}")
            
            Log.info(f"{log_tag} Bulk delete complete: {len(deleted)} deleted, {len(failed)} failed")
            
            return jsonify({
                "success": True,
                "message": f"Deleted {len(deleted)} media items",
                "data": {
                    "deleted": deleted,
                    "failed": failed,
                    "summary": {
                        "total_requested": len(public_ids),
                        "total_valid": len(valid_public_ids),
                        "total_deleted": len(deleted),
                        "total_failed": len(failed),
                    },
                }
            }), HTTP_STATUS_CODES["OK"]
        
        except Exception as e:
            Log.error(f"{log_tag} Error in bulk delete: {e}")
            import traceback
            traceback.print_exc()
            
            return jsonify({
                "success": False, 
                "message": "Failed to delete media"
            }), HTTP_STATUS_CODES["INTERNAL_SERVER_ERROR"]






































