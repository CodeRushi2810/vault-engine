import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pickle
from features import compute_features
from strategies import get_all_strategies
from enum import Enum

from core.system_logger import setup_logger
from core.config import STOCKS as stocks
import sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from core.discord_bot import send_discord_message


logger = setup_logger("sm_engine")



class StockState(Enum):
    DETECTING = 1
    PENDING = 2
    EXECUTED = 3
    CLOSED = 4

class Position:
    def __init__(self, stock, strategy, entry_time, entry_price, shares, cost, tsl_pct):
        self.stock = stock
        self.strategy = strategy
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.shares = shares
        self.cost = cost
        self.tsl_pct = tsl_pct
        self.highest_price = entry_price
        self.rsi_hit_70 = False

class StateMachineEngine:
    def __init__(self, initial_capital=1000000.0):
        self.balance = initial_capital
        self.open_positions = []
        self.completed_trades = []
        self.stock_states = {}
        self.latest_signals = {}
        
        BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.model_file = os.path.join(BASE_DIR, "backtesting", "bot_brain.pkl")
        self.ml_ready = False
        
        if os.path.exists(self.model_file):
            with open(self.model_file, 'rb') as f:
                data = pickle.load(f)
                self.ml_model = data['model']
                self.ml_features = data['features']
            self.ml_ready = True
        else:
            logger.info("WARNING: bot_brain.pkl not found. You must run ml_trainer.py first.")

    def load_state(self, out_file):
        start_date = pd.to_datetime("2026-05-01")
        is_resuming = False
        self.historical_closed_trades = []
        
        if os.path.exists(out_file):
            logger.info(f"Loading persistent ledger from {out_file}...")
            try:
                ledger_df = pd.read_csv(out_file)
                if not ledger_df.empty:
                    ledger_df['Entry_Time'] = pd.to_datetime(ledger_df['Entry_Time'])
                    ledger_df['Exit_Time'] = pd.to_datetime(ledger_df['Exit_Time'])
                    
                    last_timestamp_series = ledger_df['Exit_Time'].dropna()
                    if not last_timestamp_series.empty:
                        start_date = last_timestamp_series.max()
                        logger.info(f"Resuming simulation from {start_date}...")
                        is_resuming = True

                    closed_df = ledger_df[ledger_df['Status'] == 'CLOSED']
                    open_df = ledger_df[ledger_df['Status'] == 'OPEN']

                    closed_df['Entry_Time'] = closed_df['Entry_Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    closed_df['Exit_Time'] = closed_df['Exit_Time'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    self.historical_closed_trades = closed_df.to_dict(orient='records')
                    
                    realized_pnl = closed_df['PnL_Amount'].sum() if not closed_df.empty else 0
                    self.balance += realized_pnl
                    
                    for _, row in open_df.iterrows():
                        self.balance -= row['Cost_Basis']
                        pos = Position(
                            stock=row['Stock'],
                            strategy=row['Strategy'],
                            entry_time=row['Entry_Time'],
                            entry_price=row['Entry_Price'],
                            shares=row['Shares'],
                            cost=row['Cost_Basis'],
                            tsl_pct=0.05
                        )
                        if pd.notna(row['Exit_Price']) and row['Exit_Price'] > row['Entry_Price']:
                            pos.highest_price = row['Exit_Price']
                            
                        self.open_positions.append(pos)
                        self.set_stock_state(row['Stock'], StockState.EXECUTED)
            except Exception as e:
                logger.error(f"Failed to load ledger: {e}")
                
        return start_date, is_resuming

    def save_state(self, out_file, last_timestamp_str, last_prices):
        current_open_trades = []
        for pos in self.open_positions:
            price = last_prices.get(pos.stock, pos.entry_price)
            if pd.isna(price) or price <= 0:
                price = pos.entry_price
                
            revenue = pos.shares * price # friction removed
            pnl = revenue - pos.cost
            pnl_percent = (pnl / pos.cost) * 100 if pos.cost > 0 else 0
            
            entry_time_str = pos.entry_time if isinstance(pos.entry_time, str) else pos.entry_time.strftime('%Y-%m-%d %H:%M:%S')
            exit_time_str = last_timestamp_str
            
            current_open_trades.append({
                'Status': 'OPEN',
                'Entry_Time': entry_time_str,
                'Exit_Time': exit_time_str,
                'Stock': pos.stock,
                'Strategy': pos.strategy,
                'Entry_Price': pos.entry_price,
                'Exit_Price': price,
                'Shares': pos.shares,
                'Cost_Basis': pos.cost,
                'PnL_Amount': pnl,
                'PnL_Percent': pnl_percent,
                'Win_Loss': 1 if pnl > 0 else 0
            })
            
        # Format new closed trades
        for trade in self.completed_trades:
            if not isinstance(trade['Entry_Time'], str):
                trade['Entry_Time'] = trade['Entry_Time'].strftime('%Y-%m-%d %H:%M:%S')
            if not isinstance(trade['Exit_Time'], str):
                trade['Exit_Time'] = trade['Exit_Time'].strftime('%Y-%m-%d %H:%M:%S')
                
        all_trades = getattr(self, 'historical_closed_trades', []) + self.completed_trades + current_open_trades
        
        if not all_trades:
            logger.info("No valid trades were executed by the State Machine.")
            return
            
        df_trades = pd.DataFrame(all_trades)
        df_trades.to_csv(out_file, index=False)
        logger.info(f"State Machine Trades securely saved to {out_file}")

    def get_stock_state(self, stock):
        if stock not in self.stock_states:
            self.stock_states[stock] = StockState.DETECTING
        return self.stock_states[stock]

    def set_stock_state(self, stock, state):
        self.stock_states[stock] = state

    def process_candle(self, timestamp, row, strategies):
        if not self.ml_ready: return
        
        stock = row['Stock']
        price = row['Close']
        high = row['High']
        low = row['Low']
        
        if pd.isna(price) or price <= 0:
            price = row['Open']
        if pd.isna(price) or price <= 0:
            return
            
        current_state = self.get_stock_state(stock)
        
        # AGENT 3 (Risk Monitor) checks EXECUTED stocks to enforce TP and SL
        stock_positions = [p for p in self.open_positions if p.stock == stock]
        
        if stock_positions:
            total_shares = sum(p.shares for p in stock_positions)
            total_cost = sum(p.cost for p in stock_positions)
            avg_price = total_cost / total_shares if total_shares > 0 else 0
            
            rsi_val = row.get('RSI_14', 50)
            
            # Pure Diamond Hands Exit: ONLY sell when RSI hits 70 (Overbought) AND Net Average is 3% in profit!
            should_exit = (rsi_val >= 70 and price >= avg_price * 1.03)
            
            import json
            settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "system_config.json")
            can_sell = True
            if os.path.exists(settings_file):
                try:
                    with open(settings_file, "r") as f:
                        config = json.load(f)
                        global_sell = config.get("global", {}).get("allowSell", True)
                        engine_active = config.get("global", {}).get("engineActive", True)
                        
                        stock_config = config.get("stocks", {}).get(stock, {})
                        stock_sell = stock_config.get("allowSell", True)
                        
                        # Note: we bypass stock_active here so that users can liquidate disabled stocks
                        if not (engine_active and global_sell and stock_sell):
                            can_sell = False
                except:
                    pass
            
            should_exit = should_exit and can_sell

            for pos in stock_positions[:]:
                # Update watermark
                pos.highest_price = max(pos.highest_price, high)
                
                if should_exit:
                    exit_price = price
                    revenue = pos.shares * exit_price # friction removed
                    pnl = revenue - pos.cost
                    pnl_percent = (pnl / pos.cost) * 100

                    self.balance += revenue
                    self.open_positions.remove(pos)

                    self.completed_trades.append({
                        'Status': 'CLOSED',
                        'Entry_Time': pos.entry_time,
                        'Exit_Time': timestamp,
                        'Stock': stock,
                        'Strategy': pos.strategy,
                        'Entry_Price': pos.entry_price,
                        'Exit_Price': exit_price,
                        'Shares': pos.shares,
                        'Cost_Basis': pos.cost,
                        'PnL_Amount': pnl,
                        'PnL_Percent': pnl_percent,
                        'Win_Loss': 1 if pnl > 0 else 0
                    })
                    
                    pnl_str = f"+Rs {pnl:,.2f}" if pnl >= 0 else f"-Rs {abs(pnl):,.2f}"
                    pnl_pct_str = f"+{pnl_percent:.2f}%" if pnl_percent >= 0 else f"{pnl_percent:.2f}%"
                    icon = "🟢" if pnl >= 0 else "🔴"
                    
                    msg = f"{icon} Sold {pos.shares} {stock} at Rs {exit_price:,.2f} | Entry: Rs {pos.entry_price:,.2f} | PnL: {pnl_str} ({pnl_pct_str})"
                        
                    send_discord_message(msg)
                
        # If all positions are closed, state goes to DETECTING
        if not any(p.stock == stock for p in self.open_positions):
            self.set_stock_state(stock, StockState.DETECTING)
                    
        # AGENT 1 (Analyst) evaluating stocks (Pyramiding Allowed)
        # Rule: We only allow a new Pyramid entry if the price is at least 5% lower than our last entry.
        last_entry_price = min([p.entry_price for p in self.open_positions if p.stock == stock], default=float('inf'))
        can_trade = len([p for p in self.open_positions if p.stock == stock]) == 0 or price <= last_entry_price * 0.95
        
        import json
        settings_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "system_config.json")
        if os.path.exists(settings_file):
            try:
                with open(settings_file, "r") as f:
                    config = json.load(f)
                    global_buy = config.get("global", {}).get("allowBuy", True)
                    engine_active = config.get("global", {}).get("engineActive", True)
                    
                    stock_config = config.get("stocks", {}).get(stock, {})
                    stock_active = stock_config.get("active", True)
                    stock_buy = stock_config.get("allowBuy", True)
                    
                    if not (engine_active and global_buy and stock_active and stock_buy):
                        can_trade = False
            except:
                pass
        
        if can_trade:
            best_signal = None
            
            # Extract features dict for ML prediction
            features = {k: v for k, v in row.items() if k not in ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume', 'Stock']}
            
            for strategy in strategies:
                direction, tsl_pct = strategy.generate_signal(row)
                if direction == 1:
                    feature_dict = features.copy()
                    feature_dict['Strategy'] = strategy.name
                    
                    df_features = pd.DataFrame([feature_dict])
                    df_features = pd.get_dummies(df_features, columns=['Strategy'])
                    
                    # Align columns with training data
                    for col in self.ml_features:
                        if col not in df_features.columns:
                            df_features[col] = 0
                    df_features = df_features[self.ml_features]
                    
                    probs = self.ml_model.predict_proba(df_features)[0]
                    confidence = probs[1] 
                    
                    if best_signal is None or confidence > best_signal['confidence']:
                        best_signal = {
                            'strategy': strategy.name,
                            'tsl_pct': tsl_pct,
                            'confidence': confidence,
                            'features': df_features.iloc[0].to_dict()
                        }
            
            # AGENT 2 (Execution) evaluates the best setup
            if best_signal is not None:
                # Capture the best signal for the frontend payload
                self.latest_signals[stock] = best_signal
                
                # ML Prediction (Agent 2)
                features_df = pd.DataFrame([best_signal['features']])
                prob = self.ml_model.predict_proba(features_df)[0][1]
                
                if prob > 0.80:
                    allocation_pct = 0.10
                elif prob > 0.60:
                    allocation_pct = 0.075
                else:
                    allocation_pct = 0.05
                    
                total_portfolio_value = self.balance + sum(p.cost for p in self.open_positions)
                invest_amount = total_portfolio_value * allocation_pct
                
                invest_amount = max(invest_amount, 10000)
                
                # Cap at available balance to prevent negative cash
                invest_amount = min(invest_amount, self.balance)

                self.latest_signals[stock]['action'] = 'BUY'
                self.latest_signals[stock]['price'] = price
                self.latest_signals[stock]['time'] = timestamp.strftime('%H:%M:%S')

                if invest_amount >= price:
                    shares = int(invest_amount // price)
                    if shares > 0:
                        self.latest_signals[stock]['executed'] = True
                        self.latest_signals[stock]['quantity'] = shares
                        
                        cost = shares * price # friction removed
                        self.balance -= cost
                        self.open_positions.append(Position(stock, best_signal['strategy'], timestamp, price, shares, cost, best_signal['tsl_pct']))
                        self.set_stock_state(stock, StockState.EXECUTED)
                        
                        msg = f"🟢 Bought {shares} {stock} at Rs {price:,.2f}"
                        send_discord_message(msg)
                    else:
                        self.latest_signals[stock]['executed'] = False
                        self.latest_signals[stock]['reason'] = 'Zero Qty'
                else:
                    self.latest_signals[stock]['executed'] = False
                    self.latest_signals[stock]['reason'] = 'No Funds'


def run_state_machine():
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(BASE_DIR, "data")
    out_file = os.path.join(data_dir, "paper_trade_logs.csv")
    
    
    
    engine = StateMachineEngine(initial_capital=1000000.0)
    start_date, is_resuming = engine.load_state(out_file)
    
    all_data = []
    logger.info("Loading chronological data for State Machine Walk-Forward Simulation...")
    for stock in stocks:
        stock_dir = os.path.join(data_dir, stock)
        
        file_15m = os.path.join(stock_dir, "15m_candles.csv")
        if os.path.exists(file_15m):
            df_15m = pd.read_csv(file_15m)
            df_15m['Timestamp'] = pd.to_datetime(df_15m['Timestamp'])
            df_15m = compute_features(df_15m)
            df_15m['Stock'] = stock
            all_data.append(df_15m)
            
    if not all_data:
        logger.info("No data found.")
        return
        
    master_df = pd.concat(all_data).sort_values('Timestamp')
    
    # Filter dataset for State Machine execution
    if is_resuming:
        master_df = master_df[master_df['Timestamp'] > start_date]
    else:
        master_df = master_df[master_df['Timestamp'] >= start_date]
    
    if master_df.empty:
        logger.info("No new candles to process. System is up to date.")
        return
    
    logger.info(f"Starting 4-Agent State Machine Simulator from {start_date} (Available Cash: Rs {engine.balance:,.2f})...")
    
    strategies = get_all_strategies()
    for timestamp, group in master_df.groupby('Timestamp'):
        for _, row in group.iterrows():
            engine.process_candle(timestamp, row, strategies)
            
    last_timestamp = master_df['Timestamp'].max()
    last_timestamp_str = last_timestamp.strftime('%Y-%m-%d %H:%M:%S')
    last_prices = {}
    for stock in stocks:
        stock_data = master_df[master_df['Stock'] == stock]
        if not stock_data.empty:
            last_prices[stock] = stock_data.iloc[-1]['Close']
            
    logger.info(f"Simulation Complete! Available Cash: Rs {engine.balance:,.2f}")
    engine.save_state(out_file, last_timestamp_str, last_prices)

if __name__ == "__main__":
    run_state_machine()
