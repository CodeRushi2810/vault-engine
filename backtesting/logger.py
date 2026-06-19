import pandas as pd
import os

from core.system_logger import setup_logger
logger = setup_logger("trade_logger")



class TradeLogger:
    def __init__(self, log_file):
        self.log_file = log_file
        self.logs = []
        
    def add_trade(self, entry_time, exit_time, stock, strategy, entry_price, exit_price, pnl_percent, setup_features):
        trade_data = {
            'Entry_Time': entry_time,
            'Exit_Time': exit_time,
            'Stock': stock,
            'Strategy': strategy,
            'Entry_Price': entry_price,
            'Exit_Price': exit_price,
            'PnL_Percent': pnl_percent,
            'Win_Loss': 1 if pnl_percent > 0 else 0
        }
        # Merge the setup features (which are already shifted to prevent lookahead bias)
        trade_data.update(setup_features)
        self.logs.append(trade_data)
        
    def save(self):
        if not self.logs:
            logger.info("No trades were recorded.")
            return
            
        df = pd.DataFrame(self.logs)
        
        # We overwrite the log to prevent duplicates if ran multiple times during testing.
        # Once in live prod, you might append.
        df.to_csv(self.log_file, index=False)
        self.logs = [] # Clear memory
        logger.info(f"Saved {len(df)} total trades to {self.log_file}")
