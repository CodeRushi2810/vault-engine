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
    
    try:
        logger.info(f"Authenticating with Groww API to search for {symbol}...")
        from core.auth import get_groww_token
        token = get_groww_token()
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
