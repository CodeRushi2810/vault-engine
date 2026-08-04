import os
import sys
import json
import time as sys_time
from datetime import datetime, timedelta
import pandas as pd
import pandas_ta as ta

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.auth import get_groww_token
from growwapi import GrowwAPI
from core.config import STOCKS
from core.system_logger import setup_logger

logger = setup_logger("update_100d_ema")

def calculate_and_update_ema():
    logger.info("Starting 100D EMA generation process...")
    
    try:
        access_token = get_groww_token()
        groww = GrowwAPI(access_token)
    except Exception as e:
        logger.error(f"Failed to authenticate with Groww: {e}")
        return

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--stock", help="Specific stock to update", type=str)
    args = parser.parse_args()
    
    target_stocks = [args.stock] if args.stock else STOCKS

    # We only need the last few days to guarantee we catch the latest 1D candle
    end_time = datetime.now()
    start_time = end_time - timedelta(days=5)
    
    out_file = os.path.join(BASE_DIR, "data", "100d_ema.json")
    
    # Load existing data as a fallback and as the base for EMA calculation
    ema_data = {"stocks": {}}
    if os.path.exists(out_file):
        try:
            with open(out_file, "r") as f:
                loaded = json.load(f)
                if "stocks" in loaded:
                    ema_data = loaded
        except:
            pass
    
    k = 2 / (100 + 1)
    
    for stock in target_stocks:
        logger.info(f"Fetching 1D history for {stock}...")
        
        # If the stock is entirely new and not in the JSON, we MUST fetch 250 days to initialize it.
        # Otherwise, we just fetch the last 5 days to get the single latest candle.
        stock_start = start_time
        if stock not in ema_data["stocks"]:
            logger.info(f"{stock} is missing from cache! Running full 250-day initialization fetch...")
            stock_start = end_time - timedelta(days=250)
            
        all_candles = []
        current_start = stock_start
        fetch_failed = False
        while current_start < end_time:
            current_end = current_start + timedelta(days=180)
            if current_end > end_time:
                current_end = end_time
                
            start_str = current_start.strftime('%Y-%m-%d %H:%M:%S')
            end_str = current_end.strftime('%Y-%m-%d %H:%M:%S')
            
            success = False
            for attempt in range(3):
                try:
                    response = groww.get_historical_candles(
                        exchange=groww.EXCHANGE_NSE,
                        segment=groww.SEGMENT_CASH,
                        groww_symbol=f"NSE-{stock}",
                        start_time=start_str,
                        end_time=end_str,
                        candle_interval=groww.CANDLE_INTERVAL_DAY
                    )
                    
                    candles = response.get("candles", [])
                    if candles:
                        all_candles.extend(candles)
                        
                    sys_time.sleep(0.5)
                    success = True
                    break
                except Exception as e:
                    logger.error(f"Error fetching for {stock} (Attempt {attempt+1}/3): {e}")
                    sys_time.sleep(3)
                    
            if not success:
                fetch_failed = True
                break
                
            current_start = current_end
            
        if fetch_failed or not all_candles:
            logger.warning(f"Failed to fetch new data for {stock}. Falling back to yesterday's EMA.")
            continue
            
        df = pd.DataFrame(all_candles, columns=['Timestamp_str', 'Open', 'High', 'Low', 'Close', 'Volume', 'OI'])
        df['Timestamp'] = pd.to_datetime(df['Timestamp_str'])
        df = df[['Timestamp', 'Close']]
        df.drop_duplicates(subset=['Timestamp'], inplace=True)
        df.sort_values('Timestamp', inplace=True)
        
        # We need the most recent valid candle
        latest_candle = df.iloc[-1]
        current_price = latest_candle['Close']
        new_timestamp_str = latest_candle['Timestamp'].strftime('%Y-%m-%d')
        
        # Mathematical EMA Calculation
        if stock in ema_data["stocks"] and len(df) < 100:
            # Efficient O(1) Daily Update using yesterday's cache
            ema_yesterday = ema_data["stocks"][stock]["ema_100"]
            ema_value = (current_price - ema_yesterday) * k + ema_yesterday
        else:
            # Full recalculation (for new stocks or initial runs)
            if len(df) < 100:
                logger.warning(f"{stock} has less than 100 daily candles ({len(df)}). EMA will be inaccurate.")
            df['EMA_100'] = ta.ema(df['Close'], length=100)
            ema_value = df.dropna(subset=['EMA_100']).iloc[-1]['EMA_100']
            
        distance_pct = ((current_price - ema_value) / ema_value) * 100
        
        ema_data["stocks"][stock] = {
            "ema_100": round(ema_value, 2),
            "last_close": current_price,
            "distance_pct": round(distance_pct, 2)
        }
        # Update the global timestamp to the latest successful fetch date
        ema_data["timestamp"] = new_timestamp_str
        
    with open(out_file, "w") as f:
        json.dump(ema_data, f, indent=4)
        
    logger.info(f"Successfully generated 100D EMA JSON file at {out_file}")

if __name__ == "__main__":
    calculate_and_update_ema()
