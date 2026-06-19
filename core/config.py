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
    "MTARTECH": "2709",
    "NETWEB": "17433",
    "POWERINDIA": "18457",
    "SCHNEIDER": "31234",
    "WAAREEENER": "25907",
    "INFY": "1594",
    "TRENT": "1964",
}

# Automatically derived lists and mappings
STOCKS = list(STOCK_TOKENS.keys())
TOKEN_TO_STOCK = {v: k for k, v in STOCK_TOKENS.items()}
