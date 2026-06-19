import os
import sys
import argparse
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from growwapi import GrowwAPI
from core.system_logger import setup_logger

logger = setup_logger("find_token")

def main():
    parser = argparse.ArgumentParser(description="Find the Groww instrument token for a stock symbol.")
    parser.add_argument("symbol", help="The NSE trading symbol (e.g. RELIANCE, TCS)")
    args = parser.parse_args()
    
    symbol = args.symbol.upper()
    
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    API_KEY = os.getenv('GROWW_API_KEY')
    API_SECRET = os.getenv('GROWW_API_SECRET')
    
    if not API_KEY or not API_SECRET:
        logger.error("Missing GROWW_API_KEY or GROWW_API_SECRET in .env file.")
        return
        
    try:
        logger.info(f"Authenticating with Groww API to search for {symbol}...")
        token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
        groww = GrowwAPI(token)
        
        logger.info(f"Searching for {symbol} on NSE...")
        res = groww.get_instrument_by_exchange_and_trading_symbol('NSE', symbol)
        
        if res and 'exchange_token' in res:
            logger.info("=" * 50)
            logger.info(f"✅ FOUND MATCH FOR: {symbol}")
            logger.info(f"   Name: {res.get('name')}")
            logger.info(f"   Token: {res.get('exchange_token')}")
            logger.info("=" * 50)
            logger.info(f"To add this stock, copy this exact line into core/config.py:")
            logger.info(f"    \"{symbol}\": \"{res.get('exchange_token')}\",")
        else:
            logger.error(f"Could not find token for {symbol}. Make sure the symbol is correct.")
            
    except Exception as e:
        logger.error(f"Search failed: {e}")

if __name__ == "__main__":
    main()
