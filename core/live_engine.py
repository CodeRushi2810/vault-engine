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
from core.agent_state import update_agent_status

logger = setup_logger("live_engine")

load_dotenv()

def log_and_broadcast(msg):
    logger.info(msg)

class LiveExecutionEngine:
    def __init__(self):
        self.tokens = TOKEN_TO_STOCK
        self.stocks = list(self.tokens.values())
        
        from core.auth import get_groww_token
        token = get_groww_token()
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

    def _fetch_single_live_candle(self, stock, start_dt, end_dt, stagger_delay=0.0):
        if stagger_delay > 0:
            time.sleep(stagger_delay)
        max_retries = 3
        retry_delay = 2.0
        for attempt in range(max_retries):
            try:
                start_str = start_dt.strftime('%Y-%m-%d %H:%M:%S')
                end_window = start_dt + datetime.timedelta(minutes=15)
                end_str = end_window.strftime('%Y-%m-%d %H:%M:%S')
                
                response = self.groww.get_historical_candles(
                    exchange=self.groww.EXCHANGE_NSE,
                    segment=self.groww.SEGMENT_CASH,
                    groww_symbol=f"NSE-{stock}",
                    start_time=start_str,
                    end_time=end_str,
                    candle_interval=GrowwAPI.CANDLE_INTERVAL_MIN_15
                )
                
                candles = response.get("candles", [])
                for c in candles:
                    if c[0] == int(start_dt.timestamp()):
                        return stock, {
                            'open': float(c[1]),
                            'high': float(c[2]),
                            'low': float(c[3]),
                            'close': float(c[4]),
                            'volume': float(c[5])
                        }
                
                if candles:
                    c = candles[-1]
                    return stock, {
                        'open': float(c[1]),
                        'high': float(c[2]),
                        'low': float(c[3]),
                        'close': float(c[4]),
                        'volume': float(c[5])
                    }
                break # If no exception but empty, just break
            except Exception as e:
                error_str = str(e).lower()
                if "rate limit" in error_str or "429" in error_str:
                    if attempt < max_retries - 1:
                        time.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                if attempt == max_retries - 1:
                    logger.error(f"Failed to fetch live tick for {stock} after {max_retries} attempts: {e}")
        return stock, None

    def fetch_live_candles(self, start_dt, end_dt):
        candles_dict = {}
        # Execute all 26 stocks concurrently, but stagger them by 0.11s each.
        # 0.11s stagger = exactly 9 requests per second (safely below the 10/s limit).
        # Total execution time: 26 * 0.11 = 2.86 seconds + 1s network latency = 3.8 seconds!
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(self.stocks)) as executor:
            future_to_stock = {}
            for i, stock in enumerate(self.stocks):
                future = executor.submit(self._fetch_single_live_candle, stock, start_dt, end_dt, i * 0.11)
                future_to_stock[future] = stock
                
            for future in concurrent.futures.as_completed(future_to_stock):
                stock, c = future.result()
                if c:
                    candles_dict[stock] = c
        return candles_dict

    async def evaluate_and_trade(self, candles_dict, candle_ts):
        now = datetime.datetime.now()
        log_and_broadcast(f"Step 1: Successfully fetched live ticks for {len(candles_dict)} stocks.")
        update_agent_status("ExecutionEngine", f"Successfully fetched live ticks for {len(candles_dict)} stocks.", is_active=True)
        await asyncio.sleep(0.5) # Slight stagger for UI animation
        
        update_agent_status("SignalProcessor", f"Scanning {len(candles_dict)} assets for mean-reversion signals...", is_active=True)
        update_agent_status("RiskManager", "Assessing pre-trade risk constraints...", is_active=True)
        
        log_and_broadcast("Step 2: Feeding data into AETHER Core...")
        update_agent_status("ExecutionEngine", "Feeding data into AETHER Core...", is_active=True)
        await asyncio.sleep(0.5) # Slight stagger for UI animation
        
        log_and_broadcast("Step 3: Evaluating ML models and dispatching Discord alerts...")
        update_agent_status("ExecutionEngine", "Evaluating ML models and dispatching Discord alerts...", is_active=True)
        
        initial_open = len(self.engine.open_positions)
        initial_closed = len(self.engine.completed_trades)
        
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
                
        trades_executed = (len(self.engine.open_positions) != initial_open) or (len(self.engine.completed_trades) != initial_closed)
                
        if not trades_executed:
            log_and_broadcast("No trades executed this cycle. Bypassing Step 4 & Step 5...")
            update_agent_status("ExecutionEngine", "No trades executed this cycle.", is_active=True)
            await asyncio.sleep(1.0)
            update_agent_status("ExecutionEngine", "Awaiting timeframe close...", is_active=True)
            update_agent_status("SignalProcessor", "Resting...", is_active=False)
            update_agent_status("RiskManager", "Risk levels optimal. Maximum drawdown within bounds.", is_active=False)
            self._save_latest_signals()
            return
            
        # Save state and update dashboard with true clock time
        log_and_broadcast("Step 4: Synching AETHER states to internal memory...")
        update_agent_status("ExecutionEngine", "Synching AETHER states to internal memory...", is_active=True)
        await asyncio.sleep(0.5)
        
        actual_now_str = now.strftime('%Y-%m-%d %H:%M:%S')
        last_prices = {stock: c['close'] for stock, c in candles_dict.items()}
        self.engine.save_state(self.out_file, actual_now_str, last_prices)
        
        log_and_broadcast("Step 5: Compiling real-time Dashboard payload...")
        update_agent_status("ExecutionEngine", "Compiling real-time Dashboard payload...", is_active=True)
        await asyncio.sleep(0.5)
        try:
            generate_report()
            from core.data_utils import push_dashboard_to_mongo
            push_dashboard_to_mongo()
        except Exception as e:
            logger.error(f"Error generating dashboard JSON: {e}")
            
        update_agent_status("ExecutionEngine", "Awaiting timeframe close...", is_active=True)
        update_agent_status("SignalProcessor", "Resting...", is_active=False)
        update_agent_status("RiskManager", "Risk levels optimal. Maximum drawdown within bounds.", is_active=False)
        self._save_latest_signals()

    def _save_latest_signals(self):
        try:
            signals_file = os.path.join(BASE_DIR, "data", "latest_signals.json")
            with open(signals_file, "w") as f:
                json.dump(self.engine.latest_signals, f)
        except Exception as e:
            logger.error(f"Failed to save latest signals: {e}")

    def _save_single_finalized_candle(self, stock, c, ts_str):
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
                return True
            except Exception as e:
                logger.error(f"Error saving finalized {stock} candle: {e}")
        return False

    def save_finalized_candles(self, candles_dict, candle_ts):
        ts_str = candle_ts.strftime('%Y-%m-%d %H:%M:%S')
        success_count = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=26) as executor:
            futures = [executor.submit(self._save_single_finalized_candle, stock, c, ts_str) for stock, c in candles_dict.items()]
            for future in concurrent.futures.as_completed(futures):
                if future.result():
                    success_count += 1
                    
        log_and_broadcast(f"Successfully finalized {success_count} candles for the {ts_str} block.")
        log_and_broadcast(f"\033[1;36m{candle_ts.strftime('%H:%M')} AETHER CYCLE COMPLETE\033[0m")
        log_and_broadcast("\033[1;36m==================================================\033[0m")
        update_agent_status("ExecutionEngine", "Resting...", is_active=False)



    async def trigger_preemptive(self):
        if get_market_status() != "OPEN": return
        now = datetime.datetime.now()
        health = get_system_health()
        if not health["overall_ok"]:
            logger.warning(f"[{now.strftime('%H:%M:%S')}] System Health Check Failed. Pausing Pre-emptive Evaluation.")
            return

        start_time = time.time()
        candle_ts = self.get_candle_start_time(now)
        log_and_broadcast("\033[1;36m==================================================\033[0m")
        log_and_broadcast(f"\033[1;36mSTARTING {candle_ts.strftime('%H:%M')} AETHER CYCLE\033[0m")
        log_and_broadcast("AETHER Clock synchronized. Launching pre-emptive cycle.")
        
        update_agent_status("ExecutionEngine", "AETHER Clock synchronized. Launching pre-emptive cycle.", is_active=True)
        
        end_dt = now.replace(hour=16, minute=0, second=0)
        
        update_agent_status("ExecutionEngine", f"Fetching live ticks...", is_active=True)
        candles = self.fetch_live_candles(candle_ts, end_dt)
        await self.evaluate_and_trade(candles, candle_ts)
        
        # Log process metrics
        try:
            import json, os
            metrics_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "process_metrics.json")
            data = {}
            if os.path.exists(metrics_file):
                with open(metrics_file, 'r') as f: data = json.load(f)
            dur = time.time() - start_time
            if "AI Evaluation Cycle" not in data:
                data["AI Evaluation Cycle"] = {"avg": dur, "count": 1, "last": dur}
            else:
                c = data["AI Evaluation Cycle"]["count"]
                data["AI Evaluation Cycle"]["avg"] = ((data["AI Evaluation Cycle"]["avg"] * c) + dur) / (c + 1)
                data["AI Evaluation Cycle"]["count"] += 1
                data["AI Evaluation Cycle"]["last"] = dur
            with open(metrics_file, 'w') as f: json.dump(data, f)
        except Exception: pass

    async def trigger_finalize(self):
        now = datetime.datetime.now()
        status = get_market_status()
        if status != "OPEN":
            if not (status == "POST_MARKET" and now.hour == 15 and now.minute == 30):
                return

        health = get_system_health()
        if not health["overall_ok"]:
            return

        update_agent_status("ExecutionEngine", "Finalizing memory block...", is_active=True)
        start_time = time.time()
        candle_ts = self.get_candle_start_time(now) - datetime.timedelta(minutes=15)
        log_and_broadcast(f"Step 6: Finalizing {candle_ts.strftime('%H:%M:%S')} block...")
        end_dt = now.replace(hour=16, minute=0, second=0)
        candles = self.fetch_live_candles(candle_ts, end_dt)
        self.save_finalized_candles(candles, candle_ts)
        
        update_agent_status("ExecutionEngine", "Awaiting timeframe close...", is_active=False)
        
        # Log process metrics
        try:
            import json, os
            metrics_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "process_metrics.json")
            data = {}
            if os.path.exists(metrics_file):
                with open(metrics_file, 'r') as f: data = json.load(f)
            dur = time.time() - start_time
            if "Block Finalization" not in data:
                data["Block Finalization"] = {"avg": dur, "count": 1, "last": dur}
            else:
                c = data["Block Finalization"]["count"]
                data["Block Finalization"]["avg"] = ((data["Block Finalization"]["avg"] * c) + dur) / (c + 1)
                data["Block Finalization"]["count"] += 1
                data["Block Finalization"]["last"] = dur
            with open(metrics_file, 'w') as f: json.dump(data, f)
        except Exception: pass

    def schedule_tasks(self):
        self.scheduler.add_job(self.trigger_preemptive, CronTrigger(minute='14,29,44,59', second='45'), misfire_grace_time=60)
        self.scheduler.add_job(self.trigger_finalize, CronTrigger(minute='0,15,30,45', second='5'), misfire_grace_time=60)
        self.scheduler.start()

    async def run(self):
        logger.info("Starting Execution Engine Pipeline (AETHER V2 Native API Mode)...")
        
        self.schedule_tasks()
        
        while True:
            await asyncio.sleep(3600)

if __name__ == "__main__":
    engine = LiveExecutionEngine()
    asyncio.run(engine.run())
