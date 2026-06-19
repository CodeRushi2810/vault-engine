import os
import datetime
import pandas as pd
from dotenv import load_dotenv

from core.system_logger import setup_logger
from core.config import STOCKS as stocks
from growwapi import GrowwAPI
logger = setup_logger("data_utils")

def get_previous_close_prices():
    close_prices = {}
    
    try:
        load_dotenv()
        API_KEY = os.getenv('GROWW_API_KEY')
        API_SECRET = os.getenv('GROWW_API_SECRET')
        
        if API_KEY and API_SECRET:
            token = os.environ.get('GROWW_TOKEN')
            if not token:
                token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
                
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
                    logger.warning(f"Could not fetch live quote for {stock}, falling back to CSV.")
                    pass
    except Exception as e:
        logger.error(f"Error fetching API quotes: {e}")
        
    # Fallback to CSV for any missing stocks
    now = datetime.datetime.now().date()
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        for stock in stocks:
            if stock in close_prices:
                continue
                
            csv_path = os.path.join(BASE_DIR, "data", stock, "1d_candles.csv")
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                df['Date'] = df['Timestamp'].dt.date
                daily_closes = df
                
                if len(daily_closes) >= 2:
                    date_n = daily_closes.iloc[-1]['Date']
                    if date_n == now:
                        close_prices[stock] = {
                            "prev_close": float(daily_closes.iloc[-2]['Close'])
                        }
                    else:
                        close_prices[stock] = {
                            "prev_close": float(daily_closes.iloc[-1]['Close'])
                        }
                elif not daily_closes.empty:
                    date_n = daily_closes.iloc[-1]['Date']
                    if date_n == now:
                        close_prices[stock] = {
                            "prev_close": float(daily_closes.iloc[-1]['Close'])
                        }
                    else:
                        close_prices[stock] = {
                            "prev_close": float(daily_closes.iloc[-1]['Close'])
                        }
    except Exception as e:
        logger.error(f"Error calculating prev closes: {e}")
        
    return close_prices
