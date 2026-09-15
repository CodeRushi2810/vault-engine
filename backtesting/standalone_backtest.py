import os
import sys
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# Set up paths so we can import from core and backtesting seamlessly
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(BASE_DIR)
sys.path.append(os.path.join(BASE_DIR, "backtesting"))

from core.config import STOCKS
from backtesting.state_machine_engine import StateMachineEngine
from backtesting.strategies import get_all_strategies
from backtesting.features import compute_features

# ---------------------------------------------------------
# MOCK DESTRUCTIVE METHODS TO ENSURE 100% DECOUPLING
# ---------------------------------------------------------
import backtesting.state_machine_engine

# 1. Stop discord messages
backtesting.state_machine_engine.send_discord_message = lambda msg: None

# 2. Stop saving state to paper_trade_logs.csv
StateMachineEngine.save_state = lambda self, out_file, last_timestamp_str, last_prices: None

# 3. We explicitly DO NOT call engine.load_state() below.
# This forces the ledger to start fresh at 10 lakh Rs!
# ---------------------------------------------------------

def run_standalone_backtest():
    data_dir = os.path.join(BASE_DIR, "data")
    
    print("\n" + "="*70)
    print("STANDALONE DECOUPLED BACKTEST")
    print("="*70)
    print("Initializing fresh engine with Rs 1,000,000...")
    
    engine = StateMachineEngine(initial_capital=1000000.0)
    if not engine.ml_ready:
        print("[X] ML Model not found! Cannot run backtest.")
        return
        
    all_data = []
    print(f"Loading and computing features for {len(STOCKS)} stocks...")
    for stock in STOCKS:
        stock_dir = os.path.join(data_dir, stock)
        file_15m = os.path.join(stock_dir, "15m_candles.csv")
        if os.path.exists(file_15m):
            df_15m = pd.read_csv(file_15m)
            df_15m['Timestamp'] = pd.to_datetime(df_15m['Timestamp'])
            df_15m = compute_features(df_15m)
            df_15m['Stock'] = stock
            all_data.append(df_15m)
            
    if not all_data:
        print("No historical data found.")
        return
        
    master_df = pd.concat(all_data).sort_values('Timestamp')
    
    strategies = get_all_strategies()
    
    print(f"Starting simulation across {len(master_df)} candles (this might take a moment)...")
    
    for timestamp, group in master_df.groupby('Timestamp'):
        for _, row in group.iterrows():
            engine.process_candle(timestamp, row, strategies)
            
    # Calculate final stats
    total_revenue = 0
    wins = 0
    losses = 0
    
    for t in engine.completed_trades:
        if t['Win_Loss'] == 1:
            wins += 1
        else:
            losses += 1
        total_revenue += t['PnL_Amount']
        
    win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
    
    last_prices = {}
    for stock in STOCKS:
        stock_data = master_df[master_df['Stock'] == stock]
        if not stock_data.empty:
            last_prices[stock] = stock_data.iloc[-1]['Close']
            
    unrealized_pnl = sum((last_prices.get(p.stock, p.entry_price) - (p.cost / p.shares)) * p.shares for p in engine.open_positions)
    open_positions_cost = sum(p.cost for p in engine.open_positions)
    net_worth = engine.balance + open_positions_cost + unrealized_pnl
    
    print("\n" + "="*70)
    print("BACKTEST RESULTS")
    print("="*70)
    print(f"Initial Capital   : Rs 1,000,000.00")
    print(f"Final Cash Balance: Rs {engine.balance:,.2f}")
    print(f"Open Positions    : {len(engine.open_positions)}")
    print(f"Unrealized PnL    : Rs {unrealized_pnl:,.2f}")
    print(f"Net Worth         : Rs {net_worth:,.2f}")
    print("-" * 70)
    print(f"Total Trades      : {wins + losses}")
    print(f"Wins / Losses     : {wins} / {losses}")
    print(f"Win Rate          : {win_rate:.2f}%")
    print(f"Realized PnL      : Rs {total_revenue:,.2f}")
    print("="*70 + "\n")

    # ------------------------------------------------------------------
    # GENERATE DECOUPLED REPORT JSON
    # ------------------------------------------------------------------
    import json
    
    report_data = {
        "open_positions": [],
        "closed_positions": []
    }
    
    for p in engine.open_positions:
        report_data["open_positions"].append({
            "stock": p.stock,
            "purchasedatetime": str(p.entry_time),
            "price": p.entry_price,
            "quantity": p.shares,
            "total_buy_value": p.cost
        })
        
    for t in engine.completed_trades:
        sell_value = t['Cost_Basis'] + t['PnL_Amount']
        report_data["closed_positions"].append({
            "stock": t['Stock'],
            "purchasedatetime": str(t['Entry_Time']),
            "selldatetime": str(t['Exit_Time']),
            "buy_price": t['Entry_Price'],
            "sell_price": t['Exit_Price'],
            "quantity": t['Shares'],
            "total_buy_value": t['Cost_Basis'],
            "total_sell_value": sell_value,
            "profit": t['PnL_Amount'],
            "profit_percent": t['PnL_Percent']
        })
        
    report_path = os.path.join(BASE_DIR, "standalone_backtest_report.json")
    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=4)
        
    print(f"[SUCCESS] Full trade report generated successfully at:")
    print(f"-> {report_path}\n")

if __name__ == "__main__":
    run_standalone_backtest()
