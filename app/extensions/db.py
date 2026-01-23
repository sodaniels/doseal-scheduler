import os
from dotenv import load_dotenv
from pymongo import MongoClient
from redis import Redis
from rq import Queue

load_dotenv()

class MongoDB:
    def __init__(self):
        self.client = None
        self.db = None

    def init_app(self, app):
        username = os.getenv("DB_USERNAME")
        password = os.getenv("DB_PASSWORD")
        cluster = os.getenv("DB_CLUSTER")
        db_name = os.getenv("DB_NAME", "my_database")
        
        app_mode = os.getenv("APP_ENV", "development")
        
        if app_mode == "production":
            uri = f"mongodb+srv://{username}:{password}@{cluster}.mongo.ondigitalocean.com/{db_name}?tls=true&authSource=admin&replicaSet=db-zee-instntmny-mto"
        else:
            uri = f"mongodb+srv://{username}:{password}@{cluster}.mongodb.net/{db_name}?tls=true&authSource=admin"

        self.client = MongoClient(uri)
        self.db = self.client[db_name]
        app.mongo = self.db
        
        # -------------------------------------------------
        # ✅ CREATE INDEXES (runs once on startup)
        # -------------------------------------------------

        # stock_ledger indexes
        self.db.stock_ledger.create_index({ "business_id": 1, "outlet_id": 1, "product_id": 1 })
        self.db.stock_ledger.create_index({ "business_id": 1, "outlet_id": 1, "product_id": 1, "composite_variant_id": 1 })
        self.db.stock_ledger.create_index({ "reference_type": 1, "reference_id": 1 })
        self.db.stock_ledger.create_index({ "created_at": -1 })

        # sales indexes
        self.db.sales.create_index({ "business_id": 1, "outlet_id": 1 })
        self.db.sales.create_index({ "business_id": 1, "user__id": 1 })
        self.db.sales.create_index({ "business_id": 1, "status": 1 })
        self.db.sales.create_index({ "created_at": -1 })
        self.db.sales.create_index({ "customer_id": 1 })

    def get_collection(self, name):
        if self.db is None:
            raise RuntimeError("MongoDB not initialized")
        return self.db[name]

class RedisConnection:
    def __init__(self):
        self.connection = None
        self.queue = None

    def init_app(self, app):
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", 6379))
        self.connection = Redis(host=host, port=port)
        self.queue = Queue("emails", connection=self.connection)
        app.queue = self.queue

# Export the instances
db = MongoDB()
redis_connection = RedisConnection()
