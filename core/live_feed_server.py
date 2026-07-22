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
internet_status = "ONLINE"

def on_data_received(meta):
    global feed
    if feed is None: return
    raw_data = feed.get_ltp()
    
    # Map tokens to symbols server-side so the frontend doesn't need tokens
    data = {'NSE': {'CASH': {}}}
    if 'NSE' in raw_data and 'CASH' in raw_data['NSE']:
        for token, val in raw_data['NSE']['CASH'].items():
            symbol = TOKEN_TO_STOCK.get(token, token)
            data['NSE']['CASH'][symbol] = val
            
    # Broadcast to all connected clients
    if manager.loop and manager.loop.is_running():
        asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps(data)), manager.loop)



def poll_agents():
    while True:
        try:
            now = datetime.datetime.now()
            minutes = now.minute % 15
            seconds = now.second
            
            # Simple status simulation for execution engine based on time
            if minutes == 14 and seconds >= 45:
                exec_status = "EVALUATING LIVE CANDLES..."
                exec_color = "text-rose-400"
                exec_glow = "shadow-[0_0_60px_rgba(244,63,94,0.6)]"
                exec_bg = "bg-gradient-to-br from-rose-500 to-rose-900"
            else:
                remaining_m = 14 - minutes
                remaining_s = 45 - seconds
                if remaining_s < 0:
                    remaining_s += 60
                    remaining_m -= 1
                exec_status = f"Awaiting timeframe close... {remaining_m}m {remaining_s}s"
                exec_color = "text-emerald-400"
                exec_glow = "shadow-[0_0_50px_rgba(16,185,129,0.3)]"
                exec_bg = "bg-gradient-to-br from-emerald-500 to-teal-900"
                
            payload = {
                "AGENTS": {
                    "DataFeedServer": {
                        "name": "NEXUS",
                        "role": "Data Feed Server",
                        "description": "Streams high-frequency market ticks natively from broker.",
                        "status": "Streaming live ticks for 11 stocks natively...",
                        "color": "text-cyan-400",
                        "glow": "shadow-[0_0_40px_rgba(6,182,212,0.4)]",
                        "bg": "bg-gradient-to-br from-cyan-400 to-blue-900",
                        "lastActive": now.strftime('%H:%M:%S')
                    },
                    "SignalProcessor": {
                        "name": "LUMINA",
                        "role": "Signal Processor",
                        "description": "Filters market noise and synthesizes setup conditions.",
                        "status": "Scanning active indicators for mean-reversion...",
                        "color": "text-pink-400",
                        "glow": "shadow-[0_0_40px_rgba(236,72,153,0.4)]",
                        "bg": "bg-gradient-to-br from-pink-400 to-fuchsia-900",
                        "lastActive": now.strftime('%H:%M:%S')
                    },
                    "ExecutionEngine": {
                        "name": "AETHER",
                        "role": "Execution Engine",
                        "description": "The central brain. Evaluates models and triggers live market orders.",
                        "status": exec_status,
                        "color": exec_color,
                        "glow": exec_glow,
                        "bg": exec_bg,
                        "lastActive": now.strftime('%H:%M:%S')
                    },
                    "RiskManager": {
                        "name": "AEGIS",
                        "role": "Risk Manager",
                        "description": "Monitors portfolio drawdowns and manages dynamic capital exposure.",
                        "status": "Risk levels optimal. Maximum drawdown within bounds.",
                        "color": "text-purple-400",
                        "glow": "shadow-[0_0_40px_rgba(168,85,247,0.4)]",
                        "bg": "bg-gradient-to-br from-purple-400 to-indigo-900",
                        "lastActive": now.strftime('%H:%M:%S')
                    },
                    "BootupCoordinator": {
                        "name": "ORACLE",
                        "role": "Coordinator",
                        "description": "Synchronizes pipeline health and handles auto catch-up sequences.",
                        "status": "Pipeline synchronized. Auto Catch-Up Sequence armed.",
                        "color": "text-amber-400",
                        "glow": "shadow-[0_0_40px_rgba(251,191,36,0.4)]",
                        "bg": "bg-gradient-to-br from-amber-400 to-orange-900",
                        "lastActive": now.strftime('%H:%M:%S')
                    }
                }
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

def poll_indices(groww):
    """
    Dedicated background thread to poll NIFTY and SENSEX via REST.
    Bypasses WebSocket index issues where 'p' defaults to 0.
    """
    while True:
        try:
            from core.market_utils import get_market_status
            status = get_market_status()
            if status in ["OPEN", "PRE_MARKET"]:
                payload = {"INDICES": {}}
                for idx_symbol, idx_exch in [("NIFTY", "NSE"), ("SENSEX", "BSE")]:
                    try:
                        q = groww.get_quote(idx_symbol, idx_exch, "CASH")
                        if q and 'last_price' in q:
                            c = q.get('ohlc', {}).get('close', q['last_price'])
                            payload["INDICES"][idx_symbol] = {
                                "ltp": q['last_price'],
                                "dayChange": q['last_price'] - c,
                                "dayChangePerc": ((q['last_price'] - c) / c * 100) if c else 0
                            }
                    except:
                        pass
                if payload["INDICES"] and manager.loop and manager.loop.is_running():
                    asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps(payload)), manager.loop)
            time.sleep(3)
        except Exception as e:
            time.sleep(3)

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

        index_poller_thread = threading.Thread(target=poll_indices, args=(groww,), daemon=True)
        index_poller_thread.start()
        
        status = get_market_status()
        if status not in ["PRE_MARKET", "OPEN", "POST_MARKET"]:
            logger.info(f"Market is {status}. Bypassing Live Feed subscriptions.")
            return
            
        global initial_prices
        logger.info("Fetching initial quotes for all stocks...")
        for symbol, token in tokens.items():
            max_retries = 3
            retry_delay = 2
            for attempt in range(max_retries):
                try:
                    q = groww.get_quote(symbol, "NSE", "CASH")
                    if q and 'last_price' in q:
                        initial_prices[symbol] = {"ltp": q['last_price']}
                    
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
