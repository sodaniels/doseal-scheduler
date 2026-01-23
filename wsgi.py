# wsgi.py
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from app import (
    create_mto_subscriber_app,
    create_mto_admin_app, 
)

# admin api base
project_default_app = create_mto_admin_app()

# define all apps in the same DispatcherMiddleware
application = DispatcherMiddleware(project_default_app, {
    "/subscriber": create_mto_subscriber_app(), #for serving subscriber app
})
