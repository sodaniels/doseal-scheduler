
import os
import base64
import json
import hashlib
import hmac

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Load key from environment and truncate to 32 bytes
key_passphrase = os.getenv('SECRET_KEY')

if not key_passphrase:
    raise ValueError("SECRET_KEY is not set in the environment!")

SECRET_KEY = key_passphrase.encode()[:32]  # Ensure it’s exactly 32 bytes
HASH_KEY = key_passphrase.encode()  # Use full key for HMAC hashing

# AES Encryption
def encrypt_data(data):
    aesgcm = AESGCM(SECRET_KEY)
    nonce = os.urandom(12)  # 96 bits is standard for GCM
    json_data = json.dumps(data).encode()
    encrypted = aesgcm.encrypt(nonce, json_data, None)
    return base64.b64encode(nonce + encrypted).decode()

def decrypt_data(encrypted_data):
    raw = base64.b64decode(encrypted_data)
    nonce = raw[:12]
    ciphertext = raw[12:]
    aesgcm = AESGCM(SECRET_KEY)
    decrypted = aesgcm.decrypt(nonce, ciphertext, None)
    return json.loads(decrypted.decode())


def hash_data(data):
    """Creates an HMAC-SHA256 hash for searching."""
    return hmac.new(HASH_KEY, data.encode(), hashlib.sha256).hexdigest()


# import os
# import base64
# import json
# import hashlib
# import hmac

# from Crypto.Cipher import AES
# from Crypto.Util.Padding import pad, unpad

# # Load key from environment and truncate to 32 bytes
# key_passphrase = os.getenv('SECRET_KEY')

# if not key_passphrase:
#     raise ValueError("SECRET_KEY is not set in the environment!")

# SECRET_KEY = key_passphrase.encode()[:32]  # Ensure it’s exactly 32 bytes
# HASH_KEY = key_passphrase.encode()  # Use full key for HMAC hashing

# # AES Encryption
# def encrypt_data(data):
#     # Ensure the data is serialized and then padded to be a multiple of AES.block_size
#     cipher = AES.new(SECRET_KEY, AES.MODE_CBC)
#     # Use `pad` to ensure the data is a multiple of block size
#     encrypted_bytes = cipher.encrypt(pad(json.dumps(data).encode(), AES.block_size))
#     # Combine IV with the encrypted bytes and base64 encode
#     return base64.b64encode(cipher.iv + encrypted_bytes).decode('utf-8')

# # AES Decryption
# def decrypt_data(encrypted_data):
#     raw_data = base64.b64decode(encrypted_data)
#     iv = raw_data[:16]  # Extract IV
#     encrypted_bytes = raw_data[16:]
#     cipher = AES.new(SECRET_KEY, AES.MODE_CBC, iv)
#     decrypted_data = unpad(cipher.decrypt(encrypted_bytes), AES.block_size).decode('utf-8')
#     return json.loads(decrypted_data)


# def hash_data(data):
#     """Creates an HMAC-SHA256 hash for searching."""
#     return hmac.new(HASH_KEY, data.encode(), hashlib.sha256).hexdigest()


