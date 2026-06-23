import time
import subprocess
import datetime
import json
import os
import pandas as pd
import websockets
import asyncio
import threading

def is_market_open():
    now = datetime.datetime.now()
    # Check if weekday (0=Monday, 4=Friday)
    if now.weekday() > 4:
        return False
        
    # Check if between 9:00 AM and 3:30 PM
    start = now.replace(hour=8, minute=50, second=0, microsecond=0)
    end = now.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return start <= now <= end

from core.data_utils import get_previous_close_prices

from core.system_logger import setup_logger
logger = setup_logger("bootup")



def generate_previous_close():
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Injecting previous close prices into dashboard_data.json...")
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
    API_KEY = os.getenv('GROWW_API_KEY')
    API_SECRET = os.getenv('GROWW_API_SECRET')
    if API_KEY and API_SECRET:
        with contextlib.redirect_stdout(open(os.devnull, 'w')):
            try:
                token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
                os.environ['GROWW_TOKEN'] = token
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Authenticated with Groww API. Session Token Cached.")
            except Exception as e:
                logger.error(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Groww API Auth Failed: {e}")
    else:
        logger.error(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Missing GROWW_API_KEY or GROWW_API_SECRET in .env!")
    
    # Pre-generate static previous close prices for the UI
    generate_previous_close()
    
    # 1. Start live_engine.py unconditionally (it handles orders and runs continuously)
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting core/live_engine.py...")
    engine_process = subprocess.Popen(["python", "-m", "core.live_engine"])
    
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting background WebSocket Heartbeat server on port 8001...")
    heartbeat_thread = threading.Thread(target=run_heartbeat_server, daemon=True)
    heartbeat_thread.start()
    
    feed_process = subprocess.Popen(["python", "-m", "core.live_feed_server"])
    
    logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Starting background Discord listener (core/discord_listener.py)...")
    discord_process = subprocess.Popen(["python", "-m", "core.discord_listener"])
    
    market_state = "OPEN" if is_market_open() else "CLOSED"
    
    try:
        while True:
            current_state = "OPEN" if is_market_open() else "CLOSED"
            
            # Detect transition from OPEN to CLOSED
            if current_state == "CLOSED" and market_state == "OPEN":
                logger.info(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Market transitioned to CLOSED.")
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Fetching end-of-day 1D candles from Groww API...")
                subprocess.run(["python", "-m", "core.fetch_data"])
                generate_previous_close()
                
                # Restart feed server to refresh tokens and clear cache for the night
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Restarting live_feed_server.py for overnight Dashboard access...")
                feed_process.terminate()
                feed_process.wait()
                feed_process = subprocess.Popen(["python", "-m", "core.live_feed_server"])
                
            # Detect transition from CLOSED to OPEN
            elif current_state == "OPEN" and market_state == "CLOSED":
                logger.info(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] Market transitioned to OPEN.")
                # Restart feed server to get fresh morning token
                logger.info(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] Restarting live_feed_server.py for morning session...")
                feed_process.terminate()
                feed_process.wait()
                feed_process = subprocess.Popen(["python", "-m", "core.live_feed_server"])
                
                # Also restart discord bot in case connection dropped overnight
                if discord_process and discord_process.poll() is None:
                    discord_process.terminate()
                    discord_process.wait()
                discord_process = subprocess.Popen(["python", "-m", "core.discord_listener"])

            market_state = current_state
            time.sleep(5)
            
    except KeyboardInterrupt:
        logger.info("\nPipeline stopped by user. Cleaning up processes...")
        if feed_process and feed_process.poll() is None:
            feed_process.terminate()
        if engine_process and engine_process.poll() is None:
            engine_process.terminate()
        if discord_process and discord_process.poll() is None:
            discord_process.terminate()
        logger.info("Cleanup complete. Exiting.")

if __name__ == "__main__":
    main()
