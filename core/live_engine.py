import os
import sys
import time
import json
import asyncio
import datetime
import pandas as pd
import concurrent.futures
import warnings
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from growwapi import GrowwAPI
from dotenv import load_dotenv

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(BASE_DIR, "backtesting"))

from backtesting.state_machine_engine import StateMachineEngine
from backtesting.strategies import get_all_strategies
from backtesting.features import compute_features
from core.run_pipeline import generate_report
from core.fetch_data import get_groww_history

from core.system_logger import setup_logger
from core.config import STOCK_TOKENS, TOKEN_TO_STOCK
from core.config import STOCKS as stocks
from core.health_check import get_system_health
from core.market_utils import get_market_status

logger = setup_logger("live_engine")

load_dotenv()

class LiveExecutionEngine:
    def __init__(self):
        self.tokens = TOKEN_TO_STOCK
        self.stocks = list(self.tokens.values())
        
        API_KEY = os.getenv('GROWW_API_KEY')
        API_SECRET = os.getenv('GROWW_API_SECRET')
        token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
        self.groww = GrowwAPI(token)
        
        self.scheduler = AsyncIOScheduler()
        
        # Initialize and load AI Brain
        self.engine = StateMachineEngine(initial_capital=1000000.0)
        self.strategies = get_all_strategies()
        self.out_file = os.path.join(BASE_DIR, "data", "paper_trade_logs.csv")
        self.engine.load_state(self.out_file)

    def get_candle_start_time(self, dt):
        minute = (dt.minute // 15) * 15
        return dt.replace(minute=minute, second=0, microsecond=0)

    def _fetch_single_live_candle(self, stock, start_dt, end_dt):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import contextlib
                with contextlib.redirect_stdout(open(os.devnull, 'w')), contextlib.redirect_stderr(open(os.devnull, 'w')):
                    df = get_groww_history(self.groww, stock, GrowwAPI.CANDLE_INTERVAL_MIN_15, start_dt, end_dt)
            if not df.empty:
                start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
                match = df[df['Timestamp'] == pd.to_datetime(start_str)]
                if not match.empty:
                    c = match.iloc[0]
                    return stock, {
                        'open': float(c['Open']),
                        'high': float(c['High']),
                        'low': float(c['Low']),
                        'close': float(c['Close']),
                        'volume': float(c['Volume'])
                    }
        except Exception:
            pass
        return stock, None

    def fetch_live_candles(self, start_dt, end_dt):
        candles_dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            future_to_stock = {executor.submit(self._fetch_single_live_candle, stock, start_dt, end_dt): stock for stock in self.stocks}
            for future in concurrent.futures.as_completed(future_to_stock):
                stock, c = future.result()
                if c:
                    candles_dict[stock] = c
        return candles_dict

    async def evaluate_and_trade(self, candles_dict, candle_ts):
        now = datetime.datetime.now()
        logger.info(f"--- PRE-EMPTIVE AI EVALUATION ({candle_ts.strftime('%H:%M')}) ---")
        logger.info(f"Step 1: Successfully fetched live ticks for {len(candles_dict)} stocks.")
        logger.info("Step 2: Feeding data into AETHER Core...")
        
        for stock, c in candles_dict.items():
            csv_path = os.path.join(BASE_DIR, "data", stock, "15m_candles.csv")
            if not os.path.exists(csv_path): continue
            try:
                df = pd.read_csv(csv_path)
                df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                
                # Append live tick
                ts_str = candle_ts.strftime('%Y-%m-%d %H:%M:%S')
                new_row = {
                    'Timestamp': pd.to_datetime(ts_str), 'Open': c['open'],
                    'High': c['high'], 'Low': c['low'], 'Close': c['close'], 'Volume': c['volume']
                }
                new_df = pd.DataFrame([new_row])
                df = pd.concat([df, new_df], ignore_index=True)
                
                # Compute features on the merged live history
                df = compute_features(df)
                df['Stock'] = stock
                live_row = df.iloc[-1]
                
                # Pass into the ML engine with ACTUAL clock time, not candle start time
                actual_now_str = now.strftime('%Y-%m-%d %H:%M:%S')
                self.engine.process_candle(pd.to_datetime(actual_now_str), live_row, self.strategies)
                
            except Exception as e:
                logger.error(f"Error processing {stock} live tick: {e}")
                
        # Save state and update dashboard with true clock time
        logger.info("Step 3: Synching AETHER states to internal memory...")
        actual_now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        last_prices = {stock: c['close'] for stock, c in candles_dict.items()}
        self.engine.save_state(self.out_file, actual_now_str, last_prices)
        
        logger.info("Step 4: Compiling real-time Dashboard payload...")
        try:
            generate_report()
            logger.info("==================================================")
            logger.info("        PIPELINE SYNCHRONIZATION COMPLETE         ")
            logger.info("==================================================\n")
        except Exception as e:
            logger.error(f"Error generating dashboard JSON: {e}")

    def save_finalized_candles(self, candles_dict, candle_ts):
        ts_str = candle_ts.strftime('%Y-%m-%d %H:%M:%S')
        success_count = 0
        for stock, c in candles_dict.items():
            csv_path = os.path.join(BASE_DIR, "data", stock, "15m_candles.csv")
            if os.path.exists(csv_path):
                try:
                    df = pd.read_csv(csv_path)
                    df['Timestamp'] = pd.to_datetime(df['Timestamp'])
                    df = df[df['Timestamp'] != pd.to_datetime(ts_str)]
                    
                    new_row = {
                        'Timestamp': pd.to_datetime(ts_str),
                        'Open': c['open'],
                        'High': c['high'],
                        'Low': c['low'],
                        'Close': c['close'],
                        'Volume': c['volume']
                    }
                    new_df = pd.DataFrame([new_row])
                    df = pd.concat([df, new_df], ignore_index=True)
                    df = df.sort_values(by='Timestamp')
                    df['Timestamp'] = df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                    df.to_csv(csv_path, index=False)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Error saving finalized {stock} candle: {e}")
                    
        logger.info(f"Successfully finalized {success_count} candles for the {ts_str} block.")

    def _catchup_single_stock(self, stock, now, latest_possible_candle):
        csv_path = os.path.join(BASE_DIR, "data", stock, "15m_candles.csv")
        if not os.path.exists(csv_path): return
        
        try:
            df = pd.read_csv(csv_path)
            df['Timestamp'] = pd.to_datetime(df['Timestamp'])
            if df.empty: return
            
            fetch_start = now - datetime.timedelta(days=3)
            
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                import contextlib
                with contextlib.redirect_stdout(open(os.devnull, 'w')), contextlib.redirect_stderr(open(os.devnull, 'w')):
                    df_new = get_groww_history(self.groww, stock, GrowwAPI.CANDLE_INTERVAL_MIN_15, fetch_start, now)
            
            if not df_new.empty:
                df_new['Timestamp'] = pd.to_datetime(df_new['Timestamp'])
                df_new = df_new[df_new['Timestamp'] <= latest_possible_candle]
                
                if not df_new.empty:
                    initial_len = len(df)
                    combined_df = pd.concat([df, df_new], ignore_index=True)
                    combined_df.drop_duplicates(subset=['Timestamp'], keep='last', inplace=True)
                    combined_df.sort_values(by='Timestamp', inplace=True)
                    
                    final_len = len(combined_df)
                    added_count = final_len - initial_len
                    
                    is_modified = False
                    if added_count > 0:
                        is_modified = True
                    else:
                        if df.iloc[-1]['Volume'] != combined_df.iloc[-1]['Volume'] or df.iloc[-1]['Close'] != combined_df.iloc[-1]['Close']:
                            is_modified = True
                    
                    if is_modified:
                        combined_df['Timestamp'] = combined_df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
                        combined_df.to_csv(csv_path, index=False)
                        if added_count > 0:
                            logger.info(f"[{stock}] Synced data. Inserted {added_count} new historical candles.")
        except Exception:
            pass

    def catchup_missing_candles(self):
        if get_market_status() != "OPEN":
            logger.info("Market is offline. Bypassing Auto Catch-Up Sequence.")
            return
            
        logger.info("Running Auto Catch-Up Sequence for historical data gaps...")
        now = datetime.datetime.now()
        
        market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
        market_end = now.replace(hour=15, minute=31, second=0, microsecond=0)
        
        if now < market_start:
            logger.info("Auto Catch-Up Sequence Complete.\n")
            return
            
        latest_possible_candle = self.get_candle_start_time(now) - datetime.timedelta(minutes=15)
        market_last_candle = now.replace(hour=15, minute=15, second=0, microsecond=0)
        
        if latest_possible_candle > market_last_candle:
            latest_possible_candle = market_last_candle
            
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(self._catchup_single_stock, stock, now, latest_possible_candle) for stock in self.stocks]
            concurrent.futures.wait(futures)
            
        logger.info("Auto Catch-Up Sequence Complete.\n")

    async def trigger_preemptive(self):
        if get_market_status() != "OPEN": return
        now = datetime.datetime.now()
        health = get_system_health()
        if not health["overall_ok"]:
            logger.warning(f"[{now.strftime('%H:%M:%S')}] System Health Check Failed. Pausing Pre-emptive Evaluation.")
            return

        logger.info(f"[{now.strftime('%H:%M:%S')}] AETHER Clock synchronized. Launching pre-emptive cycle.")
        candle_ts = self.get_candle_start_time(now)
        end_dt = now.replace(hour=16, minute=0, second=0)
        candles = self.fetch_live_candles(candle_ts, end_dt)
        await self.evaluate_and_trade(candles, candle_ts)

    async def trigger_finalize(self):
        if get_market_status() != "OPEN": return
        now = datetime.datetime.now()
        health = get_system_health()
        if not health["overall_ok"]:
            return

        candle_ts = self.get_candle_start_time(now) - datetime.timedelta(minutes=15)
        logger.info(f"[{now.strftime('%H:%M:%S')}] Finalizing {candle_ts.strftime('%H:%M:%S')} block...")
        end_dt = now.replace(hour=16, minute=0, second=0)
        candles = self.fetch_live_candles(candle_ts, end_dt)
        self.save_finalized_candles(candles, candle_ts)

    def schedule_tasks(self):
        self.scheduler.add_job(self.trigger_preemptive, CronTrigger(minute='14,29,44,59', second='45'))
        self.scheduler.add_job(self.trigger_finalize, CronTrigger(minute='0,15,30,45', second='5'))
        self.scheduler.start()

    async def run(self):
        logger.info("Starting Execution Engine Pipeline (AETHER V2 Native API Mode)...")
        if get_market_status() == "OPEN":
            self.catchup_missing_candles()
        
        self.schedule_tasks()
        
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    engine = LiveExecutionEngine()
    asyncio.run(engine.run())
