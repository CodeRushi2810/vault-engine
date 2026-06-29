from growwapi import GrowwAPI
import os
from dotenv import load_dotenv
load_dotenv("C:/Vault/vault-cloud-edition/vault-engine/.env")
groww = GrowwAPI(GrowwAPI.get_access_token(api_key=os.getenv("GROWW_API_KEY"), secret=os.getenv("GROWW_API_SECRET")))
q = groww.get_quote("JUBLFOOD", "NSE", "CASH")
print(q.get('ohlc', {}).get('close'))
