import os
import time as sys_time
import pandas as pd
from growwapi import GrowwAPI
from dotenv import load_dotenv
from datetime import datetime, timedelta, time
import warnings

from core.system_logger import setup_logger
from core.config import STOCKS
logger = setup_logger("fetch_data")



# Suppress pandas FutureWarnings
warnings.simplefilter(action='ignore', category=FutureWarning)

def get_market_status():
    now = datetime.now()
    
    # Check if weekday (0=Monday, 4=Friday)
    if now.weekday() > 4:
        last_trading_date = now.date() - timedelta(days=now.weekday() - 4)
        is_market_open = False
    else:
        last_trading_date = now.date()
        # Check if currently in market hours (9:15 to 15:30)
        is_market_open = (time(9, 15) <= now.time() < time(15, 30))
        
    return is_market_open, last_trading_date

# Target Stocks

# Target Stocks



def get_groww_history(groww, stock_name, interval_constant, start_time, end_time):
    # Determine chunk days based on Groww API backtesting limits
    if interval_constant in [groww.CANDLE_INTERVAL_DAY, groww.CANDLE_INTERVAL_WEEK, groww.CANDLE_INTERVAL_MONTH]:
        chunk_days = 180
    elif interval_constant in [groww.CANDLE_INTERVAL_MIN_10, groww.CANDLE_INTERVAL_MIN_15, groww.CANDLE_INTERVAL_MIN_30]:
        chunk_days = 90
    else:
        chunk_days = 30
        
    all_candles = []
    
    current_start = start_time
    while current_start < end_time:
        current_end = current_start + timedelta(days=chunk_days)
        if current_end > end_time:
            current_end = end_time
            
        start_str = current_start.strftime('%Y-%m-%d %H:%M:%S')
        end_str = current_end.strftime('%Y-%m-%d %H:%M:%S')
        
        max_retries = 3
        retry_delay = 2
        for attempt in range(max_retries):
            try:
                response = groww.get_historical_candles(
                    exchange=groww.EXCHANGE_NSE,
                    segment=groww.SEGMENT_CASH,
                    groww_symbol=f"NSE-{stock_name}",
                    start_time=start_str,
                    end_time=end_str,
                    candle_interval=interval_constant
                )
                
                candles = response.get("candles", [])
                if candles:
                    all_candles.extend(candles)
                
                # Small delay to prevent rate limit on next request
                sys_time.sleep(0.5)
                break
                    
            except Exception as e:
                error_str = str(e).lower()
                if "rate limit" in error_str or "429" in error_str:
                    if attempt < max_retries - 1:
                        logger.warning(f"Rate limit hit for {stock_name}. Retrying in {retry_delay}s...")
                        sys_time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                
                logger.error(f"Error fetching Groww data for {stock_name} from {start_str} to {end_str}: {e}")
                break
            
        current_start = current_end
        
    if not all_candles:
        return pd.DataFrame()
        
    df = pd.DataFrame(all_candles, columns=['Timestamp_str', 'Open', 'High', 'Low', 'Close', 'Volume', 'OI'])
    df['Timestamp'] = pd.to_datetime(df['Timestamp_str'])
    df.drop(columns=['Timestamp_str', 'OI'], inplace=True)
    df = df[['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']]
    
    # Drop any potential overlaps from chunking
    df.drop_duplicates(subset=['Timestamp'], inplace=True)
    df.sort_values('Timestamp', inplace=True)
    
    # No need to resample since we are directly fetching the required interval natively
    
    return df

def update_csv_with_new_data(file_path, new_df, date_only=False):
    if new_df.empty:
        return 0
        
    if os.path.exists(file_path):
        existing_df = pd.read_csv(file_path)
        existing_df['Timestamp'] = pd.to_datetime(existing_df['Timestamp'])
        
        combined_df = pd.concat([existing_df, new_df], ignore_index=True)
    else:
        combined_df = new_df
        
    if date_only:
        combined_df['Date_str'] = combined_df['Timestamp'].dt.strftime('%Y-%m-%d')
        combined_df.drop_duplicates(subset=['Date_str'], keep='last', inplace=True)
        combined_df.sort_values('Date_str', inplace=True)
        combined_df.drop(columns=['Date_str'], inplace=True)
    else:
        combined_df.drop_duplicates(subset=['Timestamp'], keep='last', inplace=True)
        combined_df.sort_values('Timestamp', inplace=True)
        
    combined_df.to_csv(file_path, index=False)
    return len(combined_df)

def main():
    logger.info("Authenticating with Groww...")
    try:
        from core.auth import get_groww_token
        access_token = get_groww_token()
        groww = GrowwAPI(access_token)
        logger.info("Successfully authenticated with Groww!")
    except Exception as e:
        logger.error(f"Failed to authenticate with Groww: {e}")
        return

    end_time = datetime.now()
    is_market_open, last_trading_date = get_market_status()

    logger.info("\nStarting historical 15m candle update for Live Trading...")
    
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(BASE_DIR, "data")
    os.makedirs(data_dir, exist_ok=True)
    
    for stock in STOCKS:
        stock_dir = os.path.join(data_dir, stock)
        os.makedirs(stock_dir, exist_ok=True)
        
        # ----------------------------------------------------
        # 1. 15m Candles Update
        # ----------------------------------------------------
        file_15m = os.path.join(stock_dir, "15m_candles.csv")
        start_time_15m = end_time - timedelta(days=90) # Default max available length for 15m
        is_15m_up_to_date = False
        
        original_rows = 0
        if os.path.exists(file_15m):
            df_existing_15m = pd.read_csv(file_15m)
            original_rows = len(df_existing_15m)
            if not df_existing_15m.empty:
                last_ts = pd.to_datetime(df_existing_15m['Timestamp'].max())
                
                if is_market_open:
                    if end_time - last_ts < timedelta(minutes=15):
                        is_15m_up_to_date = True
                else:
                    if last_ts.date() >= last_trading_date and last_ts.hour >= 15:
                        is_15m_up_to_date = True
                        
                start_time_15m = last_ts
                if start_time_15m < end_time - timedelta(days=90):
                    start_time_15m = end_time - timedelta(days=90)
            
        if is_15m_up_to_date:
            pass # Skip logging to keep it clean if already up to date
        elif start_time_15m < end_time:
            df_15m = get_groww_history(groww, stock, groww.CANDLE_INTERVAL_MIN_15, start_time_15m, end_time)
            if not df_15m.empty:
                total_15m = update_csv_with_new_data(file_15m, df_15m, date_only=False)
                inserted = total_15m - original_rows
                if inserted > 0:
                    logger.info(f"Synced {stock}. Inserted {inserted} new 15m candles.")
                

        


if __name__ == "__main__":
    main()
