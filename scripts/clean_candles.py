import os
import pandas as pd
import datetime
import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from core.config import STOCKS as stocks


BASE_DIR = 'C:/Vault/the-vault-trading'

expected_times = [datetime.time(h, m) for h in range(9, 16) for m in (0, 15, 30, 45) if not (h == 9 and m == 0) and not (h == 15 and m > 15)]

for stock in stocks:
    csv_path = os.path.join(BASE_DIR, 'data', stock, '15m_candles.csv')
    if not os.path.exists(csv_path): continue
    
    df = pd.read_csv(csv_path)
    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
    df = df.sort_values(by='Timestamp').reset_index(drop=True)
    
    # Filter out candles outside 9:15 - 15:15
    start_time = datetime.time(9, 15)
    end_time = datetime.time(15, 15)
    
    df['time'] = df['Timestamp'].dt.time
    df['date'] = df['Timestamp'].dt.date
    
    # 1. Drop outside bounds
    df = df[(df['time'] >= start_time) & (df['time'] <= end_time)]
    
    # 2. Fill missing candles
    dates = df['date'].unique()
    
    complete_rows = []
    
    for i, d in enumerate(dates):
        day_df = df[df['date'] == d].copy()
        day_times = day_df['time'].tolist()
        
        for et in expected_times:
            if et not in day_times:
                # Create missing candle
                ts = pd.to_datetime(f"{d} {et.strftime('%H:%M:%S')}")
                if ts > pd.Timestamp.now():
                    continue
                
                # Forward fill logic
                # Find the most recent candle before this timestamp
                prev_candles = [r for r in complete_rows if r['Timestamp'] < ts]
                if prev_candles:
                    prev_c = prev_candles[-1]
                    new_row = {
                        'Timestamp': ts,
                        'Open': prev_c['Close'],
                        'High': prev_c['Close'],
                        'Low': prev_c['Close'],
                        'Close': prev_c['Close'],
                        'Volume': 0,
                        'time': et,
                        'date': d
                    }
                else:
                    # If it's the very first candle of the dataset missing
                    # Find the next available candle and backfill
                    next_candles = day_df[day_df['time'] > et]
                    if not next_candles.empty:
                        next_c = next_candles.iloc[0]
                        new_row = {
                            'Timestamp': ts,
                            'Open': next_c['Open'],
                            'High': next_c['Open'],
                            'Low': next_c['Open'],
                            'Close': next_c['Open'],
                            'Volume': 0,
                            'time': et,
                            'date': d
                        }
                    else:
                        continue # Should not happen if day has data
                complete_rows.append(new_row)
            else:
                # Candle exists
                existing_row = day_df[day_df['time'] == et].iloc[0].to_dict()
                complete_rows.append(existing_row)

    # Reconstruct dataframe
    new_df = pd.DataFrame(complete_rows)
    new_df = new_df.sort_values('Timestamp').reset_index(drop=True)
    
    # Drop temp columns
    new_df = new_df.drop(columns=['time', 'date'])
    
    # Format Timestamp
    new_df['Timestamp'] = new_df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    
    new_df.to_csv(csv_path, index=False)
    print(f"Cleaned {stock}: exact 9:15 to 15:15 boundary enforced. Interpolated missing candles.")
