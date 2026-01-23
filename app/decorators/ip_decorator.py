from flask import request, abort
import ipaddress
from app.utils.logger import Log

def restrict_ip(allowed_ips):
    # Pre-parse allowed IPs/ranges into ipaddress objects
    allowed_networks = []
    for ip in allowed_ips:
        try:
            # If it's a plain IP, treat it as a /32 or /128
            if '/' not in ip:
                # Guess IP type and convert to network
                ip_obj = ipaddress.ip_network(ip + '/32', strict=False)
            else:
                ip_obj = ipaddress.ip_network(ip, strict=False)
            allowed_networks.append(ip_obj)
        except ValueError:
            Log.warning(f"Invalid IP or network in allowed_ips: {ip}")
            continue

    def decorator(func):
        def wrapper(*args, **kwargs):
            client_ip = request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip()
            Log.debug(f"Client IP: {client_ip}")

            try:
                ip_obj = ipaddress.ip_address(client_ip)
                # Check if client_ip is in any allowed network
                if not any(ip_obj in network for network in allowed_networks):
                    Log.warning(f"Forbidden IP: {client_ip}")
                    abort(403)
            except ValueError:
                Log.warning(f"Malformed IP address received: {client_ip}")
                abort(403)

            return func(*args, **kwargs)
        wrapper.__name__ = func.__name__
        return wrapper
    return decorator
