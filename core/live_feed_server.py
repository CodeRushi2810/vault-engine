import os
import json
import threading
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from growwapi import GrowwAPI, GrowwFeed
from dotenv import load_dotenv
import time
import datetime

from core.system_logger import setup_logger
from core.config import STOCK_TOKENS as tokens, TOKEN_TO_STOCK
from core.health_check import get_system_health
from core.market_utils import get_market_status
from core.agent_state import get_all_agent_states, update_agent_status
logger = setup_logger("live_feed")

# Suppress growwapi logs to prevent raw 'Error:' spam
import logging
logging.getLogger("growwapi").setLevel(logging.CRITICAL)
for name in logging.root.manager.loggerDict:
    if name.startswith("growwapi"):
        logging.getLogger(name).setLevel(logging.CRITICAL)
@asynccontextmanager
async def lifespan(app: FastAPI):
    manager.loop = asyncio.get_running_loop()
    t = threading.Thread(target=start_groww_feed, daemon=True)
    t.start()
    t2 = threading.Thread(target=tail_vault_log, daemon=True)
    t2.start()
    yield

app = FastAPI(lifespan=lifespan)

# Allow CORS for Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

@app.get("/api/dashboard_data")
async def get_dashboard_data():
    json_path = os.path.join(BASE_DIR, "data", "dashboard_data.json")
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(content={"trades": []})


@app.get("/api/notifications")
async def get_notifications():
    csv_path = os.path.join(BASE_DIR, "data", "notification_state.csv")
    if os.path.exists(csv_path):
        with open(csv_path, 'r') as f:
            return Response(content=f.read(), media_type="text/csv")
    return Response(content="Key,Value\n", media_type="text/csv")

from fastapi import Request
@app.post("/api/notifications")
async def post_notifications(request: Request):
    csv_path = os.path.join(BASE_DIR, "data", "notification_state.csv")
    content = await request.body()
    with open(csv_path, 'wb') as f:
        f.write(content)
    return JSONResponse(content={"status": "success"})

class ConnectionManager:
    def __init__(self):
        self.active_connections = []
        self.loop = None

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in list(self.active_connections):
            try:
                await connection.send_text(message)
            except Exception:
                self.active_connections.remove(connection)

manager = ConnectionManager()
feed = None
initial_prices = {}
# Track ticks for NEXUS agent
nexus_tick_count = 0
last_nexus_update = time.time()
internet_status = "ONLINE"

def on_data_received(meta):
    global feed, nexus_tick_count
    if feed is None: return
    raw_data = feed.get_ltp()
    nexus_tick_count += 1
    
    # Map tokens to symbols server-side so the frontend doesn't need tokens
    data = {'NSE': {'CASH': {}}, 'INDICES': {}}
    if 'NSE' in raw_data and 'CASH' in raw_data['NSE']:
        for token, val in raw_data['NSE']['CASH'].items():
            symbol = TOKEN_TO_STOCK.get(token, token)
            data['NSE']['CASH'][symbol] = val

    try:
        idx_raw = feed.get_index_value()
        if idx_raw:
            if 'NSE' in idx_raw and 'CASH' in idx_raw['NSE']:
                nifty_data = idx_raw['NSE']['CASH'].get('NIFTY')
                if nifty_data and nifty_data.get('value'):
                    ltp = nifty_data.get('value')
                    c = initial_prices.get('NIFTY', {}).get('close', ltp)
                    data['INDICES']['NIFTY'] = {
                        "ltp": ltp,
                        "dayChange": ltp - c,
                        "dayChangePerc": ((ltp - c) / c * 100) if c else 0
                    }
            if 'BSE' in idx_raw and 'CASH' in idx_raw['BSE']:
                sensex_data = idx_raw['BSE']['CASH'].get('1')
                if sensex_data and sensex_data.get('value'):
                    ltp = sensex_data.get('value')
                    c = initial_prices.get('SENSEX', {}).get('close', ltp)
                    data['INDICES']['SENSEX'] = {
                        "ltp": ltp,
                        "dayChange": ltp - c,
                        "dayChangePerc": ((ltp - c) / c * 100) if c else 0
                    }
    except Exception as e:
        pass
            
    # Broadcast to all connected clients
    if manager.loop and manager.loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps(data)), manager.loop)



def poll_agents():
    global nexus_tick_count, last_nexus_update
    while True:
        try:
            now = time.time()
            # Calculate tick rate for NEXUS
            elapsed = now - last_nexus_update
            if elapsed >= 1.0:
                tps = int(nexus_tick_count / elapsed)
                nexus_tick_count = 0
                last_nexus_update = now
                
                market_stat = get_market_status()
                if market_stat == "OPEN" and feed is not None:
                    update_agent_status("DataFeedServer", f"Consuming NATS stream at {tps} ticks/sec", is_active=True)
                elif market_stat == "PRE_MARKET":
                    update_agent_status("DataFeedServer", "REST Polling Indicative Equilibrium Price", is_active=True)
                else:
                    update_agent_status("DataFeedServer", f"Market {market_stat}. Waiting for schedule.", is_active=False)

            market_status = get_market_status()

            agents_state = get_all_agent_states()
            if "ExecutionEngine" in agents_state and not agents_state["ExecutionEngine"].get("is_active"):
                if market_status == "OPEN":
                    now_dt = datetime.datetime.now()
                    minutes = now_dt.minute % 15
                    seconds = now_dt.second
                    remaining_m = 14 - minutes
                    remaining_s = 45 - seconds
                    if remaining_s < 0:
                        remaining_s += 60
                        remaining_m -= 1
                    agents_state["ExecutionEngine"]["status"] = f"Awaiting timeframe close... {remaining_m}m {remaining_s}s"
                else:
                    agents_state["ExecutionEngine"]["status"] = f"Market {market_status}. Engine resting."

            payload = {
                "AGENTS": agents_state
            }
            payload["INTERNET_STATUS"] = internet_status
            payload["SYSTEM_STATUS"] = get_system_health()
            
            # Determine FEED_STATE
            if feed is not None:
                payload["FEED_STATE"] = "NATS_WEBSOCKET"
            elif get_market_status() == "PRE_MARKET":
                payload["FEED_STATE"] = "PRE_MARKET_POLLING"
            else:
                payload["FEED_STATE"] = "REST_POLLING"
                
            # Read PROCESS_METRICS
            try:
                import json, os
                metrics_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "process_metrics.json")
                if os.path.exists(metrics_file):
                    with open(metrics_file, 'r') as f:
                        payload["PROCESS_METRICS"] = json.load(f)
            except Exception:
                pass

            # Read TOP_SIGNALS
            try:
                signals_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "latest_signals.json")
                if os.path.exists(signals_file):
                    with open(signals_file, 'r') as f:
                        payload["TOP_SIGNALS"] = json.load(f)
            except Exception:
                pass

            market_status = get_market_status()
            payload["MARKET_STATUS"] = market_status
            
            if market_status == "HOLIDAY" or market_status == "WEEKEND":
                from core.market_utils import get_holiday_name, get_next_trading_day
                hn = get_holiday_name()
                nxt = get_next_trading_day()
                if hn: payload["HOLIDAY_NAME"] = hn
                payload["NEXT_OPEN"] = nxt.strftime("%d %B")
            
            if manager.loop and manager.loop.is_running():
                asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps(payload)), manager.loop)
        except Exception as e:
            logger.error("Error polling agents:", e)
        time.sleep(1)



def pre_market_poller(groww, tokens):
    """
    Dedicated background thread to poll the REST API every 15 seconds 
    during the PRE_MARKET phase (9:00 - 9:15) to capture the 9:08 Indicative Equilibrium Price,
    because the WebSocket feed is notoriously silent until 9:15.
    """
    while True:
        try:
            from core.market_utils import get_market_status
            if get_market_status() == "PRE_MARKET":
                data = {'NSE': {'CASH': {}}}
                for symbol, token in tokens.items():
                    try:
                        q = groww.get_quote(symbol, "NSE", "CASH")
                        if q and 'last_price' in q:
                            data['NSE']['CASH'][symbol] = {"p": q['last_price']}
                    except:
                        pass
                
                # Also poll indices
                data['INDICES'] = {}
                for idx_symbol, idx_exch in [("NIFTY", "NSE"), ("SENSEX", "BSE")]:
                    try:
                        q = groww.get_quote(idx_symbol, idx_exch, "CASH")
                        if q and 'last_price' in q:
                            c = q.get('ohlc', {}).get('close', q['last_price'])
                            data["INDICES"][idx_symbol] = {
                                "ltp": q['last_price'],
                                "dayChange": q['last_price'] - c,
                                "dayChangePerc": ((q['last_price'] - c) / c * 100) if c else 0
                            }
                    except:
                        pass
                
                if manager.loop and manager.loop.is_running():
                    asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps(data)), manager.loop)
                    
            time.sleep(15)
        except Exception as e:
            time.sleep(5)

def start_groww_feed():
    try:
        logger.info("Initializing Live Feed Server with shared Token...")
        
        from core.auth import get_groww_token
        access_token = get_groww_token()
            
        import contextlib
        with contextlib.redirect_stdout(open(os.devnull, 'w')):
            groww = GrowwAPI(access_token)
        
        agents_thread = threading.Thread(target=poll_agents, daemon=True)
        agents_thread.start()
        
        pre_market_thread = threading.Thread(target=pre_market_poller, args=(groww, tokens), daemon=True)
        pre_market_thread.start()

        status = get_market_status()
        if status not in ["PRE_MARKET", "OPEN", "POST_MARKET"]:
            logger.info(f"Market is {status}. Bypassing Live Feed subscriptions.")
            return
            
        global initial_prices
        logger.info("Fetching initial quotes for all stocks and indices...")
        for symbol, token in list(tokens.items()) + [("NIFTY", "NIFTY"), ("SENSEX", "1")]:
            max_retries = 3
            retry_delay = 2
            exch = "BSE" if symbol == "SENSEX" else "NSE"
            for attempt in range(max_retries):
                try:
                    q = groww.get_quote(symbol, exch, "CASH")
                    if q and 'last_price' in q:
                        close_p = q.get('ohlc', {}).get('close', q['last_price'])
                        initial_prices[symbol] = {"ltp": q['last_price'], "close": close_p}
                    
                    time.sleep(0.5)
                    break
                except Exception as e:
                    error_str = str(e).lower()
                    if "rate limit" in error_str or "429" in error_str:
                        if attempt < max_retries - 1:
                            logger.warning(f"Rate limit hit for {symbol}. Retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            retry_delay *= 2
                            continue
                    break
                
        instruments_list = [{"exchange": "NSE", "segment": "CASH", "exchange_token": str(v)} for v in tokens.values()]

        
        while True:
            try:
                import concurrent.futures
                def _init_feed():
                    with contextlib.redirect_stdout(open(os.devnull, 'w')):
                        return GrowwFeed(groww)
                        
                logger.info("Connecting to Groww WebSockets (NATS)...")
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = executor.submit(_init_feed)
                global feed
                
                try:
                    feed = future.result(timeout=30)
                except concurrent.futures.TimeoutError:
                    raise Exception("Connection timed out after 30 seconds")
                    
                logger.info("Subscribing to LTP for stocks...")
                feed.subscribe_ltp(instruments_list, on_data_received=on_data_received)
                
                logger.info("Subscribing to Index values for NIFTY and SENSEX...")
                index_list = [
                    {"exchange": "NSE", "segment": "CASH", "exchange_token": "NIFTY"},
                    {"exchange": "BSE", "segment": "CASH", "exchange_token": "1"}
                ]
                feed.subscribe_index_value(index_list, on_data_received=on_data_received)
                
                logger.info("Consuming feed...")
                feed.consume()
                # If successful, NATS is running in background and handles its own reconnects. Break outer loop.
                break
            except Exception as e:
                logger.error(f"Error starting feed (NATS): {e}")
                logger.info("Falling back to REST Polling for 5 minutes before retrying NATS...")
                
                fallback_start = time.time()
                while time.time() - fallback_start < 300:
                    time.sleep(2)  # Wait a bit between global polls to avoid hitting the 10 req/s hard limit
                    
                    # Fallback for Stocks
                    for symbol, token in tokens.items():
                        try:
                            q = groww.get_quote(symbol, "NSE", "CASH")
                            if q and 'last_price' in q:
                                initial_prices[symbol] = {"ltp": q['last_price']}
                                # Broadcast to UI
                                if manager.loop and manager.loop.is_running():
                                    asyncio.run_coroutine_threadsafe(
                                        manager.broadcast(json.dumps({"NSE": {"CASH": {symbol: {"ltp": q['last_price']}}}})),
                                        manager.loop
                                    )
                            time.sleep(0.15)
                        except Exception as poll_e:
                            error_str = str(poll_e).lower()
                            if "rate limit" in error_str or "429" in error_str:
                                time.sleep(5)
                            continue
    except Exception as e:
        logger.error(f"Error in start_groww_feed: {e}")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        if initial_prices:
            await websocket.send_text(json.dumps({"NSE": {"CASH": initial_prices}}))
        while True:
            # Just keep the connection open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)



from pydantic import BaseModel
from core.discord_bot import send_discord_message

class NotificationTestRequest(BaseModel):
    trade_type: str
    stock: str
    shares: int = 10
    buy_price: float
    sell_price: float = None
    pnl: float = None
    pnl_percent: float = None

def tail_vault_log():
    log_file = os.path.join(BASE_DIR, "data", "vault.log")
    if not os.path.exists(log_file):
        open(log_file, 'a').close()
    
    with open(log_file, 'r', encoding='utf-8') as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.1)
                continue
            
            clean_msg = line.strip().replace("\033[1;36m", "").replace("\033[0m", "")
            if manager.loop and manager.loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    manager.broadcast(json.dumps({"ENGINE_LOG": clean_msg, "timestamp": datetime.datetime.now().isoformat()})), 
                    manager.loop
                )

@app.get("/api/logs")
async def get_logs():
    log_file = os.path.join(BASE_DIR, "data", "vault.log")
    if not os.path.exists(log_file):
        return {"logs": []}
        
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            recent = lines[-200:]
            
        out = []
        for line in recent:
            clean = line.strip().replace("\033[1;36m", "").replace("\033[0m", "")
            if clean:
                out.append({"message": clean, "timestamp": datetime.datetime.now().isoformat()})
        return {"logs": out}
    except Exception as e:
        return {"logs": []}

@app.get("/api/live-prices")
async def get_live_prices():
    global initial_prices
    return initial_prices

@app.post("/api/trigger-update")
async def trigger_update():
    if manager.loop and manager.loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps({"type": "UPDATE_DASHBOARD"})), manager.loop)
    return {"success": True}

@app.post("/api/test-notification")
async def test_notification(req: NotificationTestRequest):
    if req.trade_type.upper() == 'BUY':
        msg = f"🟢 Bought {req.shares} {req.stock} at Rs {req.buy_price:,.2f}"
    else:
        pnl_str = f"+Rs {req.pnl:,.2f}" if req.pnl and req.pnl >= 0 else f"-Rs {abs(req.pnl) if req.pnl else 0:,.2f}"
        pnl_pct_str = f"+{req.pnl_percent:.2f}%" if req.pnl_percent and req.pnl_percent >= 0 else f"{req.pnl_percent or 0:.2f}%"
        icon = "🟢" if req.pnl and req.pnl >= 0 else "🔴"
        
        msg = f"{icon} Sold {req.shares} {req.stock} at Rs {req.sell_price:,.2f} | Entry: Rs {req.buy_price:,.2f} | PnL: {pnl_str} ({pnl_pct_str})"
              
    success = send_discord_message(msg)
    return {"success": success, "message": msg}

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "system_config.json")

def load_system_config():
    default_config = {"global": {"engineActive": True, "allowBuy": True, "allowSell": True}, "stocks": {}}
    if not os.path.exists(SETTINGS_FILE):
        return default_config
    with open(SETTINGS_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return default_config

def save_system_config(config):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(config, f, indent=4)

@app.get("/api/config")
async def get_system_config():
    return load_system_config()

from typing import Dict, Any

@app.post("/api/config")
async def update_system_config(config: Dict[str, Any]):
    save_system_config(config)
    return {"success": True, "config": config}

if __name__ == "__main__":
    uvicorn.run("core.live_feed_server:app", host="0.0.0.0", port=8000, reload=False, access_log=False, log_level="warning")
