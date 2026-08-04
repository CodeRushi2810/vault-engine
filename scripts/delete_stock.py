import os
import sys
import argparse
import subprocess
import re
import json
import shutil

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.system_logger import setup_logger
logger = setup_logger("delete_stock")

def check_open_positions(symbol):
    log_file = os.path.join(BASE_DIR, "data", "paper_trade_logs.csv")
    if not os.path.exists(log_file):
        return False
    try:
        import csv
        with open(log_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("Stock") == symbol and row.get("Status") == "OPEN":
                    return True
    except Exception as e:
        logger.error(f"Error checking open positions: {e}")
    return False

def remove_from_config(symbol):
    config_path = os.path.join(BASE_DIR, "core", "config.py")
    with open(config_path, "r") as f:
        content = f.read()
        
    # Remove the specific line mapping the stock token
    # e.g. "VOLTAS": "3718",
    pattern = rf'^\s*["\']{symbol}["\']\s*:\s*["\']\d+["\']\s*,?\s*\n?'
    new_content = re.sub(pattern, '', content, flags=re.MULTILINE)
    
    if new_content == content:
        logger.warning(f"Stock {symbol} not found in core/config.py")
        return True # Continue anyway
        
    with open(config_path, "w") as f:
        f.write(new_content)
        
    logger.info(f"? Removed {symbol} from core/config.py")
    return True

def remove_from_system_config(symbol):
    config_path = os.path.join(BASE_DIR, "data", "system_config.json")
    if os.path.exists(config_path):
        try:
            with open(config_path, "r") as f:
                config = json.load(f)
                
            if "stocks" in config and symbol in config["stocks"]:
                del config["stocks"][symbol]
                with open(config_path, "w") as f:
                    json.dump(config, f, indent=4)
                logger.info(f"? Removed {symbol} from data/system_config.json")
        except Exception as e:
            logger.error(f"Error updating system_config.json: {e}")
    return True

def remove_from_json_cache(filename, symbol, is_nested=False):
    path = os.path.join(BASE_DIR, "data", filename)
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                data = json.load(f)
                
            modified = False
            if is_nested and "stocks" in data and symbol in data["stocks"]:
                del data["stocks"][symbol]
                modified = True
            elif not is_nested and symbol in data:
                del data[symbol]
                modified = True
                
            if modified:
                with open(path, "w") as f:
                    json.dump(data, f, indent=4)
                logger.info(f"? Removed {symbol} from {filename}")
        except Exception as e:
            logger.error(f"Error updating {filename}: {e}")

def remove_from_dashboard_json(symbol):
    dashboard_path = os.path.join(BASE_DIR, "data", "dashboard_data.json")
    if os.path.exists(dashboard_path):
        try:
            with open(dashboard_path, "r") as f:
                data = json.load(f)
                
            modified = False
            if "market_data" in data and symbol in data["market_data"]:
                del data["market_data"][symbol]
                modified = True
            if "prevClosePrices" in data and symbol in data["prevClosePrices"]:
                del data["prevClosePrices"][symbol]
                modified = True
                
            if modified:
                with open(dashboard_path, "w") as f:
                    json.dump(data, f, indent=4)
                logger.info(f"? Removed {symbol} from dashboard_data.json (market_data & prevClosePrices)")
        except Exception as e:
            logger.error(f"Error updating dashboard_data.json: {e}")

def run_pipeline(symbol):
    symbol = symbol.upper()
    logger.info(f"?? Starting automation pipeline to DELETE {symbol}")
    
    # STEP 1: Check Open Positions
    logger.info(f"Step 1/7: Checking for open positions...")
    if check_open_positions(symbol):
        logger.error(f"? CRITICAL: Cannot delete {symbol} because it currently has open trades running!")
        logger.error("Please sell/close all open positions for this stock before deleting it.")
        return
        
    # STEP 2: Remove from Configs
    logger.info(f"Step 2/7: Removing from core configurations...")
    remove_from_config(symbol)
    remove_from_system_config(symbol)
    
    # STEP 3: Delete Historical Data
    logger.info(f"Step 3/7: Deleting historical 15m data directory...")
    data_dir = os.path.join(BASE_DIR, "data", symbol)
    if os.path.exists(data_dir):
        shutil.rmtree(data_dir)
        logger.info(f"? Deleted data/{symbol}/")
        
    # STEP 4: Remove from Caches
    logger.info(f"Step 4/7: Purging from EMA and PrevClose caches...")
    remove_from_json_cache("100d_ema.json", symbol, is_nested=True)
    remove_from_json_cache("prev_close.json", symbol, is_nested=False)
    
    # STEP 5: Retrain AI Model
    logger.info(f"Step 5/7: Retraining AI Model without {symbol} (python backtesting/ml_trainer.py)...")
    try:
        subprocess.run([sys.executable, os.path.join("backtesting", "ml_trainer.py")], cwd=BASE_DIR, check=True)
        logger.info("? AI Model retrained successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? Model training failed with error code {e.returncode}")
        
    # STEP 6: Remove from Dashboard JSON
    logger.info(f"Step 6/7: Removing from dashboard_data.json...")
    remove_from_dashboard_json(symbol)
    
    # STEP 7: Push to MongoDB
    logger.info(f"Step 7/7: Pushing updated snapshot to MongoDB...")
    try:
        cmd = "from core.data_utils import push_dashboard_to_mongo; push_dashboard_to_mongo()"
        subprocess.run([sys.executable, "-c", cmd], cwd=BASE_DIR, check=True)
        logger.info("? MongoDB sync complete.")
    except subprocess.CalledProcessError as e:
        logger.error(f"? MongoDB sync failed with error code {e.returncode}")
        
    logger.info("=" * 50)
    logger.info(f"? SUCCESS: Pipeline complete! {symbol} has been completely wiped from the Vault.")
    logger.info("NOTE: Any historical trades for this stock are securely preserved in the ledger.")
    logger.info("=" * 50)

def main():
    parser = argparse.ArgumentParser(description="Fully automated pipeline to DELETE a stock.")
    parser.add_argument("symbol", help="The NSE trading symbol to remove (e.g. RELIANCE, ZOMATO)")
    args = parser.parse_args()
    
    run_pipeline(args.symbol)

if __name__ == "__main__":
    main()
