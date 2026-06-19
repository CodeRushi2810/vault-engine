import os
import subprocess
import pandas as pd

from core.system_logger import setup_logger
logger = setup_logger("pipeline")



def run_script(script_path):
    script_name = os.path.basename(script_path)
    logger.info(f"\n{'='*50}\nRunning {script_name}...\n{'='*50}")
    # Run the script and stream the output directly to the terminal
    result = subprocess.run(["python", script_path], capture_output=False)
    if result.returncode != 0:
        logger.error(f"Error running {script_name}. Pipeline stopped.")
        exit(1)

def generate_report():
    logger.info(f"\n{'='*50}\nGenerating JSON Payload for Dashboard...\n{'='*50}")
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    log_file = os.path.join(BASE_DIR, "data", "paper_trade_logs.csv")
    
    if not os.path.exists(log_file):
        logger.info("No trade logs found to generate report.")
        return
        
    # Export JSON for the Next.js Dashboard
    json_path = os.path.join(BASE_DIR, "dashboard", "public", "dashboard_data.json")
    if os.path.exists(os.path.dirname(json_path)):
        import json
        
        raw_df = pd.read_csv(log_file)
        import numpy as np
        raw_df = raw_df.replace({np.nan: None})
        
        raw_df['Entry_Date_Obj'] = pd.to_datetime(raw_df['Entry_Time'])
        raw_df['Financial_Year'] = raw_df['Entry_Date_Obj'].apply(
            lambda x: f"FY{str(x.year - 1)[-2:]}-{str(x.year)[-2:]}" if x.month < 4 else f"FY{str(x.year)[-2:]}-{str(x.year + 1)[-2:]}"
        )
        raw_df['Entry_Time_Formatted'] = raw_df['Entry_Date_Obj'].dt.strftime('%d %B %Y, %H:%M')
        raw_df['Exit_Time_Formatted'] = pd.to_datetime(raw_df['Exit_Time']).dt.strftime('%d %B %Y, %H:%M')
        
        import sys
        sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from core.data_utils import get_previous_close_prices
        dashboard_data = {
            "trades": raw_df[['Status', 'Entry_Time', 'Exit_Time', 'Entry_Time_Formatted', 'Exit_Time_Formatted', 'Financial_Year', 'Stock', 'Strategy', 'Entry_Price', 'Exit_Price', 'Shares', 'Cost_Basis', 'PnL_Amount', 'PnL_Percent', 'Win_Loss']].to_dict(orient='records'),
            "prevClosePrices": get_previous_close_prices()
        }
        with open(json_path, 'w') as f:
            json.dump(dashboard_data, f)
        logger.info(f"Dashboard data exported to {json_path}")
        
        try:
            import requests
            requests.post("http://127.0.0.1:8000/api/trigger-update", timeout=1)
            logger.info("Sent UPDATE_DASHBOARD signal to live feed server.")
        except Exception as e:
            logger.warning(f"Failed to trigger dashboard update: {e}")
            
    logger.info(f"Update successfully completed!")

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_script(os.path.join(BASE_DIR, "core", "fetch_data.py"))
    run_script(os.path.join(BASE_DIR, "backtesting", "engine.py"))
    run_script(os.path.join(BASE_DIR, "backtesting", "ml_trainer.py"))
    run_script(os.path.join(BASE_DIR, "backtesting", "state_machine_engine.py"))
    generate_report()
