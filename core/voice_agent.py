import os
import json
import math
import asyncio
import time
from pydantic import BaseModel
from google import genai
from google.genai import types

class UiAction(BaseModel):
    type: str
    tab: str | None = None
    key: str | None = None
    direction: str | None = None
    table: str | None = None
    delay: float | None = None

class HermesResponseModel(BaseModel):
    speech_text: str
    ui_actions: list[UiAction]

async def process_hermes_command(cmd: str, dash_data: dict, BASE_DIR: str, genai_client) -> tuple[str, list[dict]]:
    response_text = ""
    ui_actions_to_send = []
    
    try:
        closed_summary = {}
        open_summary = {}
        all_time_realized = 0.0
        total_invested = 0.0
        total_unrealized = 0.0
        
        market_data = dash_data.get("market_data", {})
        prev_closes = dash_data.get("prevClosePrices", {})
        
        for t in dash_data.get("trades", []):
            stock = t.get("Stock")
            status = t.get("Status")
            
            if status == "CLOSED":
                pnl = t.get("PnL_Amount", 0)
                closed_summary[stock] = closed_summary.get(stock, 0.0) + pnl
                all_time_realized += pnl
                
            elif status == "OPEN":
                shares = t.get("Shares", 0)
                cost = t.get("Cost_Basis", 0)
                total_invested += cost
                live_p = market_data.get(stock, t.get("Entry_Price", 0))
                u_pnl = (shares * live_p) - cost
                total_unrealized += u_pnl
                
                if stock not in open_summary:
                    open_summary[stock] = {
                        "shares": 0,
                        "total_cost": 0.0,
                        "live_price": live_p,
                        "unrealized_pnl": 0.0
                    }
                open_summary[stock]["shares"] += shares
                open_summary[stock]["total_cost"] += cost
                open_summary[stock]["unrealized_pnl"] += u_pnl
        
        total_1d_pnl = 0.0
        for stock, data in open_summary.items():
            if data["shares"] > 0:
                data["entry_price"] = data["total_cost"] / data["shares"]
            data["total_invested"] = data["total_cost"]
            data["current_value"] = data["live_price"] * data["shares"]
            del data["total_cost"]
            
            prev_c_data = prev_closes.get(stock, {})
            prev_c = data.get("entry_price", 0)
            if isinstance(prev_c_data, dict) and "prev_close" in prev_c_data:
                prev_c = prev_c_data["prev_close"]
            elif isinstance(prev_c_data, (int, float)):
                prev_c = prev_c_data
                
            total_1d_pnl += (data["live_price"] - prev_c) * data["shares"]
            
        for stock, data in open_summary.items():
            data["entry_price"] = math.ceil(data.get("entry_price", 0))
            data["live_price"] = math.ceil(data.get("live_price", 0))
            data["unrealized_pnl"] = math.ceil(data.get("unrealized_pnl", 0))
            data["total_invested"] = math.ceil(data.get("total_invested", 0))
            data["current_value"] = math.ceil(data.get("current_value", 0))
            
        for stock, pnl in closed_summary.items():
            closed_summary[stock] = math.ceil(pnl)
            
        for stock, p in market_data.items():
            if isinstance(p, (int, float)):
                market_data[stock] = math.ceil(p)
                
        from core.market_utils import get_market_status, get_holiday_name
        import datetime
        now = datetime.datetime.now()
        market_status = get_market_status(now)
        holiday = get_holiday_name(now)
        
        context_dict = {
            "metrics": {
                "realized_profit": math.ceil(all_time_realized),
                "unrealized_profit": math.ceil(total_unrealized),
                "invested_amount": math.ceil(total_invested),
                "available_cash": math.ceil(1000000 + all_time_realized - total_invested),
                "one_day_return": math.ceil(total_1d_pnl)
            },
            "market_info": {
                "status": market_status,
                "holiday_reason": holiday if holiday else "N/A"
            },
            "open_trades": open_summary,
            "closed_trades_pnl": closed_summary,
            "live_prices": market_data,
            "indices": dash_data.get("INDICES", {})
        }
        
        context_path = os.path.join(BASE_DIR, "data", "hermes_context.json")
        with open(context_path, "w") as fw:
            json.dump(context_dict, fw, indent=2)
            
        history_path = os.path.join(BASE_DIR, "data", "hermes_chat_history.json")
        history = []
        if os.path.exists(history_path):
            try:
                with open(history_path, "r") as f:
                    history = json.load(f)
            except:
                pass
                
        current_time = time.time()
        # Keep only history from the last 24 hours (86400 seconds)
        history = [msg for msg in history if current_time - msg.get("timestamp", 0) < 86400]
        
        history_context = ""
        if history:
            history_context = "Here is the previous conversation context, use this during the thinking and logical reasoning, dont repeat same thing in every answer. If the last prompt was to open the notification, and the user just says close it. Use the previous chat history to know what was the conversation was about instead of hallucinating. :\n"
            for msg in history:
                history_context += f"[{msg['role']}]: {msg['text']}\n"
            history_context += "\n"
            
        prompt = f"""You are Hermes, an all-purpose AI Voice Assistant integrated into the Vault Trading Engine.
{history_context}The user just spoke this command: "{cmd}"

You can answer ANY question the user asks. If the question is about their trading portfolio, use the following accurate data context:
{json.dumps(context_dict, indent=2)}

NOTE: The keys in the open_trades, closed_trades, and live_prices are stock ticker symbols (e.g., POWERINDIA is Hitachi Energy, KAYNES is Kaynes Technology, CGPOWER is CG Power). When the user asks about a company name, intelligently map it to the corresponding ticker in their portfolio. They are the exact same company, do not treat them as different entities! When speaking, prefer using the actual company name rather than the all-caps ticker symbol.

Available UI Actions you can fire (only if the user explicitly asks to navigate, open, toggle, or sort something):
- Switch Tab: {{"type": "HERMES_UI_TAB", "tab": "Dashboard" | "Explore" | "Portfolio" | "Trades" | "Stocks P&L" | "Config" | "Docs"}}
- Open Terminal/Console: {{"type": "HERMES_UI_CONSOLE_OPEN"}}
- Close Terminal/Console: {{"type": "HERMES_UI_CONSOLE_CLOSE"}}
- Toggle Terminal/Console: {{"type": "HERMES_UI_CONSOLE"}}
- Toggle Notifications: {{"type": "HERMES_UI_NOTIFICATIONS"}}
- Toggle Holdings Numbers (Hide/Show values in Portfolio tab): {{"type": "HERMES_TOGGLE_HOLDINGS_VISIBILITY"}}
- Toggle Open Trades section (Trades tab): {{"type": "HERMES_TOGGLE_OPEN_TRADES"}}
- Toggle Closed Trades section (Trades tab): {{"type": "HERMES_TOGGLE_CLOSED_TRADES"}}

Sorting Actions (For direction, use "asc" or "desc"):
- Sort Watchlist (Explore tab): {{"type": "HERMES_SORT_WATCHLIST", "key": "Stock" | "today_close" | "1D_Change", "direction": "asc" | "desc"}}
- Sort Holdings (Portfolio tab): {{"type": "HERMES_SORT_HOLDINGS", "key": "stock" | "currentValue" | "investedValue" | "unrealizedPercent", "direction": "asc" | "desc"}}
- Sort Open Trades table (Trades tab): {{"type": "HERMES_SORT_TABLE", "table": "open", "key": "Stock" | "Entry_Time" | "Entry_Price" | "PnL_Percent" | "Cost_Basis", "direction": "asc" | "desc"}}
- Sort Closed Trades table (Trades tab): {{"type": "HERMES_SORT_TABLE", "table": "closed", "key": "Stock" | "Entry_Time" | "Exit_Time" | "Entry_Price" | "Shares" | "Cost_Basis" | "PnL_Percent", "direction": "asc" | "desc"}}

Provide a short, snappy, highly charismatic, and natural-sounding response to speak aloud. You are a sleek, high-end, witty AI assistant (think JARVIS or a sharp Wall Street veteran). Be charming, slightly cheeky, highly engaging, and never boring or robotic. Instead of saying "Opening your dashboard now," say something stylish like "Right away, boss. Let's pull up the numbers." Give solid advice but make it fun and energetic! Keep it brief and conversational.
DO NOT use markdown or emojis. 
CRITICAL: Do not use repetitive transition phrases like "However", "That being said", or "Overall". Make your dialogue flow like a charismatic movie character.
CRITICAL: ALWAYS reply in English. Your voice synthesizer (Microsoft David) only speaks English natively. Even if the user speaks to you in Hindi or another language, you MUST respond in English.
CRITICAL: The TTS engine cannot read numbers with Indian comma placements (like 11,95,415) and will read the literal word "comma". To fix this, ALWAYS spell out large numbers using Indian terms (e.g., "11 Lakhs 95 Thousand 415" or "1 Crore 20 Lakhs"). Never use commas in numbers.
"""
        if genai_client:
            res = genai_client.models.generate_content(
                model='gemini-3.5-flash-lite',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=HermesResponseModel,
                )
            )
            data = json.loads(res.text)
            response_text = data.get("speech_text", "")
            
            for action in data.get("ui_actions", []):
                delay = action.pop("delay", 0)
                if delay:
                    action["delay"] = delay
                # Filter out None keys to keep WebSocket payload clean
                action_clean = {k: v for k, v in action.items() if v is not None}
                ui_actions_to_send.append(action_clean)
                
            # Append new messages to history and save
            history.append({"role": "User", "text": cmd, "timestamp": current_time})
            history.append({"role": "Hermes", "text": response_text, "timestamp": time.time()})
            with open(history_path, "w") as fw:
                json.dump(history, fw, indent=2)
        else:
            response_text = "Sorry, Gemini API is not configured."
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        response_text = "Sorry, I encountered an error while processing that."
        
    return response_text, ui_actions_to_send
