from bson.objectid import ObjectId
from datetime import datetime
from app.extensions.db import db
from ...models.base_model import BaseModel

class LegalPage(BaseModel):
    """
    LegalPage represents static legal content such as:
    - Terms & Conditions
    - Privacy Policy
    - Refund Policy
    """

    collection_name = "legal_pages"

    def __init__(
        self,
        business_id,
        page_type,          # terms | privacy | refund | cookies | etc
        title,
        content,            # HTML / Markdown
        version="1.0",
        status="draft",     # draft | published | archived
        created_by=None,
        created_at=None,
        updated_at=None,
    ):
        super().__init__(
            business_id=ObjectId(business_id),
            page_type=page_type,
            title=title,
            content=content,
            version=version,
            status=status,
            created_by=ObjectId(created_by) if created_by else None,
            created_at=created_at or datetime.utcnow(),
            updated_at=updated_at or datetime.utcnow(),
        )

    @classmethod
    def get_latest_published_by_type(cls, business_id, page_type):
        try:
            cursor = (
                db.get_collection(cls.collection_name)
                .find({
                    "business_id": ObjectId(business_id),
                    "page_type": page_type,
                    "status": "published"
                })
                .sort("updated_at", -1)
                .limit(1)
            )

            return next(cursor, None)  # ✅ returns None if empty

        except Exception:
            return None
    
    @classmethod
    def get_published_by_id(cls, business_id, page_id):
        """
        Retrieve a specific published legal page by page_id.
        This supports versioning safely.
        """
        try:
            return db.get_collection(cls.collection_name).find_one({
                "_id": ObjectId(page_id),
                "business_id": ObjectId(business_id),
                "status": "published"
            })
        except Exception:
            return None

    @classmethod
    def list_pages(cls, business_id):
        return list(
            db.get_collection(cls.collection_name)
            .find({"business_id": ObjectId(business_id)})
            .sort("updated_at", -1)
        )

    @classmethod
    def publish(cls, page_id, business_id):
        collection = db.get_collection(cls.collection_name)

        page = collection.find_one({
            "_id": ObjectId(page_id),
            "business_id": ObjectId(business_id)
        })
        if not page:
            return False

        # archive previous published version
        collection.update_many(
            {
                "business_id": ObjectId(business_id),
                "page_type": page["page_type"],
                "status": "published"
            },
            {"$set": {"status": "archived"}}
        )

        # publish new version
        collection.update_one(
            {"_id": ObjectId(page_id)},
            {"$set": {"status": "published", "updated_at": datetime.utcnow()}}
        )
        return True