import os
import sys
import argparse
import pandas as pd
import pickle
import csv
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from backtesting.features import compute_features
from backtesting.strategies import get_all_strategies
from core.config import STOCKS

def debug_timeframe(start_time_str, end_time_str, stock_name=None):
    start_time = pd.to_datetime(start_time_str)
    end_time = pd.to_datetime(end_time_str)

    data_dir = os.path.join(BASE_DIR, "data")
    log_dir = os.path.join(BASE_DIR, "Logs")
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
        
    out_file_name = f"test_ml_{stock_name if stock_name else 'all'}.csv"
    out_file = os.path.join(log_dir, out_file_name)
    
    # Load ML Model
    model_file = os.path.join(BASE_DIR, "backtesting", "bot_brain.pkl")
    if not os.path.exists(model_file):
        print(f"Error: {model_file} not found.")
        return
        
    with open(model_file, 'rb') as f:
        data = pickle.load(f)
        ml_model = data['model']
        ml_features = data['features']
        
    strategies = get_all_strategies()
    
    all_rows = []
    
    target_stocks = STOCKS if not stock_name else [stock_name]
    
    for stock in target_stocks:
        file_15m = os.path.join(data_dir, stock, "15m_candles.csv")
        if not os.path.exists(file_15m):
            continue
            
        df = pd.read_csv(file_15m)
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        
        # Filter for timeframe
        df = df[(df['Timestamp'] >= start_time) & (df['Timestamp'] <= end_time)]
        if df.empty:
            continue
            
        # Re-load full df to compute features properly (need history for SMA, MACD, etc)
        full_df = pd.read_csv(file_15m)
        full_df['Timestamp'] = pd.to_datetime(full_df['Timestamp'])
        full_df = compute_features(full_df)
        
        # Now filter the computed df for the timeframe
        df_computed = full_df[(full_df['Timestamp'] >= start_time) & (full_df['Timestamp'] <= end_time)]
        
        for _, row in df_computed.iterrows():
            timestamp = row['Timestamp']
            price = row['Close']
            
            features_dict = {k: v for k, v in row.items() if k not in ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'Stock']}
            
            for strategy in strategies:
                direction, tsl_pct = strategy.generate_signal(row)
                triggered = (direction == 1)
                
                confidence = 'N/A'
                if triggered:
                    feature_dict_strat = features_dict.copy()
                    feature_dict_strat['Strategy'] = strategy.name
                    
                    df_features = pd.DataFrame([feature_dict_strat])
                    df_features = pd.get_dummies(df_features, columns=['Strategy'])
                    
                    # Align columns
                    for col in ml_features:
                        if col not in df_features.columns:
                            df_features[col] = 0
                    df_features = df_features[ml_features]
                    
                    probs = ml_model.predict_proba(df_features)[0]
                    confidence = probs[1]
                    
                # Add Reason
                reason_parts = []
                if not triggered:
                    if strategy.name == 'MACDCrossover':
                        if features_dict.get('MACD_Cross_Up', 0) != 1:
                            reason_parts.append("MACD didn't cross UP")
                        if features_dict.get('RSI_Oversold_Recently', 0) != 1:
                            reason_parts.append("RSI not recently oversold")
                            
                reason = " & ".join(reason_parts) if reason_parts else ""

                row_data = {
                    'Timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
                    'Stock': stock,
                    'Price': round(price, 2) if isinstance(price, float) else price,
                    'Strategy_Name': strategy.name,
                    'Strategy_Triggered': triggered,
                    'Reason': reason,
                    'ML_Confidence': round(confidence, 4) if isinstance(confidence, float) else confidence,
                }
                
                # Expand features
                for k, v in features_dict.items():
                    if k in ['MACD_Cross_Up', 'MACD_Cross_Down', 'RSI_Oversold_Recently', 'Two_Consecutive_Red', 'Volume_Spike']:
                        row_data[k] = bool(v)
                    elif k == 'SuperTrend_Dir':
                        row_data[k] = 'Uptrend' if v == 1 else 'Downtrend'
                    elif isinstance(v, float):
                        row_data[k] = round(v, 2)
                    else:
                        row_data[k] = v
                    
                all_rows.append(row_data)
                
    if not all_rows:
        print("No data found for the given timeframe.")
        return
        
    df_out = pd.DataFrame(all_rows)
    try:
        df_out.to_csv(out_file, index=False)
        print(f"Successfully evaluated {len(all_rows)} scenarios.")
        print(f"Results saved to {out_file}")
    except PermissionError:
        print(f"\n[ERROR] Permission Denied!")
        print(f"Could not save to {out_file}.")
        print("Please ensure the file is NOT open in Excel or another program, then try again.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Debug AI signals for a specific timeframe")
    parser.add_argument("--start", type=str, required=True, help="Start time (e.g., '2026-07-27 09:15:00')")
    parser.add_argument("--end", type=str, required=True, help="End time (e.g., '2026-07-27 15:30:00')")
    parser.add_argument("--stock", type=str, required=False, help="Optional specific stock symbol (e.g., NETWEB)")
    
    args = parser.parse_args()
    debug_timeframe(args.start, args.end, args.stock)
