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

logger = setup_logger("bootup")

def generate_previous_close():
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Injecting previous close and offline prices into dashboard_data.json...")
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
                        
                        data["INDICES"] = {
                            "NIFTY": {
                                "ltp": nifty.get("last_price") if nifty else None,
                                "dayChange": nifty.get("day_change") if nifty else None,
                                "dayChangePerc": nifty.get("day_change_perc") if nifty else None
                            },
                            "SENSEX": {
                                "ltp": sensex.get("last_price") if sensex else None,
                                "dayChange": sensex.get("day_change") if sensex else None,
                                "dayChangePerc": sensex.get("day_change_perc") if sensex else None
                            }
                        }
            except Exception as e:
                logger.error(f"Failed to fetch VWAP quotes: {e}")
        
        with open(json_path, 'w') as f:
            json.dump(data, f)
        logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] dashboard_data.json successfully updated natively without API calls!")
    except Exception as e:
        logger.error(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Failed to update dashboard_data.json: {e}")

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
    logger.info("="*50)
    logger.info("Starting AI Live Trading Pipeline...")
    logger.info("="*50)
    
    # 0. Global Auth Cache
    from growwapi import GrowwAPI
    from dotenv import load_dotenv
    import contextlib

    load_dotenv()
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Awaiting internet connection...")
    while not is_connected_to_internet():
        time.sleep(5)
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Internet connection verified.")
    
    from core.auth import get_groww_token
    try:
        token = get_groww_token()
        logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Authenticated with Groww API. Session Token Cached.")
    except Exception as e:
        logger.error(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Groww API Auth Failed: {e}")
    
    # Pre-generate static previous close prices for the UI
    generate_previous_close()
    
    logger.info(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Bootstrapping missing historical candles (Auto Catch-Up)...")
    subprocess.run(["python", "-m", "core.fetch_data"])
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Historical data fully synchronized.\n")
    
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
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting core/live_engine.py...")
    engine_process = start_and_wait(["python", "-m", "core.live_engine"], ["Starting Execution Engine Pipeline"])
    
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting background WebSocket Heartbeat server on port 8001...")
    heartbeat_thread = threading.Thread(target=run_heartbeat_server, daemon=True)
    heartbeat_thread.start()
    
    feed_process = start_and_wait(["python", "-m", "core.live_feed_server"], ["Ready to Groww!", "Bypassing Live Feed subscriptions"])
    
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting background Discord listener (core/discord_listener.py)...")
    discord_process = start_and_wait(["python", "-m", "core.discord_listener"], ["Synced", "Logged in as"])
    
    market_state = get_market_status()
    
    try:
        while True:
            current_state = get_market_status()
            
            # Detect transition from OPEN to POST_MARKET
            if current_state == "POST_MARKET" and market_state == "OPEN":
                logger.info(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Market transitioned to POST_MARKET.")
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Fetching end-of-day 1D candles from Groww API...")
                subprocess.run(["python", "-m", "core.fetch_data"])
                
            # Detect transition from POST_MARKET to CLOSED
            elif current_state == "CLOSED" and market_state == "POST_MARKET":
                logger.info(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Market transitioned to CLOSED.")
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Fetching final official VWAP closing prices...")
                generate_previous_close()
                
                # Restart feed server to refresh tokens and clear cache for the night
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Restarting live_feed_server.py for overnight Dashboard access...")
                feed_process.terminate()
                feed_process.wait()
                feed_process = subprocess.Popen(["python", "-m", "core.live_feed_server"])
                
            # Detect transition from CLOSED to PRE_MARKET
            elif current_state == "PRE_MARKET" and market_state in ["CLOSED", "HOLIDAY", "WEEKEND"]:
                logger.info(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Market transitioned to PRE_MARKET.")
                # Restart feed server to get fresh morning token and warmup connections
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Restarting live_feed_server.py for morning warmup...")
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
                logger.info(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Market transitioned to OPEN. Continuous trading active.")

            market_state = current_state
            time.sleep(5)
            
    except KeyboardInterrupt:
        logger.info("\nPipeline stopped by user. Cleaning up processes...")
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
