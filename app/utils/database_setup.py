# utils/database_setup.py

import os
from pathlib import Path
from ..models.admin.sale import Sale
from ..models.product_model import Product, Discount
from ..models.admin.payment import Payment
from ..models.admin.subscription_model import Subscription
from ..models.admin.package_model import Package
from ..models.admin.setup_model import Outlet
from ..utils.logger import Log

INDEXES_CREATED_FLAG = ".indexes_created"


def should_create_indexes():
    """Check if indexes have already been created."""
    return not os.path.exists(INDEXES_CREATED_FLAG)


def mark_indexes_created():
    """Mark that indexes have been created."""
    Path(INDEXES_CREATED_FLAG).touch()


def setup_database_indexes():
    """
    Create database indexes on first run.
    This runs automatically when the app starts.
    """
    
    log_tag = "[database_setup.py][setup_database_indexes]"
    
    if not should_create_indexes():
        Log.info(f"{log_tag} Indexes already created, skipping...")
        return
    
    Log.info(f"{log_tag} Creating database indexes...")
    
    try:
        Product.create_indexes()
        Sale.create_indexes()
        Discount.create_indexes()
        Payment.create_indexes()
        Subscription.create_indexes()
        Package.create_indexes()
        Outlet.create_indexes()
        
        # Mark as completed
        mark_indexes_created()
        
        Log.info(f"{log_tag} ✅ All indexes created successfully")
        
    except Exception as e:
        Log.error(f"{log_tag} Error: {str(e)}")
        