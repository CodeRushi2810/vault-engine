import os
import datetime
import pandas as pd
import json
from dotenv import load_dotenv

from core.system_logger import setup_logger
from core.config import STOCKS as stocks
from growwapi import GrowwAPI
logger = setup_logger("data_utils")

def get_previous_close_prices():
    close_prices = {}
    now = datetime.datetime.now().date()
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    # PRIMARY SOURCE: Groww API (100% accurate adjusted closing prices)
    try:
        from core.auth import get_groww_token
        token = get_groww_token()
        import contextlib
        with contextlib.redirect_stdout(open(os.devnull, 'w')):
            groww = GrowwAPI(token)
        
        for stock in stocks:
            try:
                q = groww.get_quote(stock, "NSE", "CASH")
                if q and 'ohlc' in q and 'close' in q['ohlc']:
                    close_prices[stock] = {
                        "prev_close": float(q['ohlc']['close'])
                    }
            except Exception as e:
                logger.warning(f"Could not fetch live quote for {stock}: {e}")
    except Exception as e:
        logger.error(f"Error during API fetch for prev close: {e}")
        
    # CACHE SUCCESSFUL API HITS
    cache_path = os.path.join(BASE_DIR, "data", "prev_close.json")
    if len(close_prices) == len(stocks):
        try:
            with open(cache_path, "w") as f:
                json.dump(close_prices, f, indent=4)
            logger.info("Successfully updated prev_close.json cache from Groww API.")
        except Exception as e:
            logger.error(f"Failed to write prev_close.json cache: {e}")
            
    # FALLBACK SOURCE: Local JSON Cache (for any stocks that failed)
    missing_stocks = [s for s in stocks if s not in close_prices]
    if missing_stocks:
        logger.warning(f"API missed {len(missing_stocks)} stocks. Falling back to prev_close.json cache...")
        try:
            if os.path.exists(cache_path):
                with open(cache_path, "r") as f:
                    cached_data = json.load(f)
                for stock in missing_stocks:
                    if stock in cached_data:
                        close_prices[stock] = cached_data[stock]
                        logger.info(f"Loaded {stock} from prev_close.json cache.")
                    else:
                        logger.error(f"Stock {stock} not found in prev_close.json cache!")
            else:
                logger.error("Fallback failed: prev_close.json does not exist yet.")
        except Exception as e:
            logger.warning(f"Error reading JSON fallback: {e}")
            
    return close_prices

def push_dashboard_to_mongo():
    logger.info("Pushing dashboard data to MongoDB offline snapshot...")
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(BASE_DIR, "data", "dashboard_data.json")
    if not os.path.exists(json_path):
        logger.error("dashboard_data.json not found.")
        return
    
    try:
        from pymongo import MongoClient
        load_dotenv(os.path.join(BASE_DIR, ".env"))
        mongo_uri = os.getenv("MONGO_URI")
        if not mongo_uri:
            logger.error("MONGO_URI not set.")
            return
            
        with open(json_path, 'r') as f:
            data = json.load(f)
            
        # Ensure market_data exists so the frontend can calculate 1D PnL when offline
        if "market_data" not in data or not data["market_data"]:
            data["market_data"] = {}
            import pandas as pd
            from core.config import STOCKS
            for stock in STOCKS:
                csv_path = os.path.join(BASE_DIR, "data", stock, "15m_candles.csv")
                if os.path.exists(csv_path):
                    try:
                        df = pd.read_csv(csv_path)
                        if not df.empty:
                            # Use the most recent 15m close price as the offline LTP
                            data["market_data"][stock] = float(df.iloc[-1]['Close'])
                    except Exception:
                        pass
            
        client = MongoClient(mongo_uri)
        db = client['vault_db']
        collection = db['dashboard_snapshot']
        
        # Replace existing snapshot with the new one
        collection.delete_many({})
        collection.insert_one({"data": data})
        logger.info("Successfully pushed dashboard snapshot to MongoDB.")
    except Exception as e:
        logger.error(f"Failed to push dashboard snapshot to MongoDB: {e}")
