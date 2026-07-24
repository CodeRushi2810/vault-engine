import json
import os
import re
import datetime
from core.market_utils import get_market_status, get_holiday_name, get_next_trading_day
from core.config import STOCK_ALIASES, TOKEN_TO_STOCK

def format_indian_spoken_number(num):
    try:
        is_negative = num < 0
        num = abs(num)
        
        if isinstance(num, float):
            integer_part = int(num)
            decimal_part = round(num - integer_part, 2)
        else:
            integer_part = int(num)
            decimal_part = 0.0

        if integer_part < 1000:
            res = str(integer_part)
        else:
            res = ""
            if integer_part >= 10000000:
                crores = integer_part // 10000000
                res += f"{crores} crore "
                integer_part %= 10000000
            if integer_part >= 100000:
                lakhs = integer_part // 100000
                res += f"{lakhs} lakh "
                integer_part %= 100000
            if integer_part >= 1000:
                thousands = integer_part // 1000
                res += f"{thousands} thousand "
                integer_part %= 1000
            if integer_part > 0:
                res += f"{integer_part}"
        
        res = res.strip()
        if decimal_part > 0:
            res += f" point {str(decimal_part).split('.')[1]}"
            
        if is_negative:
            res = "minus " + res
            
        return res
    except:
        return str(num)

def get_company_name(sym):
    aliases = STOCK_ALIASES.get(sym, [])
    if aliases:
        return aliases[0].title()
    return sym

def handle_invested(cmd, base_dir, initial_prices):
    json_path = os.path.join(base_dir, "data", "dashboard_data.json")
    invested = 0
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                dash_data = json.load(f)
                for t in dash_data.get("trades", []):
                    if t.get("Status") == "OPEN":
                        invested += t.get("Cost_Basis", 0)
        except Exception: pass
    return f"Your total invested amount is {format_indian_spoken_number(invested)} Rupees.", []

def handle_total_return(cmd, base_dir, initial_prices):
    json_path = os.path.join(base_dir, "data", "dashboard_data.json")
    total_pnl = 0
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                dash_data = json.load(f)
                market_data = dash_data.get("market_data", {})
                for t in dash_data.get("trades", []):
                    if t.get("Status") == "OPEN":
                        sym = t.get("Stock")
                        shares = t.get("Shares", 0)
                        cost = t.get("Cost_Basis", 0)
                        live_p = market_data.get(sym, t.get("Entry_Price", 0))
                        curr_val = shares * live_p
                        total_pnl += (curr_val - cost)
        except Exception: pass
    
    updown = "up" if total_pnl >= 0 else "down"
    return f"Your total returns are {updown} by {format_indian_spoken_number(total_pnl)} Rupees.", []

def handle_status(cmd, base_dir, initial_prices):
    json_path = os.path.join(base_dir, "data", "dashboard_data.json")
    total_val = 0
    total_pnl = 0
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                dash_data = json.load(f)
                market_data = dash_data.get("market_data", {})
                for t in dash_data.get("trades", []):
                    if t.get("Status") == "OPEN":
                        sym = t.get("Stock")
                        shares = t.get("Shares", 0)
                        cost = t.get("Cost_Basis", 0)
                        live_p = market_data.get(sym, t.get("Entry_Price", 0))
                        curr_val = shares * live_p
                        total_val += curr_val
                        total_pnl += (curr_val - cost)
        except Exception: pass
    
    updown = "up" if total_pnl >= 0 else "down"
    return f"Your portfolio is at {format_indian_spoken_number(total_val)} Rupees. You're {updown} by {format_indian_spoken_number(total_pnl)} Rupees.", []

def handle_day_return(cmd, base_dir, initial_prices):
    json_path = os.path.join(base_dir, "data", "dashboard_data.json")
    day_pnl = 0
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                dash_data = json.load(f)
                prev_closes = dash_data.get("prevClosePrices", {})
                market_data = dash_data.get("market_data", {})
                for t in dash_data.get("trades", []):
                    if t.get("Status") == "OPEN":
                        sym = t.get("Stock")
                        shares = t.get("Shares", 0)
                        live_p = market_data.get(sym, t.get("Entry_Price", 0))
                        prev_c = prev_closes.get(sym, live_p)
                        if isinstance(prev_c, dict): prev_c = prev_c.get("prev_close", live_p)
                        day_pnl += (live_p - prev_c) * shares
        except Exception: pass
    updown = "up" if day_pnl >= 0 else "down"
    return f"Your day returns are {updown} by {format_indian_spoken_number(day_pnl)} Rupees.", []

def handle_gainer(cmd, base_dir, initial_prices):
    json_path = os.path.join(base_dir, "data", "dashboard_data.json")
    gainers = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                dash_data = json.load(f)
                prev_closes = dash_data.get("prevClosePrices", {})
                market_data = dash_data.get("market_data", {})
                for sym, pc in prev_closes.items():
                    if isinstance(pc, dict): pc = pc.get("prev_close", 0)
                    live_p = market_data.get(sym, pc)
                    if pc > 0:
                        pct = ((live_p - pc) / pc) * 100
                        if pct > 0:
                            gainers.append((sym, pct))
                gainers.sort(key=lambda x: x[1], reverse=True)
        except Exception: pass
    if gainers:
        response_text = f"Your top gainer today is {get_company_name(gainers[0][0])} up by {gainers[0][1]:.2f} percent."
        if len(gainers) > 1:
            response_text += f" Followed by {get_company_name(gainers[1][0])} up by {gainers[1][1]:.2f} percent."
        return response_text, []
    return "You don't have any top gainers today.", []

def handle_loser(cmd, base_dir, initial_prices):
    json_path = os.path.join(base_dir, "data", "dashboard_data.json")
    losers = []
    if os.path.exists(json_path):
        try:
            with open(json_path, 'r') as f:
                dash_data = json.load(f)
                prev_closes = dash_data.get("prevClosePrices", {})
                market_data = dash_data.get("market_data", {})
                for sym, pc in prev_closes.items():
                    if isinstance(pc, dict): pc = pc.get("prev_close", 0)
                    live_p = market_data.get(sym, pc)
                    if pc > 0:
                        pct = ((live_p - pc) / pc) * 100
                        if pct < 0:
                            losers.append((sym, pct))
                losers.sort(key=lambda x: x[1])
        except Exception: pass
    if losers:
        response_text = f"Your top loser today is {get_company_name(losers[0][0])} down by {abs(losers[0][1]):.2f} percent."
        if len(losers) > 1:
            response_text += f" Followed by {get_company_name(losers[1][0])} down by {abs(losers[1][1]):.2f} percent."
        return response_text, []
    return "You don't have any top losers today.", []

def handle_market_status(cmd, base_dir, initial_prices):
    now = datetime.datetime.now()
    status = get_market_status(now)
    holiday = get_holiday_name(now)
    if status == "OPEN":
        response_text = "The market is currently open for active trading."
    elif status == "PRE_MARKET":
        response_text = "The market is in the pre-market session. Regular trading begins at 9:15 AM."
    elif status == "POST_MARKET":
        response_text = "The market is in the post-market session. Regular trading has concluded for the day."
    elif status == "HOLIDAY":
        next_day = get_next_trading_day(now)
        response_text = f"The market is closed today on account of {holiday}. It will reopen at 9:15 AM on {next_day.strftime('%B %d')}."
    elif status == "WEEKEND":
        next_day = get_next_trading_day(now)
        response_text = f"The market is closed for the weekend. It will reopen at 9:15 AM on {next_day.strftime('%B %d')}."
    else:
        next_day = get_next_trading_day(now)
        response_text = f"The market is currently closed. It will open at 9:15 AM on {next_day.strftime('%B %d')}."
    return response_text, []

def handle_sort_watchlist(cmd, base_dir, initial_prices):
    key = "percentChange"
    if "name" in cmd or "company" in cmd: key = "name"
    elif "price" in cmd: key = "price"
    
    direction = "desc"
    if "ascending" in cmd or "bottom" in cmd or "lowest" in cmd: direction = "asc"
    
    key_name = "day change"
    if key == "name": key_name = "company name"
    elif key == "price": key_name = "market price"
    
    dir_name = "descending order"
    if direction == "asc": dir_name = "ascending order"
    
    response_text = f"Sorted your watchlist by {key_name} in {dir_name}."
    return response_text, [{"type": "HERMES_SORT_WATCHLIST", "key": key, "direction": direction}]

def handle_balance(cmd, base_dir, initial_prices):
    import pandas as pd
    csv_path = os.path.join(base_dir, "data", "paper_trade_logs.csv")
    balance = 1000000.0
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            for _, row in df.iterrows():
                if row['Status'] == 'OPEN':
                    balance -= float(row['Cost_Basis'])
                elif row['Status'] == 'CLOSED':
                    balance += float(row['PnL_Amount'])
        except: pass
    return f"Your current available cash balance is {format_indian_spoken_number(balance)} Rupees.", []

def handle_nifty(cmd, base_dir, initial_prices):
    val = initial_prices.get("NIFTY", {}).get("ltp", 0)
    c = initial_prices.get("NIFTY", {}).get("close", 0)
    if val and c:
        dc = val - c
        dcp = (dc/c)*100
        direction = "up" if dc >= 0 else "down"
        return f"The Nifty 50 is currently trading at {val:,.0f}, {direction} {abs(dcp):.2f} percent for the day.", []
    return "I don't have the live Nifty price available at the moment, sir.", []

def handle_sensex(cmd, base_dir, initial_prices):
    val = initial_prices.get("SENSEX", {}).get("ltp", 0)
    c = initial_prices.get("SENSEX", {}).get("close", 0)
    if val and c:
        dc = val - c
        dcp = (dc/c)*100
        direction = "up" if dc >= 0 else "down"
        return f"The Sensex is currently trading at {val:,.0f}, {direction} {abs(dcp):.2f} percent for the day.", []
    return "I don't have the live Sensex price available at the moment, sir.", []

def handle_pnl(cmd, base_dir, initial_prices):
    import pandas as pd
    csv_path = os.path.join(base_dir, "data", "paper_trade_logs.csv")
    total_pnl = 0.0
    if os.path.exists(csv_path):
        try:
            df = pd.read_csv(csv_path)
            closed = df[df['Status'] == 'CLOSED']
            total_pnl = closed['PnL_Amount'].sum()
        except: pass
    direction = "profit" if total_pnl >= 0 else "loss"
    return f"Sir, your total realized {direction} is {format_indian_spoken_number(abs(total_pnl))} Rupees.", []

def handle_price_of(cmd, base_dir, initial_prices):
    stock_match = re.search(r"price(?: of)? ([a-z\s]+)", cmd)
    if stock_match:
        raw_stock = stock_match.group(1).strip()
        found_sym = None
        
        # Check aliases first for company names
        for sym, aliases in STOCK_ALIASES.items():
            for alias in aliases:
                if alias in raw_stock or raw_stock in alias:
                    found_sym = sym
                    break
            if found_sym:
                break
                
        # Fallback to direct ticker check
        if not found_sym:
            for sym in TOKEN_TO_STOCK.values():
                if sym.lower() in raw_stock or raw_stock in sym.lower():
                    found_sym = sym
                    break
        
        if found_sym:
            val = initial_prices.get(found_sym, {}).get("ltp", 0)
            if not val:
                # Fallback to dashboard data if market is closed or live feed is absent
                json_path = os.path.join(base_dir, "data", "dashboard_data.json")
                if os.path.exists(json_path):
                    try:
                        import json
                        with open(json_path, 'r') as f:
                            dash_data = json.load(f)
                            val = dash_data.get("market_data", {}).get(found_sym, 0)
                    except: pass
            
            company_name = get_company_name(found_sym)
            if val:
                return f"The market price of {company_name} is {val:,.2f} Rupees.", []
            else:
                return f"I am tracking {company_name}, but I do not have a live price yet.", []
    return "", []

# Define the Sitemap
HERMES_SITEMAP = {
    "Global": [
        {
            "id": "greeting",
            "match": lambda cmd: cmd.strip() in ["hii", "hi", "hello", "hey", "hey hermes", "hello hermes"],
            "response": lambda cmd: "Hello there! I'm Hermes, your personal trading assistant. How can I help you dominate the markets today?",
            "actions": []
        },
        {
            "id": "close_notifications",
            "match": lambda cmd: "close" in cmd and "notification" in cmd,
            "response": lambda cmd: "Closed notifications.",
            "actions": [{"type": "HERMES_UI_NOTIFICATIONS_CLOSE"}]
        },
        {
            "id": "open_notifications",
            "match": lambda cmd: "open" in cmd and "notification" in cmd,
            "response": lambda cmd: "Opened notifications.",
            "actions": [{"type": "HERMES_UI_NOTIFICATIONS_OPEN"}]
        },
        {
            "id": "toggle_notifications",
            "match": lambda cmd: "notification" in cmd,
            "response": lambda cmd: "Toggled notifications.",
            "actions": [{"type": "HERMES_UI_NOTIFICATIONS"}]
        },
        {
            "id": "close_console",
            "match": lambda cmd: "close" in cmd and ("terminal" in cmd or "console" in cmd or "logs" in cmd),
            "response": lambda cmd: "Closed the console.",
            "actions": [{"type": "HERMES_UI_CONSOLE_CLOSE"}]
        },
        {
            "id": "open_console",
            "match": lambda cmd: "open" in cmd and ("terminal" in cmd or "console" in cmd or "logs" in cmd),
            "response": lambda cmd: "Opened the console.",
            "actions": [{"type": "HERMES_UI_CONSOLE_OPEN"}]
        },
        {
            "id": "toggle_console",
            "match": lambda cmd: "terminal" in cmd or "console" in cmd or "logs" in cmd,
            "response": lambda cmd: "Toggled the console.",
            "actions": [{"type": "HERMES_UI_CONSOLE"}]
        },
        # Tab Navigation
        {
            "id": "tab_explore",
            "match": lambda cmd: any(x in cmd for x in ["open", "show", "switch", "go"]) and "explore" in cmd,
            "response": lambda cmd: "Switched to the Explore tab.",
            "actions": [{"type": "HERMES_UI_TAB", "tab": "Explore"}]
        },
        {
            "id": "tab_holdings",
            "match": lambda cmd: any(x in cmd for x in ["open", "show", "switch", "go"]) and ("holdings" in cmd or "portfolio" in cmd),
            "response": lambda cmd: "Switched to your Holdings.",
            "actions": [{"type": "HERMES_UI_TAB", "tab": "Portfolio"}]
        },
        {
            "id": "tab_positions",
            "match": lambda cmd: any(x in cmd for x in ["open", "show", "switch", "go"]) and ("positions" in cmd or "trades" in cmd),
            "response": lambda cmd: "Switched to your Positions.",
            "actions": [{"type": "HERMES_UI_TAB", "tab": "Trades"}]
        },
        {
            "id": "tab_pnl",
            "match": lambda cmd: any(x in cmd for x in ["open", "show", "switch", "go"]) and ("stocks" in cmd or "p & l" in cmd or "pnl tab" in cmd),
            "response": lambda cmd: "Switched to the Stocks P&L tab.",
            "actions": [{"type": "HERMES_UI_TAB", "tab": "Stocks P&L"}]
        },
        {
            "id": "tab_dashboard",
            "match": lambda cmd: any(x in cmd for x in ["open", "show", "switch", "go"]) and "dashboard" in cmd,
            "response": lambda cmd: "Switched to the Dashboard.",
            "actions": [{"type": "HERMES_UI_TAB", "tab": "Dashboard"}]
        },
        {
            "id": "tab_config",
            "match": lambda cmd: any(x in cmd for x in ["open", "show", "switch", "go"]) and ("config" in cmd or "settings" in cmd),
            "response": lambda cmd: "Switched to Configuration.",
            "actions": [{"type": "HERMES_UI_TAB", "tab": "Config"}]
        },
        {
            "id": "tab_docs",
            "match": lambda cmd: any(x in cmd for x in ["open", "show", "switch", "go"]) and ("docs" in cmd or "documentation" in cmd),
            "response": lambda cmd: "Switched to Documentation.",
            "actions": [{"type": "HERMES_UI_TAB", "tab": "Docs"}]
        },
        # Global Data Checks
        {
            "id": "invested_amount",
            "match": lambda cmd: "invested" in cmd or "investment" in cmd,
            "handler": handle_invested
        },
        {
            "id": "total_return",
            "match": lambda cmd: "total return" in cmd or "overall return" in cmd,
            "handler": handle_total_return
        },
        {
            "id": "portfolio_status",
            "match": lambda cmd: "status" in cmd or "report" in cmd or "current value" in cmd or "portfolio value" in cmd,
            "handler": handle_status
        },
        {
            "id": "day_return",
            "match": lambda cmd: "day return" in cmd or "today's return" in cmd or "one day return" in cmd,
            "handler": handle_day_return
        },
        {
            "id": "top_gainer",
            "match": lambda cmd: "gainer" in cmd,
            "handler": handle_gainer
        },
        {
            "id": "top_loser",
            "match": lambda cmd: "loser" in cmd,
            "handler": handle_loser
        },
        {
            "id": "market_status",
            "match": lambda cmd: any(x in cmd for x in ["market status", "is the market open", "when will market open", "when will the market open"]),
            "handler": handle_market_status
        },
        {
            "id": "cash_balance",
            "match": lambda cmd: any(x in cmd for x in ["balance", "funds", "money", "cash"]),
            "handler": handle_balance
        },
        {
            "id": "nifty_price",
            "match": lambda cmd: "nifty" in cmd,
            "handler": handle_nifty
        },
        {
            "id": "sensex_price",
            "match": lambda cmd: "sensex" in cmd,
            "handler": handle_sensex
        },
        {
            "id": "realized_pnl",
            "match": lambda cmd: "pnl" in cmd or "profit" in cmd or "loss" in cmd,
            "handler": handle_pnl
        },
        {
            "id": "price_of_stock",
            "match": lambda cmd: "price of" in cmd or "price" in cmd,
            "handler": handle_price_of
        }
    ],
    "Explore": [
        {
            "id": "sort_watchlist",
            "match": lambda cmd: any(x in cmd for x in ["start", "sort", "short", "spot"]) and "watchlist" in cmd,
            "handler": handle_sort_watchlist
        },
        {
            "id": "scroll_watchlist",
            "match": lambda cmd: any(x in cmd for x in ["show me my watchlist", "go to my watchlist", "show me the watchlist", "scroll to watchlist"]),
            "response": lambda cmd: "Opened your watchlist.",
            "actions": [
                {"type": "HERMES_UI_TAB", "tab": "Explore"},
                {"type": "HERMES_SCROLL_WATCHLIST", "delay": 0.2}
            ]
        }
    ],
    "Holdings": [],
    "Positions": [],
    "Stocks_PnL": [],
    "Dashboard": [],
    "Config": [],
    "Docs": []
}
