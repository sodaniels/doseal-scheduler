from flask import request, g
from app.utils.logger import Log

def detect_access_mode():
    """
    Detects the user's access mode (emulator, mobile, or web) based on request headers.

    This function determines how a user is accessing the application by inspecting HTTP headers:
      1. If a custom header 'X-Access-Mode' is present, its value is used directly.
      2. If not, the function examines the 'User-Agent' header to identify common emulator signatures
         (such as 'emulator', 'simulator', 'genymotion', 'bluestacks', etc.).
      3. If none of the emulator keywords are found, the function checks for mobile device keywords
         ('mobile', 'android', 'iphone') in the 'User-Agent'.
      4. If none of the above conditions are met, the function defaults to 'web' as the access mode.

    The detected access mode is stored in the Flask `g` context for downstream usage, and all access
    mode detections are logged with the client's IP address.

    Returns:
        None: This function does not return a value. It sets `g.access_mode` for later use in the request context.

    Example usage:
        detect_access_mode()
        # Later in the request: mode = g.access_mode
    """
    client_ip = request.remote_addr
    log_tag = f'[access_mode.py][detect_access_mode][{client_ip}]'

    # Check custom header first
    access_mode = request.headers.get("X-Access-Mode")
    if access_mode:
        Log.info(f"{log_tag} ACCESS MODE: {access_mode}")
        g.access_mode = str.lower(access_mode)
        return

    # Fallback to user-agent
    user_agent = str.lower(request.headers.get("User-Agent", ''))

    # Emulator keywords
    emulator_keywords = [
        'emulator',        # Android Emulator
        'simulator',       # iOS Simulator
        'genymotion',      # Genymotion
        'bluestacks',      # Bluestacks Android Emulator
        'android sdk built', # Android Studio Emulator
        'sdk',             # May appear in emulator UA strings
        'avd'              # Android Virtual Device
    ]

    if any(keyword in user_agent for keyword in emulator_keywords):
        Log.info(f"{log_tag} ACCESS MODE: emulator")
        g.access_mode = 'emulator'
    elif 'mobile' in user_agent or 'android' in user_agent or 'iphone' in user_agent:
        Log.info(f"{log_tag} ACCESS MODE: mobile")
        g.access_mode = 'mobile'
    else:
        Log.info(f"{log_tag} ACCESS MODE: web")
        g.access_mode = 'web'

