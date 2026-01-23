import os
from flask import Flask, g
from werkzeug.middleware.proxy_fix import ProxyFix
from marshmallow import ValidationError
from flask_smorest import Api
from flask_limiter.errors import RateLimitExceeded


from .utils.extensions import limiter
from .extensions import db, redis_connection, jwt, cors
#indexe
from .services.pos_ledger_service import setup_indexes as setup_pos_indexes
from .utils.database_setup import setup_database_indexes

from .config import load_config
from .routes import (
    register_subscriber_routes,
    register_admin_routes,
)
from .middleware.access_mode import detect_access_mode
from .utils.error_handlers import (
    handle_permission_error, handle_validation_error, handle_type_error,
    handle_rate_limit
)
from app.config import load_config
from .middleware.subscription_scheduler import run_scheduled_subscription_activation


# instantiate subscribers app
def create_mto_subscriber_app():
    app = Flask(__name__)
    
    #get actual client IP
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,      # Trust X-Forwarded-For
        x_proto=1,    # Trust X-Forwarded-Proto
        x_host=1,     # Trust X-Forwarded-Host
        x_port=1,     # Trust X-Forwarded-Port
        x_prefix=1    # Trust X-Forwarded-Prefix
    )

    # Load configuration (ensure it does NOT override Flask-Smorest keys)
    load_config(app)

    # Config for MTO
    app.config["API_TITLE"] = "Subscriber API"
    app.config["API_VERSION"] = "v1"
    app.config["OPENAPI_VERSION"] = "3.0.3"
    # 🔥 Critical: The base prefix MUST match how it's mounted!
    app.config["OPENAPI_URL_PREFIX"] = "/api"
    app.config["OPENAPI_JSON_PATH"] = "openapi.json"
    app.config["OPENAPI_SWAGGER_UI_PATH"] = "/docs"
    app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    # Setting jwt secret
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    
    # ✅ Now it's safe to instantiate
    api = Api(app)

    # Initialize all extensions
    db.init_app(app)
    redis_connection.init_app(app)
    jwt.init_app(app)
    cors.init_app(app)

    # Register custom error handlers
    app.errorhandler(PermissionError)(handle_permission_error)
    app.errorhandler(ValidationError)(handle_validation_error)
    app.errorhandler(TypeError)(handle_type_error)
    app.errorhandler(RateLimitExceeded)(handle_rate_limit)

    # Add global middleware
    app.before_request(detect_access_mode)

    # Register all blueprints using `api.register_blueprint(...)`
    register_subscriber_routes(app, api)

    return app

# instantiate admin app
def create_mto_admin_app():
    app = Flask(__name__)
    
    # Init limiter with app
    limiter.init_app(app)
    
    
    #get actual client IP
    app.wsgi_app = ProxyFix(
        app.wsgi_app,
        x_for=1,      # Trust X-Forwarded-For
        x_proto=1,    # Trust X-Forwarded-Proto
        x_host=1,     # Trust X-Forwarded-Host
        x_port=1,     # Trust X-Forwarded-Port
        x_prefix=1    # Trust X-Forwarded-Prefix
    )
    
    
    @app.before_request
    def activate_scheduled_subscriptions():
        # if g.get("current_user"):
        run_scheduled_subscription_activation()

    # Load configuration (ensure it does NOT override Flask-Smorest keys)
    load_config(app)

    # Config for MTO
    app.config["API_TITLE"] = "Administrator API"
    app.config["API_VERSION"] = "v1"
    app.config["OPENAPI_VERSION"] = "3.0.3"
    # 🔥 Critical: The base prefix MUST match how it's mounted!
    app.config["OPENAPI_URL_PREFIX"] = "/api"
    app.config["OPENAPI_JSON_PATH"] = "openapi.json"
    app.config["OPENAPI_SWAGGER_UI_PATH"] = "/docs"
    app.config["OPENAPI_SWAGGER_UI_URL"] = "https://cdn.jsdelivr.net/npm/swagger-ui-dist/"
    # Setting jwt secret
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY")
    
    # ✅ Now it's safe to instantiate
    api = Api(app)

    # Initialize all extensions
    db.init_app(app)
    redis_connection.init_app(app)
    jwt.init_app(app)
    cors.init_app(app)
    
    #Setup database indexes (first run only)
    with app.app_context():
        setup_pos_indexes()
        setup_database_indexes()
    

    # Register custom error handlers
    app.errorhandler(PermissionError)(handle_permission_error)
    app.errorhandler(ValidationError)(handle_validation_error)
    app.errorhandler(TypeError)(handle_type_error)
    app.errorhandler(RateLimitExceeded)(handle_rate_limit)

    # Add global middleware
    app.before_request(detect_access_mode)

    # Register all blueprints using `api.register_blueprint(...)`
    register_admin_routes(app, api)

    return app

