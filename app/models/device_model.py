from datetime import datetime
from app.extensions.db import db

class Device:
    collection_name = 'devices'
    def __init__(self, uuid, model, osVersion, sdkVersion, deviceType, os, language, manufacturer, region, created_at=None):
        # Device fields
        self.uuid = uuid
        self.model = model
        self.osVersion = osVersion
        self.sdkVersion = sdkVersion
        self.deviceType = deviceType
        self.os = os
        self.language = language
        self.manufacturer = manufacturer
        self.region = region

        # Timestamp for creation
        self.created_at = created_at or datetime.now()

    def to_dict(self):
        """
        Convert the device object to a dictionary representation.
        """
        return {
            "uuid": self.uuid,
            "model": self.model,
            "osVersion": self.osVersion,
            "sdkVersion": self.sdkVersion,
            "deviceType": self.deviceType,
            "os": self.os,
            "language": self.language,
            "manufacturer": self.manufacturer,
            "region": self.region,
            "created_at": self.created_at,
        }

    def save(self):
        """
        Save the device information to the 'devices' collection in the database.
        """
        device_collection = db.get_collection(self.collection_name)  # Use the 'devices' collection
        result = device_collection.insert_one(self.to_dict())  # Insert the device data into the collection
        return str(result.inserted_id)  # Return the inserted device's ObjectId as a string

    @classmethod
    def check_item_exists(cls, uuid):
        """
        Check if a device entry exists based on the UUID.
        Queries the database using only the uuid.

        :param uuid: The UUID of the device to check.
        :return: True if the device exists, False otherwise.
        """
        try:
            # Define the query to check the existence of the device based on uuid
            query = {
                "uuid": uuid
            }

            # Access the relevant collection in the database
            collection = db.get_collection(cls.collection_name)

            # Query the database for the recipient with the given uuid
            existing_item = collection.find_one(query)

            # Return True if the item exists, otherwise False
            return True if existing_item else False

        except Exception as e:
            print(f"Error occurred in check_item_exists: {e}")
            return False

    @classmethod
    def get_by_uuid(cls, uuid):
        """
        Retrieve a device by its UUID.
        """
        device_collection = db.get_collection('devices')  # Use the 'devices' collection
        data = device_collection.find_one({"uuid": uuid})

        if not data:
            return None  # Device not found

        # Convert ObjectId to string and return the data
        data["_id"] = str(data["_id"])
        return data

    @classmethod
    def get_all(cls, page=1, per_page=10, start_date=None, end_date=None,
                os=None, manufacturer=None):
        """
        Retrieve all devices with pagination and optional filters:
        - start_date, end_date (created_at range)
        - os (exact match, e.g. 'iOS', 'Android')
        - manufacturer (exact match, e.g. 'Apple', 'Samsung')
        """
        device_collection = db.get_collection('devices')

        # Build query dynamically
        query = {}

        # Date range filter
        if start_date or end_date:
            query["created_at"] = {}
            if start_date:
                if isinstance(start_date, str):
                    start_date = datetime.strptime(start_date, "%Y-%m-%d")
                query["created_at"]["$gte"] = start_date
            if end_date:
                if isinstance(end_date, str):
                    end_date = datetime.strptime(end_date, "%Y-%m-%d")
                query["created_at"]["$lte"] = end_date

        # OS filter (exact match)
        if os:
            query["os"] = os

        # Manufacturer filter (exact match)
        if manufacturer:
            query["manufacturer"] = manufacturer

        # Count total results
        total_count = device_collection.count_documents(query)

        # Apply filters, pagination, and sorting
        devices_cursor = (
            device_collection.find(query)
            .sort("created_at", -1)  # Newest first
            .skip((page - 1) * per_page)
            .limit(per_page)
        )

        # Prepare results
        result = []
        for device in devices_cursor:
            device["_id"] = str(device["_id"])
            result.append(device)

        # Total pages
        total_pages = (total_count + per_page - 1) // per_page

        return {
            "devices": result,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page,
            "per_page": per_page
        }
