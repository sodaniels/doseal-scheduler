from app.extensions.db import db
from flask import jsonify, request, g

from ..constants.service_code import (
    HTTP_STATUS_CODES,
)
from ..utils.logger import Log 
from ..services.shop_api_service import ShopApiService

class Essensial:
    
    @staticmethod
    def countries():
        """
        Retrieve a countries (MongoDB's default identifier).
        """
        try:
            # Query countries  (which is MongoDB's default unique identifier) 
            data = db.get_collection("countries").find({})
            if not data:
                return None
            return data
        except Exception as e:
            
              return None
       
    @staticmethod
    def tenants():
        """
        Retrieve a tenants (MongoDB's default identifier).
        """
        try:
            # Query countries  (which is MongoDB's default unique identifier) 
            data = db.get_collection("tenants").find({})
            if not data:
                return None
            return data
        except Exception as e:
            
              return None
          
    @staticmethod
    def get_tenant_by_id(tenant_id):
        """
        Retrieve a single tenant using MongoDB's default identifier (tenant_id).
        """
        try:
            # Query for a single tenant by ID
            collection = db.get_collection("tenants")
            tenant = collection.find_one({"id": int(tenant_id)})
            if tenant is None:
                return None
            return tenant
        except Exception as e:
            print(f"Error retrieving tenant: {e}")
            return None  
    
    @staticmethod
    def get_tenant_by_iso_2(country_iso_2):
        """
        Retrieve a single tenant using MongoDB's default identifier (country_iso_2).
        """
        try:
            # Query for a single tenant by ID
            tenant = db.get_collection("tenants").find_one({"country_iso_2": str.upper(country_iso_2)})
            if tenant is None:
                return None
            return tenant
        except Exception as e:
            print(f"Error retrieving tenant: {e}")
            return None  
    
    @staticmethod
    def corridors():
        """
        Retrieve corridors (MongoDB's default identifier).
        """
        try:
            # Query corridors  (which is MongoDB's default unique identifier) 
            data = db.get_collection("corridors").find({})
            if not data:
                return None
            return data
        except Exception as e:
            
              return None
       
    @staticmethod
    def corridor(country_iso2):
        """
        Retrieve a corridor (MongoDB's default identifier).
        """
        try:
            # Query corridors  (which is MongoDB's default unique identifier) 
            data = db.get_collection("corridors").find_one({"iso_3166_2": str.upper(country_iso2)})
            if not data:
                response = {
                    "success": False,
                    "status_code": 404
                }
                return response
            
            else:
                
                response = {
                        "success": True,
                        "status_code": 200,
                        "data": data
                    }
                return response
        except Exception as e:
            response = {
                "success": False,
                "status_code": 404
            }
            return response
       
       
   