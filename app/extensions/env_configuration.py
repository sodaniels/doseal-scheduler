import os

def env_configuration():
    # MongoDB Atlas connection string and database name
    MONGO_ATLAS_URI = os.getenv("MONGO_ATLAS_URI")
    DB_NAME = os.getenv("DB_NAME", "my_database")

    # Access env variables
    DB_USERNAME = os.getenv("DB_USERNAME")
    DB_PASSWORD = os.getenv("DB_PASSWORD")
    DB_CLUSTER = os.getenv("DB_CLUSTER")
    DB_NAME = os.getenv("DB_NAME")

    # Redis connection details from environment variables
    REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
    REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))