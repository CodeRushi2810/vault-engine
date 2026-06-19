import os
import datetime
import pandas as pd
from growwapi import GrowwAPI
from dotenv import load_dotenv
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.config import STOCKS as stocks

load_dotenv('C:/Vault/the-vault-trading/.env')
API_KEY = os.getenv('GROWW_API_KEY')
API_SECRET = os.getenv('GROWW_API_SECRET')
token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
groww = GrowwAPI(token)


BASE_DIR = 'C:/Vault/the-vault-trading'

start_time = '2026-06-15 14:00:00'
end_time = '2026-06-16 09:45:00'  # fetching up to 9:30 candle requires end time slightly later

for stock in stocks:
    try:
        res = groww.get_historical_candles('NSE', 'CASH', f'NSE-{stock}', start_time, end_time, GrowwAPI.CANDLE_INTERVAL_MIN_15)
        if not res or 'candles' not in res:
            print(f"No candles found for {stock}")
            continue
            
        csv_path = os.path.join(BASE_DIR, 'data', stock, '15m_candles.csv')
        if not os.path.exists(csv_path):
            print(f"No existing CSV for {stock}")
            continue
        
        df = pd.read_csv(csv_path)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        
        # Remove old candles in this timeframe
        mask = (df['Timestamp'] >= pd.to_datetime('2026-06-15 14:00:00')) & (df['Timestamp'] <= pd.to_datetime('2026-06-16 09:30:00'))
        df = df[~mask]
        
        new_rows = []
        for c in res['candles']:
            ts_str = c[0].replace('T', ' ')
            ts_dt = pd.to_datetime(ts_str)
            if pd.to_datetime('2026-06-15 14:00:00') <= ts_dt <= pd.to_datetime('2026-06-16 09:30:00'):
                if None in c[1:6]: continue
                new_rows.append({
                    'Timestamp': ts_dt,
                    'Open': float(c[1]),
                    'High': float(c[2]),
                    'Low': float(c[3]),
                    'Close': float(c[4]),
                    'Volume': float(c[5])
                })
                
        if new_rows:
            new_df = pd.DataFrame(new_rows)
            df = pd.concat([df, new_df], ignore_index=True)
            df = df.sort_values(by='Timestamp')
            df['Timestamp'] = df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
            df.to_csv(csv_path, index=False)
            print(f"Refreshed {len(new_rows)} candles for {stock}.")
        else:
            print(f"No new candles within the time range found for {stock}.")
            
    except Exception as e:
        print(f"Failed {stock}: {e}")
