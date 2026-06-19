import os
import pandas as pd
from datetime import datetime, timedelta
from features import compute_features
from strategies import get_all_strategies
from logger import TradeLogger

from core.system_logger import setup_logger
from core.config import STOCKS as stocks
import sys
import os
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)


logger = setup_logger("bt_engine")



class VirtualTrade:
    def __init__(self, entry_time, entry_price, setup_features):
        self.entry_time = entry_time
        self.entry_price = entry_price
        self.setup_features = setup_features

class StrategyTracker:
    def __init__(self, strategy, logger, stock):
        self.strategy = strategy
        self.logger = logger
        self.stock = stock
        self.current_trade = None
        
    def process_candle(self, candle):
        signal, tsl_pct = self.strategy.generate_signal(candle)
        price = candle['Open'] # Execute at Open price to avoid lookahead (since indicators used data up to previous Close)
        
        if self.current_trade is None and signal == 1:
            # We only extract numerical feature columns to save in the log
            features = {k: v for k, v in candle.items() if k not in ['Timestamp', 'Open', 'High', 'Low', 'Close', 'Volume']}
            self.current_trade = VirtualTrade(candle['Timestamp'], price, features)
            self.highest_price = price
            self.tsl_pct = tsl_pct
            
        elif self.current_trade is not None:
            # Update watermark
            self.highest_price = max(self.highest_price, candle['High'])
            
            # Check TSL against current low or close
            if candle['Low'] < self.highest_price * (1 - self.tsl_pct):
                raw_exit = self.highest_price * (1 - self.tsl_pct)
                
                # No friction applied (charges dealt with later)
                entry_cost = self.current_trade.entry_price
                exit_revenue = raw_exit
                
                pnl_percent = ((exit_revenue - entry_cost) / entry_cost) * 100
                
                self.logger.add_trade(
                    entry_time=self.current_trade.entry_time,
                    exit_time=candle['Timestamp'],
                    stock=self.stock,
                    strategy=self.strategy.name,
                    entry_price=self.current_trade.entry_price,
                    exit_price=raw_exit,
                    pnl_percent=pnl_percent,
                    setup_features=self.current_trade.setup_features
                )
                self.current_trade = None

def run_simulation():
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_dir = os.path.join(BASE_DIR, "data")
    log_file = os.path.join(data_dir, "trade_logs.csv")
    
    
    logger = TradeLogger(log_file)
    
    for stock in stocks:
        logger.info(f"\n--- Simulating {stock} ---")
        stock_dir = os.path.join(data_dir, stock)
        
        # Process 15m history
        file_15m = os.path.join(stock_dir, "15m_candles.csv")
        if os.path.exists(file_15m):
            logger.info(f"Running 15m Phase...")
            df_15m = pd.read_csv(file_15m)
            df_15m['Timestamp'] = pd.to_datetime(df_15m['Timestamp'])
            
            # Compute features over the FULL 15m dataset
            df_15m = compute_features(df_15m)
            
            trackers = [StrategyTracker(s, logger, stock) for s in get_all_strategies()]
            
            for _, row in df_15m.iterrows():
                for tracker in trackers:
                    tracker.process_candle(row)
                    
            # Force close any open trades at the end of the simulation
            last_price = df_15m.iloc[-1]['Close'] if not df_15m.empty else 0
            last_time = df_15m.iloc[-1]['Timestamp'] if not df_15m.empty else None
            if last_time:
                for tracker in trackers:
                    if tracker.current_trade is not None:
                        entry_cost = tracker.current_trade.entry_price
                        exit_revenue = last_price
                        pnl = ((exit_revenue - entry_cost) / entry_cost) * 100
                        logger.add_trade(tracker.current_trade.entry_time, last_time, stock, tracker.strategy.name, tracker.current_trade.entry_price, last_price, pnl, tracker.current_trade.setup_features)
        else:
            logger.info(f"No 15m data found for {stock}. Skipping.")
    # Save all gathered trades
    logger.info("\n--- Simulation Summary ---")
    logger.save()

if __name__ == "__main__":
    run_simulation()
