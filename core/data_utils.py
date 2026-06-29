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
        
    # FALLBACK SOURCE: Local CSV Data (for any stocks that failed)
    missing_stocks = [s for s in stocks if s not in close_prices]
    for stock in missing_stocks:
        csv_path = os.path.join(BASE_DIR, "data", stock, "1d_candles.csv")
        try:
            if os.path.exists(csv_path):
                df = pd.read_csv(csv_path)
                if not df.empty:
                    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                    df['Date'] = df['Timestamp'].dt.date
                    
                    if len(df) >= 2:
                        last_date = df.iloc[-1]['Date']
                        if last_date == now:
                            close_prices[stock] = {"prev_close": float(df.iloc[-2]['Close'])}
                        else:
                            close_prices[stock] = {"prev_close": float(df.iloc[-1]['Close'])}
                    elif len(df) == 1:
                        last_date = df.iloc[-1]['Date']
                        if last_date != now:
                            close_prices[stock] = {"prev_close": float(df.iloc[-1]['Close'])}
        except Exception as e:
            logger.warning(f"Error reading CSV fallback for {stock}: {e}")
            
    return close_prices
