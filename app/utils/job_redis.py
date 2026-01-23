# app/extensions/cache.py
import os
import redis
from typing import Any, Iterable, Optional, Tuple, List

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "redis")       # docker-compose service name
REDIS_PORT = int(os.getenv("REDIS_PORT", 6381))     # keep your 6381 default
REDIS_DB   = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD") or None

# Single shared client
_client = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=False,  # keep as bytes; decode where needed
)

# -------------------------------------------------------------------
# Connectivity
# -------------------------------------------------------------------
def connect() -> bool:
    """Ping Redis; returns True if reachable."""
    try:
        _client.ping()
        print("Connected to Redis")
        return True
    except redis.ConnectionError as err:
        print(f"Redis Client Error: {err}")
        return False

# -------------------------------------------------------------------
# Client accessor (for queue/worker code)
# -------------------------------------------------------------------
def get_redis(key: Optional[str] = None) -> redis.Redis:
    """
    Return the Redis client. `key` is accepted for compatibility with code
    that calls get_redis(<some_key>), but it's ignored here.
    """
    return _client

# Alias often used in older code (typo-friendly)
def get_redis_client(key: Optional[str] = None) -> redis.Redis:
    return _client

# -------------------------------------------------------------------
# String KV helpers (backward compatible)
# -------------------------------------------------------------------
def get_value(key: str) -> Optional[bytes]:
    """Get raw bytes value for key."""
    try:
        return _client.get(key)
    except redis.RedisError as err:
        print(f"Error fetching data from Redis: {err}")
        return None

# Keep original name for backward compatibility
def get_redis_value(key: str) -> Optional[bytes]:
    return get_value(key)

def set_redis(key: str, value: Any, ttl_seconds: Optional[int] = None) -> bool:
    """
    Set a value. If ttl_seconds is provided, sets expiry (no 'ex=' kwarg required).
    Returns True on success.
    """
    try:
        if ttl_seconds is not None:
            _client.setex(key, ttl_seconds, value)
        else:
            _client.set(key, value)
        return True
    except redis.RedisError as err:
        print(f"Error setting data in Redis: {err}")
        return False

# Provide the misspelling alias used elsewhere
set_redist = set_redis

def set_redis_with_expiry(key: str, expiry_in_seconds: int, value: Any) -> bool:
    """Legacy helper: set value with TTL."""
    try:
        _client.setex(key, expiry_in_seconds, value)
        return True
    except redis.RedisError as err:
        print(f"Error setting data with expiry in Redis: {err}")
        return False

def remove_redis(key: str) -> int:
    """Delete a key. Returns number of keys removed."""
    try:
        return _client.delete(key)
    except redis.RedisError as err:
        print(f"Error removing data from Redis: {err}")
        return 0

def expire(key: str, ttl_seconds: int) -> bool:
    """Apply TTL to an existing key."""
    try:
        return bool(_client.expire(key, ttl_seconds))
    except redis.RedisError as err:
        print(f"Error setting expiry on Redis key: {err}")
        return False

# -------------------------------------------------------------------
# Sorted Set (ZSET) helpers — for schedulers/queues
# -------------------------------------------------------------------
def zadd(key: str, mapping: dict) -> int:
    """
    Add members with scores to a sorted set.
    Example: zadd('myzset', {'member1': 123.0})
    Returns count of new elements added.
    """
    try:
        # redis-py accepts mapping[member] = score
        return int(_client.zadd(key, mapping))
    except redis.RedisError as err:
        print(f"Error zadd on {key}: {err}")
        return 0

def zrange_withscores(key: str, start: int, end: int) -> List[Tuple[bytes, float]]:
    """ZRANGE key start end WITHSCORES."""
    try:
        return _client.zrange(key, start, end, withscores=True)
    except redis.RedisError as err:
        print(f"Error zrange on {key}: {err}")
        return []

def zpopmin(key: str, count: int = 1) -> List[Tuple[bytes, float]]:
    """ZPOPMIN key [count]."""
    try:
        return _client.zpopmin(key, count=count)
    except redis.RedisError as err:
        print(f"Error zpopmin on {key}: {err}")
        return []

def zrem(key: str, *members: str) -> int:
    """ZREM key member [member ...]. Returns number of removed members."""
    try:
        return int(_client.zrem(key, *members))
    except redis.RedisError as err:
        print(f"Error zrem on {key}: {err}")
        return 0

# -------------------------------------------------------------------
# Set helpers (SADD/SMEMBERS/SREM) — for job id tracking
# -------------------------------------------------------------------
def sadd(key: str, *members: str) -> int:
    try:
        return int(_client.sadd(key, *members))
    except redis.RedisError as err:
        print(f"Error sadd on {key}: {err}")
        return 0

def smembers(key: str) -> Iterable[bytes]:
    try:
        return _client.smembers(key)
    except redis.RedisError as err:
        print(f"Error smembers on {key}: {err}")
        return set()

def srem(key: str, *members: str) -> int:
    try:
        return int(_client.srem(key, *members))
    except redis.RedisError as err:
        print(f"Error srem on {key}: {err}")
        return 0

# -------------------------------------------------------------------
# Pipeline helper
# -------------------------------------------------------------------
def pipeline(transaction: bool = True):
    """Return a pipeline you can use with 'with' or manually."""
    try:
        return _client.pipeline(transaction=transaction)
    except redis.RedisError as err:
        print(f"Error creating Redis pipeline: {err}")
        # Fallback: return a pipeline anyway (may raise on use)
        return _client.pipeline(transaction=transaction)

# Connect on import (optional)
connect()

