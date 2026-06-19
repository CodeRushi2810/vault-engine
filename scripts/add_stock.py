import os
import sys
import argparse
import subprocess
import re
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from growwapi import GrowwAPI
from core.system_logger import setup_logger

logger = setup_logger("add_stock")

def update_config(symbol, token):
    config_path = os.path.join(BASE_DIR, "core", "config.py")
    with open(config_path, "r") as f:
        content = f.read()
        
    if f'"{symbol}"' in content or f"'{symbol}'" in content:
        logger.warning(f"Stock {symbol} is already in core/config.py!")
        return True # Return true so the pipeline continues
        
    # Inject right after STOCK_TOKENS = {
    new_content = re.sub(
        r'(STOCK_TOKENS\s*=\s*\{)', 
        f'\\1\n    "{symbol}": "{token}",', 
        content, 
        count=1
    )
    
    if new_content == content:
        logger.error("Could not find STOCK_TOKENS dictionary in core/config.py")
        return False
        
    with open(config_path, "w") as f:
        f.write(new_content)
        
    logger.info(f"? Automatically added {symbol}:{token} to core/config.py")
    return True

def run_pipeline(symbol):
    symbol = symbol.upper()
    logger.info(f"?? Starting automation pipeline for {symbol}")
    
    load_dotenv(os.path.join(BASE_DIR, '.env'))
    API_KEY = os.getenv('GROWW_API_KEY')
    API_SECRET = os.getenv('GROWW_API_SECRET')
    
    if not API_KEY or not API_SECRET:
        logger.error("Missing GROWW_API_KEY or GROWW_API_SECRET in .env file.")
        return
        
    # STEP 1: Find Token
    logger.info(f"Step 1/4: Authenticating and fetching token for {symbol}...")
    try:
        token_auth = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
        groww = GrowwAPI(token_auth)
        
        res = groww.get_instrument_by_exchange_and_trading_symbol('NSE', symbol)
        if not res or 'exchange_token' not in res:
            logger.error(f"? Could not find token for {symbol}. Make sure the symbol is correct.")
            return
            
        exchange_token = res.get('exchange_token')
        logger.info(f"? Found match! Name: {res.get('name')} | Token: {exchange_token}")
        
    except Exception as e:
        logger.error(f"? Token fetch failed: {e}")
        return
        
    # STEP 2: Update Config
    logger.info(f"Step 2/4: Updating core/config.py...")
    if not update_config(symbol, exchange_token):
        return
        
    # STEP 3: Fetch Data
    logger.info(f"Step 3/4: Fetching historical data (python -m core.fetch_data)...")
    try:
        subprocess.run([sys.executable, "-m", "core.fetch_data"], cwd=BASE_DIR, check=True)
        logger.info("? Historical data fetched successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? Data fetching failed with error code {e.returncode}")
        return
        
    # STEP 4: Retrain Model
    logger.info(f"Step 4/4: Retraining AI Model (python backtesting/ml_trainer.py)...")
    try:
        subprocess.run([sys.executable, os.path.join("backtesting", "ml_trainer.py")], cwd=BASE_DIR, check=True)
        logger.info("? AI Model retrained successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? Model training failed with error code {e.returncode}")
        return
        
    logger.info("=" * 50)
    logger.info(f"?? SUCCESS: Pipeline complete! {symbol} is now fully integrated into the Vault.")
    logger.info("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="Fully automated pipeline to add a new stock.")
    parser.add_argument("symbol", help="The NSE trading symbol (e.g. RELIANCE, ZOMATO)")
    args = parser.parse_args()
    
    run_pipeline(args.symbol)

if __name__ == "__main__":
    main()
