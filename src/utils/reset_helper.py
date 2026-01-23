import os
from app.utils.redis import (
    get_redis, set_redis
)
from app.utils.logger import Log 
from app.models.business_model import Business


def reset_all_tests():
    try:
        business_id_encoded = get_redis("automated_test_business_id")
        if  business_id_encoded:
            business_id = business_id_encoded.decode("utf-8")
            delete_all = Business.delete_business_with_cascade(business_id)
            Log.info(f"[reset_helper.py][reset_all_tests] delete_all: {delete_all}")
    except Exception as e:
        Log.info(f"[reset_helper.py][reset_all_tests] error deleting business: {str(e)}")