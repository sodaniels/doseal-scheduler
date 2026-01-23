
import redis
import os

# Use environment variables to get Redis host and port (defaulting to 'redis' and '6381' respectively)
redis_host = os.getenv('REDIS_HOST', 'redis')  # 'redis' is the service name from docker-compose
redis_port = int(os.getenv('REDIS_PORT', 6381))  # Default to port 6381 if not set in the environment

# Create a Redis client
client = redis.Redis(host=redis_host, port=redis_port, db=0)

# Function to connect to Redis (with basic error handling)
def connect():
    try:
        client.ping()
        print("Connected to Redis")
    except redis.ConnectionError as err:
        print(f"Redis Client Error: {err}")

# Function to get value from Redis by key
def get_redis(key):
    try:
        return client.get(key)
    except redis.RedisError as err:
        print(f"Error fetching data from Redis: {err}")
        return None

# Function to set value in Redis by key
def set_redis(key, value):
    try:
        return client.set(key, value)
    except redis.RedisError as err:
        print(f"Error setting data in Redis: {err}")

# Function to set value with expiry time in Redis
def set_redis_with_expiry(key, expiry_in_seconds, value):
    try:
        return client.setex(key, expiry_in_seconds, value)
    except redis.RedisError as err:
        print(f"Error setting data with expiry in Redis: {err}")

# Function to remove value from Redis by key
def remove_redis(key):
    try:
        print(f"Removing Redis key: {key}")
        return client.delete(key)
    except redis.RedisError as err:
        print(f"Error removing data from Redis: {err}")

# Connect to Redis
connect()
