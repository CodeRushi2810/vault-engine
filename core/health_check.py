import os
import socket
import logging
from dotenv import load_dotenv
from growwapi import GrowwAPI

logger = logging.getLogger("health_check")

def is_connected_to_internet(timeout=3):
    try:
        start = time.time()
        socket.create_connection(("8.8.8.8", 53), timeout=timeout)
        latency = int((time.time() - start) * 1000)
        return True, latency
    except OSError:
        return False, 0

import time

_cached_health = None
_last_health_check_time = 0
_HEALTH_CHECK_INTERVAL = 15

def get_system_health():
    """
    Returns a dictionary detailing the sequential health checks.
    """
    global _cached_health, _last_health_check_time
    now = time.time()
    if _cached_health is not None and (now - _last_health_check_time) < _HEALTH_CHECK_INTERVAL:
        return _cached_health

    health = {
        "internet_ok": False,
        "ping_latency_ms": 0,
        "auth_ok": False,
        "api_ok": False,
        "db_ok": False,
        "overall_ok": False,
        "memory_percent": 0
    }
    
    try:
        import psutil
        health["memory_percent"] = psutil.virtual_memory().percent
    except Exception:
        pass
    
    # 1. Internet Check
    is_connected, latency = is_connected_to_internet()
    if not is_connected:
        logger.warning("Health Check Failed: No Internet Connection.")
        _cached_health = health
        _last_health_check_time = now
        return health
        
    health["internet_ok"] = True
    health["ping_latency_ms"] = latency
    
    # 2. Database Write Check
    data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    if os.access(data_dir, os.W_OK):
        health["db_ok"] = True
    else:
        logger.warning("Health Check Failed: Data directory is not writable.")
        _cached_health = health
        _last_health_check_time = now
        return health

    # 3. Auth & Configuration Check
    from core.auth import get_groww_token
    import contextlib
    try:
        with contextlib.redirect_stdout(open(os.devnull, 'w')):
            token = get_groww_token()
        
        with contextlib.redirect_stdout(open(os.devnull, 'w')):
            groww = GrowwAPI(token)
            
        health["auth_ok"] = True
    except Exception as e:
        logger.warning(f"Health Check Failed: Auth Error ({e})")
        _cached_health = health
        _last_health_check_time = now
        return health
        
    # 4. API Functional Check
    try:
        with contextlib.redirect_stdout(open(os.devnull, 'w')):
            q = groww.get_quote("NIFTY", "NSE", "CASH")
        if q and 'last_price' in q:
            health["api_ok"] = True
            health["overall_ok"] = True
        else:
            logger.warning("Health Check Failed: API Functional Check returned malformed data.")
    except Exception as e:
        logger.warning(f"Health Check Failed: API Error ({e})")
        
    _cached_health = health
    _last_health_check_time = now
    return health
