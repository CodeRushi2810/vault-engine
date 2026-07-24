import time
import subprocess
import datetime
import json
import os
import pandas as pd
import websockets
import asyncio
import threading
import contextlib
import sys

from core.market_utils import is_market_open, get_market_status
from core.data_utils import get_previous_close_prices
from core.health_check import is_connected_to_internet
from core.system_logger import setup_logger
from core.agent_state import update_agent_status

logger = setup_logger("bootup")

def generate_previous_close():
    logger.info("Injecting previous close and offline prices into dashboard_data.json...")
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    
    try:
        close_prices = get_previous_close_prices()
        json_path = os.path.join(BASE_DIR, "data", "dashboard_data.json")
        
        data = {"trades": []}
        if os.path.exists(json_path):
            try:
                with open(json_path, 'r') as f:
                    data = json.load(f)
            except Exception:
                pass
                
        data["prevClosePrices"] = close_prices
        
        # Inject offline LTP if market is closed to prevent 0% drops in UI
        if not is_market_open():
            if "market_data" not in data:
                data["market_data"] = {}
            try:
                from growwapi import GrowwAPI
                if os.environ.get('GROWW_TOKEN'):
                    with contextlib.redirect_stdout(open(os.devnull, 'w')):
                        groww = GrowwAPI(os.environ.get('GROWW_TOKEN'))
                        
                        # Fetch official VWAP closing prices for all tracked stocks
                        for stock in close_prices.keys():
                            try:
                                q = groww.get_quote(stock, "NSE", "CASH")
                                if q and 'last_price' in q:
                                    data["market_data"][stock] = q['last_price']
                                else:
                                    # Fallback to local CSV if API fails
                                    data["market_data"][stock] = close_prices[stock]
                            except Exception:
                                data["market_data"][stock] = close_prices[stock]

                        # Fetch indices directly via API
                        nifty = groww.get_quote("NIFTY", "NSE", "CASH")
                        sensex = groww.get_quote("SENSEX", "BSE", "CASH")
                        
                        def parse_index(idx_q):
                            if not idx_q: return None, None, None
                            ltp = idx_q.get("last_price")
                            c = idx_q.get("ohlc", {}).get("close")
                            if ltp is not None and c is not None:
                                return ltp, ltp - c, ((ltp - c) / c * 100) if c else 0
                            return ltp, None, None

                        n_ltp, n_dc, n_dcp = parse_index(nifty)
                        s_ltp, s_dc, s_dcp = parse_index(sensex)

                        data["INDICES"] = {
                            "NIFTY": {
                                "ltp": n_ltp,
                                "dayChange": n_dc,
                                "dayChangePerc": n_dcp
                            },
                            "SENSEX": {
                                "ltp": s_ltp,
                                "dayChange": s_dc,
                                "dayChangePerc": s_dcp
                            }
                        }
            except Exception as e:
                logger.error(f"Failed to fetch VWAP quotes: {e}")
        
        with open(json_path, 'w') as f:
            json.dump(data, f)
        logger.info("dashboard_data.json successfully updated natively without API calls!")
    except Exception as e:
        logger.error(f"Failed to update dashboard_data.json: {e}")

async def heartbeat_handler(websocket):
    try:
        while True:
            await websocket.send(json.dumps({"status": "alive", "timestamp": datetime.datetime.now().isoformat()}))
            await asyncio.sleep(5)
    except Exception:
        pass

async def main_server():
    async with websockets.serve(heartbeat_handler, "0.0.0.0", 8001):
        await asyncio.Future()

def run_heartbeat_server():
    asyncio.run(main_server())

def main():
    update_agent_status("BootupCoordinator", "Initializing AI Live Trading Pipeline...", is_active=True)
    logger.info("="*50)
    logger.info("Starting AI Live Trading Pipeline...")
    logger.info("="*50)
    
    # 0. Global Auth Cache
    from growwapi import GrowwAPI
    from dotenv import load_dotenv
    import contextlib

    load_dotenv()
    logger.info("Awaiting internet connection...")
    while not is_connected_to_internet():
        time.sleep(5)
    logger.info("Internet connection verified.")
    
    from core.auth import get_groww_token
    try:
        token = get_groww_token()
        logger.info("Authenticated with Groww API. Session Token Cached.")
    except Exception as e:
        logger.error(f"Groww API Auth Failed: {e}")
    
    # Pre-generate static previous close prices for the UI
    update_agent_status("BootupCoordinator", "Generating static previous close prices for the UI...", is_active=True)
    generate_previous_close()
    
    logger.info("Bootstrapping missing historical candles (Auto Catch-Up)...")
    update_agent_status("BootupCoordinator", "Bootstrapping missing historical candles (Auto Catch-Up)...", is_active=True)
    subprocess.run(["python", "-m", "core.fetch_data"])
    logger.info("Historical data fully synchronized.")
    update_agent_status("BootupCoordinator", "Historical data fully synchronized.", is_active=False)
    
    def start_and_wait(command, ready_strings):
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        ready_event = threading.Event()
        
        def output_reader():
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                for rs in ready_strings:
                    if rs in line:
                        ready_event.set()
                        
        threading.Thread(target=output_reader, daemon=True).start()
        ready_event.wait(timeout=15)
        return process

    # 1. Start live_engine.py unconditionally (it handles orders and runs continuously)
    logger.info("Starting core/live_engine.py...")
    engine_process = start_and_wait(["python", "-m", "core.live_engine"], ["Starting Execution Engine Pipeline"])
    
    logger.info("Starting background WebSocket Heartbeat server on port 8001...")
    heartbeat_thread = threading.Thread(target=run_heartbeat_server, daemon=True)
    heartbeat_thread.start()
    
    feed_process = start_and_wait(["python", "-m", "core.live_feed_server"], ["Ready to Groww!", "Bypassing Live Feed subscriptions"])
    
    logger.info("Starting background Discord listener (core/discord_listener.py)...")
    discord_process = start_and_wait(["python", "-m", "core.discord_listener"], ["Synced", "Logged in as"])
    
    market_state = get_market_status()
    
    try:
        while True:
            current_state = get_market_status()
            
            # Detect transition from OPEN to POST_MARKET
            if current_state == "POST_MARKET" and market_state == "OPEN":
                logger.info("Market transitioned to POST_MARKET.")
                logger.info("Fetching end-of-day 1D candles from Groww API...")
                subprocess.run(["python", "-m", "core.fetch_data"])
                
            # Detect transition from POST_MARKET to CLOSED
            elif current_state == "CLOSED" and market_state == "POST_MARKET":
                logger.info("Market transitioned to CLOSED.")
                logger.info("Fetching final official VWAP closing prices...")
                generate_previous_close()
                
                # Restart feed server to refresh tokens and clear cache for the night
                logger.info("Restarting live_feed_server.py for overnight Dashboard access...")
                feed_process.terminate()
                feed_process.wait()
                feed_process = subprocess.Popen(["python", "-m", "core.live_feed_server"])
                
            # Detect transition from CLOSED to PRE_MARKET
            elif current_state == "PRE_MARKET" and market_state in ["CLOSED", "HOLIDAY", "WEEKEND"]:
                logger.info("Market transitioned to PRE_MARKET.")
                # Restart feed server to get fresh morning token and warmup connections
                logger.info("Restarting live_feed_server.py for morning warmup...")
                feed_process.terminate()
                feed_process.wait()
                feed_process = subprocess.Popen(["python", "-m", "core.live_feed_server"])
                
                # Also restart discord bot in case connection dropped overnight
                if discord_process and discord_process.poll() is None:
                    discord_process.terminate()
                    discord_process.wait()
                discord_process = subprocess.Popen(["python", "-m", "core.discord_listener"])
                
            # Log transition to OPEN
            elif current_state == "OPEN" and market_state == "PRE_MARKET":
                logger.info("Market transitioned to OPEN. Continuous trading active.")

            update_agent_status("BootupCoordinator", f"Pipeline synchronized. Market Status: {current_state}", is_active=False)
            
            market_state = current_state
            time.sleep(5)
            
    except KeyboardInterrupt:
        logger.info("Pipeline stopped by user. Cleaning up processes...")
        try:
            from core.data_utils import push_dashboard_to_mongo
            push_dashboard_to_mongo()
        except Exception as e:
            logger.error(f"Error pushing to mongo on exit: {e}")
            
        if feed_process and feed_process.poll() is None:
            feed_process.terminate()
        if engine_process and engine_process.poll() is None:
            engine_process.terminate()
        if discord_process and discord_process.poll() is None:
            discord_process.terminate()
        logger.info("Cleanup complete. Exiting.")

if __name__ == "__main__":
    main()
