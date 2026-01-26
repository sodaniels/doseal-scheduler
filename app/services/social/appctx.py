from flask import Flask

# IMPORTANT:
# Only import the factory inside the function to avoid circular imports
def get_app() -> Flask:
    from app import create_social_app  # local import prevents circular import
    return create_social_app()

def run_in_app_context(fn, *args, **kwargs):
    app = get_app()
    with app.app_context():
        return fn(*args, **kwargs)