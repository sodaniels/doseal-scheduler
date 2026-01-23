from dotenv import load_dotenv
load_dotenv()  # Load environment variables from .env file

import os

# Access env variables
DB_USERNAME = os.getenv("DB_USERNAME")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_CLUSTER = os.getenv("DB_CLUSTER")
DB_NAME = os.getenv("DB_NAME")


class Config:MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://{DB_USERNAME}:{DB_PASSWORD}@{DB_CLUSTER}.mongodb.net/{DB_NAME}?retryWrites=true&w=majority')


class Config:
    """Base configuration class."""
    APP_NAME = os.getenv("APP_NAME", "Doseal POS")
    
    SECRET_KEY = os.getenv("SECRET_KEY", "your_default_secret_key")
    DEBUG = os.getenv("FLASK_DEBUG", "True") == "True"
    TESTING = False
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/yourdb")
    # ========================================
    # EXCHANGERATE CONFIGURATION
    # ========================================
    EXCHANGERATE_API_KEY=os.getenv("EXCHANGERATE_API_KEY")
    
    # ========================================
    # HUBTEL CONFIGURATION (Ghana)
    # ========================================
    HUBTEL_CHECKOUT_BASE_URL = os.getenv("HUBTEL_CHECKOUT_BASE_URL")
    HUBTEL_VALIDATE_ACCOUNT_BASE_URL = os.getenv("HUBTEL_VALIDATE_ACCOUNT_BASE_URL")
    HUBTEL_POS_SALES_ID = os.getenv("HUBTEL_POS_SALES_ID")
    HUBTEL_MERCHANT_ACCOUNT_NUMBER = os.getenv("HUBTEL_POS_SALES_ID")
    HUBTEL_PREPAID_DEPOSTI_ACCOUNT = os.getenv("HUBTEL_PREPAID_DEPOSTI_ACCOUNT")
    HUBTEL_USERNAME = os.getenv("HUBTEL_USERNAME")
    HUBTEL_PASSWORD = os.getenv("HUBTEL_PASSWORD")
    
    # URLs
    HUBTEL_CALLBACK_BASE_URL = os.getenv("HUBTEL_CALLBACK_BASE_URL")
    HUBTEL_RETURN_URL = os.getenv("HUBTEL_RETURN_URL")
    HUBTEL_CANCELLATION_URL = os.getenv("HUBTEL_CANCELLATION_URL")
    
    # ========================================
    # M-PESA CONFIGURATION
    # ========================================
    
    MPESA_ENVIRONMENT = os.getenv('MPESA_ENVIRONMENT', 'sandbox')  # 'sandbox' or 'production'
    MPESA_CONSUMER_KEY = os.getenv('MPESA_CONSUMER_KEY')
    MPESA_CONSUMER_SECRET = os.getenv('MPESA_CONSUMER_SECRET')
    MPESA_SHORTCODE = os.getenv('MPESA_SHORTCODE')
    MPESA_PASSKEY = os.getenv('MPESA_PASSKEY')
    MPESA_CALLBACK_URL = os.getenv('MPESA_CALLBACK_URL', 'https://yourdomain.com/api/v1/webhooks/payment/mpesa')
    MPESA_SECURITY_CREDENTIAL = os.getenv('MPESA_SECURITY_CREDENTIAL')
    
    # M-Pesa API URLs
    if MPESA_ENVIRONMENT == 'production':
        MPESA_BASE_URL = 'https://api.safaricom.co.ke'
    else:
        MPESA_BASE_URL = 'https://sandbox.safaricom.co.ke'

class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True
    MONGO_URI = os.getenv(f"mongodb+srv://{DB_USERNAME}:{DB_PASSWORD}@{DB_CLUSTER}.mongodb.net/{DB_NAME}?retryWrites=true&w=majority", "mongodb://localhost:27017/devdb")

class TestingConfig(Config):
    """Testing configuration."""
    DEBUG = False
    TESTING = True
    MONGO_URI = os.getenv("TEST_MONGO_URI", "mongodb://localhost:27017/testdb")

class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    MONGO_URI = os.getenv("PROD_MONGO_URI", "mongodb://localhost:27017/proddb")
    
    
def load_config(app):
    load_dotenv()
    app.config["MONGO_URI"] = f"mongodb+srv://{os.getenv('DB_USERNAME')}:{os.getenv('DB_PASSWORD')}@{os.getenv('DB_CLUSTER')}.mongodb.net/{os.getenv('DB_NAME')}?retryWrites=true&w=majority"
    app.config["REDIS_HOST"] = os.getenv("REDIS_HOST", "localhost")
    app.config["REDIS_PORT"] = int(os.getenv("REDIS_PORT", 6379))
    app.config["ALLOWED_ORIGINS"] = [os.getenv('ZEEPAY_SOURCES_FOR_CORS')]