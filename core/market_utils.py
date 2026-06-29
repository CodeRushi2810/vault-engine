import datetime

# Hardcoded NSE Holidays for 2026 based on official circular
NSE_HOLIDAYS_2026 = {
    "2026-01-15": "Municipal Corporation Election",
    "2026-01-26": "Republic Day",
    "2026-03-03": "Holi",
    "2026-03-26": "Shri Ram Navami",
    "2026-03-31": "Shri Mahavir Jayanti",
    "2026-04-03": "Good Friday",
    "2026-04-14": "Dr. Baba Saheb Ambedkar Jayanti",
    "2026-05-01": "Maharashtra Day",
    "2026-05-28": "Bakri Id",
    "2026-06-26": "Muharram",
    "2026-09-14": "Ganesh Chaturthi",
    "2026-10-02": "Mahatma Gandhi Jayanti",
    "2026-10-20": "Dussehra",
    "2026-11-10": "Diwali-Balipratipada",
    "2026-11-24": "Prakash Gurpurb",
    "2026-12-25": "Christmas"
}

# Muhurat Trading is November 08, 2026 (Sunday). Special hours will apply.
# We will flag it as a special case if needed.
MUHURAT_TRADING_2026 = "2026-11-08"

def is_weekend(dt: datetime.datetime = None):
    if dt is None:
        dt = datetime.datetime.now()
    # 5 is Saturday, 6 is Sunday
    return dt.weekday() in [5, 6]

def get_holiday_name(dt: datetime.datetime = None):
    if dt is None:
        dt = datetime.datetime.now()
    date_str = dt.strftime("%Y-%m-%d")
    return NSE_HOLIDAYS_2026.get(date_str)

def is_market_open(dt: datetime.datetime = None):
    """
    Returns True if the given datetime is within market hours (09:15 to 15:30)
    on a normal trading day.
    """
    if dt is None:
        dt = datetime.datetime.now()
        
    if is_weekend(dt):
        return False
        
    if get_holiday_name(dt) is not None:
        return False
        
    start = dt.replace(hour=9, minute=15, second=0, microsecond=0)
    end = dt.replace(hour=15, minute=30, second=0, microsecond=0)
    
    return start <= dt <= end

def is_pre_market(dt: datetime.datetime = None):
    if dt is None:
        dt = datetime.datetime.now()
        
    if is_weekend(dt) or get_holiday_name(dt):
        return False
        
    start = dt.replace(hour=9, minute=0, second=0, microsecond=0)
    end = dt.replace(hour=9, minute=15, second=0, microsecond=0)
    
    return start <= dt < end

def is_post_market(dt: datetime.datetime = None):
    if dt is None:
        dt = datetime.datetime.now()
        
    if is_weekend(dt) or get_holiday_name(dt):
        return False
        
    start = dt.replace(hour=15, minute=30, second=0, microsecond=0)
    end = dt.replace(hour=16, minute=0, second=0, microsecond=0)
    
    return start < dt <= end

def get_market_status(dt: datetime.datetime = None):
    """
    Returns the string representation of the market status:
    'OPEN', 'CLOSED', 'HOLIDAY', 'WEEKEND', 'PRE_MARKET', or 'POST_MARKET'
    """
    if dt is None:
        dt = datetime.datetime.now()
        
    holiday = get_holiday_name(dt)
    if holiday:
        return "HOLIDAY"
        
    if is_weekend(dt):
        return "WEEKEND"
        
    if is_pre_market(dt):
        return "PRE_MARKET"
        
    if is_market_open(dt):
        return "OPEN"
        
    if is_post_market(dt):
        return "POST_MARKET"
        
    return "CLOSED"

def get_next_trading_day(dt: datetime.datetime = None):
    if dt is None:
        dt = datetime.datetime.now()
    next_day = dt + datetime.timedelta(days=1)
    while get_holiday_name(next_day) or is_weekend(next_day):
        next_day += datetime.timedelta(days=1)
    return next_day
