import os
import datetime
import pandas as pd
from growwapi import GrowwAPI
from dotenv import load_dotenv
import warnings
warnings.simplefilter(action='ignore', category=FutureWarning)

load_dotenv('C:/Vault/the-vault-trading/.env')
API_KEY = os.getenv('GROWW_API_KEY')
API_SECRET = os.getenv('GROWW_API_SECRET')
token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
groww = GrowwAPI(token)

import sys
BASE_DIR = 'C:/Vault/the-vault-trading'
sys.path.append(BASE_DIR)
from core.config import STOCKS
BASE_DIR = 'C:/Vault/the-vault-trading'

now = datetime.datetime.now()
start_time = now.replace(hour=9, minute=0, second=0).strftime('%Y-%m-%d %H:%M:%S')
end_time = now.strftime('%Y-%m-%d %H:%M:%S')

for stock in STOCKS:
    try:
        res = groww.get_historical_candles('NSE', 'CASH', f'NSE-{stock}', start_time, end_time, GrowwAPI.CANDLE_INTERVAL_MIN_15)
        if not res or 'candles' not in res:
            continue
            
        csv_path = os.path.join(BASE_DIR, 'data', stock, '15m_candles.csv')
        if not os.path.exists(csv_path): continue
        
        # Read existing CSV
        df = pd.read_csv(csv_path)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        
        # Remove today's candles
        today = now.date()
        df = df[df['Timestamp'].dt.date != today]
        
        # Add pure Groww candles for today
        new_rows = []
        for c in res['candles']:
            ts_str = c[0].replace('T', ' ')
            new_rows.append({
                'Timestamp': pd.to_datetime(ts_str),
                'Open': float(c[1] or c[4]),
                'High': float(c[2] or c[4]),
                'Low': float(c[3] or c[4]),
                'Close': float(c[4]),
                'Volume': float(c[5] or 0)
            })
            
        if new_rows:
            new_df = pd.DataFrame(new_rows)
            df = pd.concat([df, new_df], ignore_index=True)
            
        # Write back correctly formatted
        df['Timestamp'] = df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        df.to_csv(csv_path, index=False)
        print(f"Re-fetched and filled all today's candles for {stock} including gaps.")
    except Exception as e:
        print(f"Failed {stock}: {e}")
