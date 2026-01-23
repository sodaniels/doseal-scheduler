# resources/package_resource.py
from flask import g, request, jsonify
from flask.views import MethodView
from flask_smorest import Blueprint
from marshmallow import ValidationError

from .admin_business_resource import token_required
from ....models.admin.package_model import Package
from ....schemas.admin.package_schema import (
    PackageSchema, PackageUpdateSchema, PackageQuerySchema
)
from ....utils.json_response import prepared_response
from ....utils.helpers import make_log_tag
from ....utils.logger import Log
from ....constants.service_code import SYSTEM_USERS
from ....utils.crypt import decrypt_data

blp_package = Blueprint("packages", __name__, description="Subscription package management")

#GET PACAKGES
@blp_package.route("/packages", methods=["GET"])
class ListPackages(MethodView):
    """List all active packages (public endpoint)."""
    
    def get(self):
        """Get all active subscription packages."""
        
        
        
        try:
            page = request.args.get("page", 1, type=int)
            per_page = request.args.get("per_page", 50, type=int)
            
            result = Package.get_all_active(page, per_page)
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Packages retrieved successfully",
                data=result
            )
            
        except Exception as e:
            Log.error(f"[ListPackages] Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to retrieve packages",
                errors=[str(e)]
            )


#GET SINGKE PACKAGE
@blp_package.route("/package", methods=["GET"])
class GetPackage(MethodView):
    """Get single package details (public endpoint)."""
    
    @blp_package.arguments(PackageQuerySchema, location="query")
    @blp_package.response(200, PackageQuerySchema)
    def get(self, item_data):
        """Get package by ID."""
        
        package_id = item_data.get("package_id")
        
        try:
            package = Package.get_by_id(package_id)
            
            if not package:
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Package not found"
                )
            
            return prepared_response(
                status=True,
                status_code="OK",
                message="Package retrieved successfully",
                data=package
            )
            
        except Exception as e:
            Log.error(f"[GetPackage] Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to retrieve package",
                errors=[str(e)]
            )


#POST PACKAGE
@blp_package.route("/admin/packages", methods=["POST"])
class CreatePackage(MethodView):
    """Create a new package (admin only)."""
    
    @token_required
    @blp_package.arguments(PackageSchema, location="json")
    @blp_package.response(201, PackageSchema)
    def post(self, json_data):
        """Create a new subscription package."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        account_type = decrypt_data(user_info.get("account_type"))
        
        business_id = str(user_info.get("business_id"))
        user_id = str(user_info.get("_id"))
        
        log_tag = make_log_tag(
            "admin_package_resource.py",
            "CreatePackage",
            "post",
            client_ip,
            user_id,
            account_type,
            business_id,
            business_id,
        )
        
        # Only system owner can create packages
        if account_type != SYSTEM_USERS["SYSTEM_OWNER"]:
            Log.info(f"{log_tag} Only system owner can create packages")
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="Only system owner can create packages"
            )
            
            
        # Check if the package already exists for this business
        try:
            Log.info(f"{log_tag} Checking if package already exists")
            exists = Package.check_multiple_item_exists(
                business_id,
                {"name": json_data.get("name")},
            )
        except Exception as e:
            Log.error(f"{log_tag} Error while checking duplicate package: {e}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="An error occurred while validating package uniqueness.",
                errors=[str(e)]
            )

        if exists:
            Log.info(f"{log_tag} Package already exists")
            return prepared_response(
                status=False,
                status_code="CONFLICT",
                message="Package already exists"
            )
        
        try:
            user_id = user_info.get("user_id")
            user__id = str(user_info.get("_id"))
            
            package = Package(
                user_id=user_id,
                user__id=user__id,
                business_id=business_id,
                **json_data
            )
            
            package_id = package.save()
            
            if not package_id:
                Log.info(f"{log_tag} Failed to create package")
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="Failed to create package"
                )
            
            created_package = Package.get_by_id(package_id)
            
            Log.info(f"{log_tag} Package created successfully")
            return prepared_response(
                status=True,
                status_code="CREATED",
                message="Package created successfully",
                data=created_package
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error occurred when creating packge: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to create package",
                errors=[str(e)]
            )

#PUT PACAGE
@blp_package.route("/admin/packages", methods=["PUT"])
class UpdatePackage(MethodView):
    """Update a package (admin only)."""
    
    @token_required
    @blp_package.arguments(PackageUpdateSchema, location="json")
    @blp_package.response(200, PackageUpdateSchema)
    def put(self, item_data):
        """Update a package."""
        
        client_ip = request.remote_addr
        user_info = g.get("current_user", {})
        account_type = decrypt_data(user_info.get("account_type"))
        business_id = str(user_info.get("business_id"))
        user_id = str(user_info.get("_id"))
        
        log_tag = make_log_tag(
            "admin_package_resource.py",
            "CreatePackage",
            "post",
            client_ip,
            user_id,
            account_type,
            business_id,
            business_id,
        )
        
        # Only system owner can create packages
        if account_type != SYSTEM_USERS["SYSTEM_OWNER"]:
            Log.info(f"{log_tag} Only system owner can create packages")
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="Only system owner can create packages"
            )
        
        
        try:
            package_id = item_data.get("package_id")
            item_data.pop("package_id", None)
            
            success = Package.update(package_id, business_id, **item_data)
            
            if not success:
                Log.info(f"{log_tag} Failed to update package")
                return prepared_response(
                    status=False,
                    status_code="INTERNAL_SERVER_ERROR",
                    message="Failed to update package"
                )
            
            updated_package = Package.get_by_id(package_id)
            
            Log.info(f"{log_tag} Package updated successfully")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Package updated successfully",
                data=updated_package
            )
            
        except Exception as e:
            Log.info(f"{log_tag} Error occurred when updating package: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to update package",
                errors=[str(e)]
            )


# DELETE PACKAGE

@blp_package.route("/admin/package", methods=["DELETE"])
class DeletePackage(MethodView):
    """DELETE single package details (public endpoint)."""
    
    @token_required
    @blp_package.arguments(PackageQuerySchema, location="query")
    @blp_package.response(200, PackageQuerySchema)
    def delete(self, item_data):
        """DELETE package by ID."""
        
        client_ip = request.remote_addr
        package_id = item_data.get("package_id")
        user_info = g.get("current_user", {})
        account_type = decrypt_data(user_info.get("account_type"))
        
        business_id = str(user_info.get("business_id"))
        user_id = str(user_info.get("_id"))
        
        log_tag = make_log_tag(
            "admin_package_resource.py",
            "DeletePackage",
            "delete",
            client_ip,
            user_id,
            account_type,
            business_id,
            business_id,
        )
        
        # Only system owner can create packages
        if account_type != SYSTEM_USERS["SYSTEM_OWNER"]:
            Log.info(f"{log_tag} Only system owner can delete a package")
            return prepared_response(
                status=False,
                status_code="FORBIDDEN",
                message="Only system owner can delete a package"
            )
        
        try:
            package = Package.delete(package_id, business_id)
            
            if not package:
                Log.info(f"{log_tag} Only system owner can delete a package")
                return prepared_response(
                    status=False,
                    status_code="NOT_FOUND",
                    message="Package not found"
                )
            
            Log.info(f"{log_tag} Only system owner can delete a package")
            return prepared_response(
                status=True,
                status_code="OK",
                message="Package deleted successfully",
                data=package
            )
            
        except Exception as e:
            Log.error(f"{log_tag} Error: {str(e)}")
            return prepared_response(
                status=False,
                status_code="INTERNAL_SERVER_ERROR",
                message="Failed to deleted package",
                errors=[str(e)]
            )








