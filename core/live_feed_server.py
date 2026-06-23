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
logger = setup_logger("live_feed")



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

@app.get("/api/news_data")
async def get_news_data():
    json_path = os.path.join(BASE_DIR, "data", "news_data.json")
    if os.path.exists(json_path):
        with open(json_path, 'r') as f:
            return JSONResponse(content=json.load(f))
    return JSONResponse(content=[])

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

def poll_indices(groww_client):
    global internet_status
    while True:
        try:
            nifty = groww_client.get_quote("NIFTY", "NSE", "CASH")
            sensex = groww_client.get_quote("SENSEX", "BSE", "CASH")
            payload = {
                "INDICES": {
                    "NIFTY": {
                        "ltp": nifty.get("last_price"),
                        "dayChange": nifty.get("day_change"),
                        "dayChangePerc": nifty.get("day_change_perc")
                    },
                    "SENSEX": {
                        "ltp": sensex.get("last_price"),
                        "dayChange": sensex.get("day_change"),
                        "dayChangePerc": sensex.get("day_change_perc")
                    }
                }
            }
            internet_status = "ONLINE"
            if manager.loop and manager.loop.is_running():
                asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps(payload)), manager.loop)
        except Exception:
            internet_status = "OFFLINE"
        time.sleep(5)

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
            if manager.loop and manager.loop.is_running():
                asyncio.run_coroutine_threadsafe(manager.broadcast(json.dumps(payload)), manager.loop)
        except Exception as e:
            logger.error("Error polling agents:", e)
        time.sleep(1)

def start_groww_feed():
    load_dotenv()
    API_KEY = os.getenv("GROWW_API_KEY")
    API_SECRET = os.getenv("GROWW_API_SECRET")
    
    if not API_KEY or not API_SECRET:
        logger.info("Missing API credentials in .env")
        return
        
    try:
        logger.info("Initializing Live Feed Server with shared Token...")
        
        access_token = os.environ.get('GROWW_TOKEN')
        if not access_token:
            logger.info("Fallback: Re-authenticating with Groww...")
            access_token = GrowwAPI.get_access_token(api_key=API_KEY, secret=API_SECRET)
            
        import contextlib
        with contextlib.redirect_stdout(open(os.devnull, 'w')):
            groww = GrowwAPI(access_token)
            global feed
            feed = GrowwFeed(groww)
        
        threading.Thread(target=poll_indices, args=(groww,), daemon=True).start()
        threading.Thread(target=poll_agents, daemon=True).start()
        
        # Tokens dynamically fetched
        
        
        global initial_prices
        logger.info("Fetching initial quotes for all stocks...")
        for symbol, token in tokens.items():
            try:
                q = groww.get_quote(symbol, "NSE", "CASH")
                if q and 'last_price' in q:
                    initial_prices[symbol] = {"ltp": q['last_price']}
            except Exception as e:
                pass
                
        instruments_list = [{"exchange": "NSE", "segment": "CASH", "exchange_token": str(v)} for v in tokens.values()]
        
        logger.info("Subscribing to LTP for stocks...")
        feed.subscribe_ltp(instruments_list, on_data_received=on_data_received)
        logger.info("Consuming feed...")
        feed.consume()
    except Exception as e:
        logger.error(f"Error starting feed: {e}")


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

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "trade_settings.json")

def load_trade_settings():
    if not os.path.exists(SETTINGS_FILE):
        return {}
    with open(SETTINGS_FILE, "r") as f:
        try:
            return json.load(f)
        except:
            return {}

def save_trade_settings(settings):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=4)

@app.get("/api/trade_settings")
async def get_trade_settings():
    return load_trade_settings()

class TradeSettingUpdate(BaseModel):
    stock: str
    active: bool

@app.post("/api/trade_settings")
async def update_trade_setting(req: TradeSettingUpdate):
    settings = load_trade_settings()
    settings[req.stock] = req.active
    save_trade_settings(settings)
    return {"success": True, "settings": settings}

if __name__ == "__main__":
    uvicorn.run("core.live_feed_server:app", host="0.0.0.0", port=8000, reload=False, access_log=False, log_level="warning")
