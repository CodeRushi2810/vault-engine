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

# Load credentials
load_dotenv()
API_KEY = os.getenv("GROWW_API_KEY")
API_SECRET = os.getenv("GROWW_API_SECRET")

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
    if not API_KEY or not API_SECRET:
        logger.info("Please provide GROWW_API_KEY and GROWW_API_SECRET in the .env file.")
        return

    logger.info("Authenticating with Groww...")
    try:
        access_token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
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
        
        if os.path.exists(file_15m):
            df_existing_15m = pd.read_csv(file_15m)
            if not df_existing_15m.empty:
                last_ts = pd.to_datetime(df_existing_15m['Timestamp'].max())
                
                if is_market_open:
                    if end_time - last_ts < timedelta(minutes=15):
                        is_15m_up_to_date = True
                else:
                    if last_ts.date() >= last_trading_date and last_ts.hour >= 15:
                        is_15m_up_to_date = True
                        
                start_time_15m = last_ts - timedelta(days=5)
                if start_time_15m < end_time - timedelta(days=90):
                    start_time_15m = end_time - timedelta(days=90)
                logger.info(f"Found existing 15m data for {stock}. Last timestamp: {last_ts}.")
            else:
                logger.info(f"15m file exists but empty for {stock}.")
        else:
            logger.info(f"No existing 15m data for {stock}.")
            
        if is_15m_up_to_date:
            logger.info(f"15m data is already up to date for {stock}. Skipping fetch.")
        elif start_time_15m < end_time:
            logger.info(f"Fetching 15m candles from Groww for {stock} since {start_time_15m}...")
            df_15m = get_groww_history(groww, stock, groww.CANDLE_INTERVAL_MIN_15, start_time_15m, end_time)
            if not df_15m.empty:
                total_15m = update_csv_with_new_data(file_15m, df_15m, date_only=False)
                logger.info(f"Updated 15m candles for {stock} (Total rows: {total_15m}).")
            else:
                logger.info(f"No new 15m data fetched for {stock}.")
                
        # ----------------------------------------------------
        # 2. 1d Candles Update
        # ----------------------------------------------------
        file_1d = os.path.join(stock_dir, "1d_candles.csv")
        start_time_1d = end_time - timedelta(days=365) # Default max available length for 1d
        is_1d_up_to_date = False
        
        if os.path.exists(file_1d):
            df_existing_1d = pd.read_csv(file_1d)
            if not df_existing_1d.empty:
                last_ts_1d = pd.to_datetime(df_existing_1d['Timestamp'].max())
                
                # Check if it has today's candle if we are post-market, else it just needs yesterday's
                if not is_market_open and last_ts_1d.date() >= last_trading_date:
                    is_1d_up_to_date = True
                elif is_market_open and last_ts_1d.date() >= last_trading_date:
                    # In market open, today's candle is technically incomplete, but if it has yesterday's, it's mostly up to date.
                    # We always fetch if market is open to update the current 'today' candle.
                    pass
                        
                start_time_1d = last_ts_1d - timedelta(days=5)
                if start_time_1d < end_time - timedelta(days=365):
                    start_time_1d = end_time - timedelta(days=365)
                logger.info(f"Found existing 1d data for {stock}. Last timestamp: {last_ts_1d}.")
            else:
                logger.info(f"1d file exists but empty for {stock}.")
        else:
            logger.info(f"No existing 1d data for {stock}.")
            
        if is_1d_up_to_date:
            logger.info(f"1d data is already up to date for {stock}. Skipping fetch.")
        elif start_time_1d < end_time:
            logger.info(f"Fetching 1d candles from Groww for {stock} since {start_time_1d}...")
            df_1d = get_groww_history(groww, stock, groww.CANDLE_INTERVAL_DAY, start_time_1d, end_time)
            if not df_1d.empty:
                total_1d = update_csv_with_new_data(file_1d, df_1d, date_only=True)
                logger.info(f"Updated 1d candles for {stock} (Total rows: {total_1d}).")
            else:
                logger.info(f"No new 1d data fetched for {stock}.")
        


if __name__ == "__main__":
    main()
