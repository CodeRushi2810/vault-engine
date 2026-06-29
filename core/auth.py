import os
import pyotp
from growwapi import GrowwAPI
from dotenv import load_dotenv

# Initialize dotenv to ensure environment variables are loaded
load_dotenv()

# Global cache for the token
_GROWW_TOKEN_CACHE = None

def get_groww_token() -> str:
    """
    Centralized function to fetch and cache the Groww access token.
    Supports TOTP (No-Expiry) Flow via GROWW_TOTP_SECRET and GROWW_TOTP_KEY.
    Falls back to the legacy GROWW_API_SECRET and GROWW_API_KEY.
    """
    global _GROWW_TOKEN_CACHE
    
    # 1. Check if token is already cached in memory
    if _GROWW_TOKEN_CACHE:
        return _GROWW_TOKEN_CACHE
        
    # 2. Check if token was passed via environment variable by the parent process
    env_token = os.environ.get('GROWW_TOKEN')
    if env_token:
        _GROWW_TOKEN_CACHE = env_token
        return _GROWW_TOKEN_CACHE

    # 3. Generate a new token using TOTP Flow (Preferred)
    totp_key = os.environ.get('GROWW_TOTP_KEY')
    totp_secret = os.environ.get('GROWW_TOTP_SECRET')
    
    if totp_key and totp_secret:
        try:
            totp = pyotp.TOTP(totp_secret).now()
            token = GrowwAPI.get_access_token(api_key=totp_key, totp=totp)
            _GROWW_TOKEN_CACHE = token
            # Store in os.environ so child processes spawned after this inherit it
            os.environ['GROWW_TOKEN'] = token
            print("[AUTH] Successfully generated token using new 24/7 TOTP Flow.")
            return token
        except Exception as e:
            print(f"[AUTH] Error authenticating with TOTP: {e}. Falling back to Legacy API Key...")
    api_key = os.environ.get('GROWW_API_KEY')
    api_secret = os.environ.get('GROWW_API_SECRET')
    
    if api_key and api_secret:
        try:
            token = GrowwAPI.get_access_token(api_key=api_key, secret=api_secret)
            _GROWW_TOKEN_CACHE = token
            os.environ['GROWW_TOKEN'] = token
            print("[AUTH] Successfully generated token using Legacy API Key Flow (Fallback).")
            return token
        except Exception as e:
            print(f"Error authenticating with API Secret: {e}")
            raise e
            
    raise ValueError("Missing Groww API credentials in environment variables.")
