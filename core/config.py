# Centralized configuration for the Vault Trading Engine

# Master dictionary mapping stock symbols to Groww instrument tokens.
# To add a new stock, simply add its symbol and token here.
STOCK_TOKENS = {
    "VOLTAS": "3718",
"GVT&D": "16783",
    "JUBLFOOD": "18096",
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

STOCK_ALIASES = {
    "GVT&D": ["GE Vernova T and D India", "gvtd", "ge t&d", "ge t and d", "gvt&d"],
    "JUBLFOOD": ["Jubilant Foodworks", "jubilant foodworks", "jubilant food", "jublfood"],
    "SBIN": ["State Bank of India", "state bank of india", "sbi", "sbin"],
    "ANANTRAJ": ["Anant Raj", "anant raj", "anantraj"],
    "BBOX": ["Black Box", "black box", "bbox"],
    "CGPOWER": ["CG Power", "cg power", "cgpower"],
    "EICHERMOT": ["Eicher Motors", "eicher motors", "eichermot"],
    "HFCL": ["HFCL", "hfcl"],
    "JBMA": ["JBM Auto", "jbm auto", "jbma"],
    "MTARTECH": ["MTAR Technologies", "mtar technologies", "mtar tech", "mtartech"],
    "NETWEB": ["Netweb Technologies", "netweb technologies", "netweb"],
    "POWERINDIA": ["Hitachi Energy", "hitachi energy", "powerindia", "power india"],
    "SCHNEIDER": ["Schneider Electric", "schneider electric", "schneider"],
    "WAAREEENER": ["Waaree Energies", "waaree energies", "waaree", "waareeener"],
    "INFY": ["Infosys", "infosys", "infy"],
    "TRENT": ["Trent", "trent"],
    "MOSCHIP": ["Moschip Technologies", "moschip technologies", "moschip"],
    "TATAPOWER": ["Tata Power", "tata power", "tatapower"],
    "TATAELXSI": ["Tata Elxsi", "tata elxsi", "tataelxsi"],
    "LT": ["Larsen and Toubro", "larsen and toubro", "l&t", "l and t", "lt"],
    "KAYNES": ["Kaynes Technology", "kaynes technology", "kaynes"],
    "CUMMINSIND": ["Cummins India", "cummins india", "cummins", "cumminsind"],
    "SIEMENS": ["Siemens", "siemens"],
    "ABB": ["ABB India", "abb india", "abb"],
    "AEROFLEX": ["Aeroflex Industries", "aeroflex industries", "aeroflex"],
    "ENRIN": ["Siemens Energy India", "Siemens Energy", "siemens energy", "enrin"],
}
