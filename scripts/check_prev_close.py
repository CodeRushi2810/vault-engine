from growwapi import GrowwAPI
import os
import sys
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(BASE_DIR)

from core.auth import get_groww_token
groww = GrowwAPI(get_groww_token())
q = groww.get_quote("JUBLFOOD", "NSE", "CASH")
print(q.get('ohlc', {}).get('close'))
