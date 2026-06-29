# Centralized configuration for the Vault Trading Engine

# Master dictionary mapping stock symbols to Groww instrument tokens.
# To add a new stock, simply add its symbol and token here.
STOCK_TOKENS = {
    "GVT&D": "16783",
    "JUBLFOOD": "18096",
    "SBIN": "3045",
    "ANANTRAJ": "13620",
    "BBOX": "3435",
    "CGPOWER": "760",
    "EICHERMOT": "910",
    "HFCL": "21951",
    "JBMA": "11655",
    "MTARTECH": "2715",
    "NETWEB": "17433",
    "POWERINDIA": "18457",
    "SCHNEIDER": "31234",
    "WAAREEENER": "25907",
    "INFY": "1594",
    "TRENT": "1964",
    "MOSCHIP": "29459",
    "TATAPOWER": "3426",
    "TATAELXSI": "3411",
    "LT": "11483",
    "KAYNES": "12092",
    "CUMMINSIND": "1901",
    "SIEMENS": "3150",
    "ABB": "13",
    "AEROFLEX": "18268",
    "ENRIN": "756871",
}

# Automatically derived lists and mappings
STOCKS = list(STOCK_TOKENS.keys())
TOKEN_TO_STOCK = {v: k for k, v in STOCK_TOKENS.items()}
