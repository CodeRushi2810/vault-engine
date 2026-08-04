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

def update_system_config(symbol):
    config_path = os.path.join(BASE_DIR, "data", "system_config.json")
    if not os.path.exists(config_path):
        return True
        
    try:
        import json
        with open(config_path, "r") as f:
            config = json.load(f)
            
        if "stocks" not in config:
            config["stocks"] = {}
            
        config["stocks"][symbol] = {
            "active": True,
            "allowBuy": True,
            "allowSell": True
        }
        
        with open(config_path, "w") as f:
            json.dump(config, f, indent=4)
            
        logger.info(f"? Automatically armed {symbol} for trading in data/system_config.json")
        return True
    except Exception as e:
        logger.error(f"? Failed to update system_config.json: {e}")
        return False

def run_pipeline(symbol):
    symbol = symbol.upper()
    logger.info(f"?? Starting automation pipeline for {symbol}")
    
    # STEP 1: Find Token
    logger.info(f"Step 1/8: Authenticating and fetching token for {symbol}...")
    try:
        from core.auth import get_groww_token
        token_auth = get_groww_token()
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
    logger.info(f"Step 2/8: Updating core/config.py...")
    if not update_config(symbol, exchange_token):
        return
        
    # STEP 3: Update System Config
    logger.info(f"Step 3/8: Updating data/system_config.json...")
    if not update_system_config(symbol):
        return
        
    # STEP 4: Fetch Data
    logger.info(f"Step 4/8: Fetching historical data (python -m core.fetch_data)...")
    try:
        subprocess.run([sys.executable, "-m", "core.fetch_data"], cwd=BASE_DIR, check=True)
        logger.info("? Historical data fetched successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? Data fetching failed with error code {e.returncode}")
        return
        
    # STEP 5: Update 100D EMA
    logger.info(f"Step 5/8: Initializing 100D EMA Baseline for {symbol} (python scripts/update_100d_ema.py)...")
    try:
        subprocess.run([sys.executable, os.path.join("scripts", "update_100d_ema.py"), "--stock", symbol], cwd=BASE_DIR, check=True)
        logger.info("? 100D EMA Baseline updated successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? 100D EMA update failed with error code {e.returncode}")
        return
        
    # STEP 6: Retrain Model
    logger.info(f"Step 6/8: Retraining AI Model (python backtesting/ml_trainer.py)...")
    try:
        subprocess.run([sys.executable, os.path.join("backtesting", "ml_trainer.py")], cwd=BASE_DIR, check=True)
        logger.info("? AI Model retrained successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? Model training failed with error code {e.returncode}")
        return
        
    # STEP 7: Refresh Prev Close Cache
    logger.info(f"Step 7/8: Refreshing Previous Close Cache...")
    try:
        subprocess.run([sys.executable, "-c", "from core.data_utils import get_previous_close_prices; get_previous_close_prices(force_refresh=True)"], cwd=BASE_DIR, check=True)
        logger.info("? Previous Close Cache refreshed successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? Prev close refresh failed with error code {e.returncode}")
        return
        
    # STEP 8: Sync Dashboard & MongoDB
    logger.info(f"Step 8/8: Syncing Dashboard and pushing offline snapshot to MongoDB...")
    try:
        cmd = "from core.run_pipeline import generate_report; from core.data_utils import push_dashboard_to_mongo; generate_report(); push_dashboard_to_mongo()"
        subprocess.run([sys.executable, "-c", cmd], cwd=BASE_DIR, check=True)
        logger.info("? Dashboard sync complete.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? Dashboard sync failed with error code {e.returncode}")
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
