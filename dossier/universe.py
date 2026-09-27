"""Who the dossier studies: every focus stock, each with its own comparison group.

The engine works on one focus stock at a time. `use(symbol)` switches the
module-level FOCUS / PEERS / THEME that the rest of the engine reads, and
`python -m dossier.daily` runs the whole routine once per stock in STOCKS.

Comparison groups: business similarity judged from general knowledge, then
checked by co-movement on daily returns net of NIFTY (`python -m dossier.run
peers`). NETWEB's group approved by Rushi on 27 September 2026; MTARTECH's
chosen on 27 September 2026 the same way (business-similar AND moves with it).
"""

STOCKS = {
    "NETWEB": {
        "name": "Netweb Technologies India Limited",
        "peers": [
            "MOSCHIP",     # chip and system design (NSE-listed only from February 2025)
            "E2E",         # GPU cloud; buys the kind of servers Netweb builds
            "RPTECH",      # Rashi Peripherals, IT hardware distribution
            "AVALON",      # electronics contract manufacturing
            "SYRMA",       # electronics contract manufacturing
            "KAYNES",      # electronics contract manufacturing, chip packaging
            "HFCL",        # telecom equipment
            "TEJASNET",    # telecom and networking hardware
            "DATAPATTNS",  # defence electronic systems
            "ZENTEC",      # defence simulators and electronics
        ],
        "theme": ["ANANTRAJ"],   # data-centre theme gauge, not a business peer
    },
    "MTARTECH": {
        "name": "MTAR Technologies Limited",
        "peers": [
            "DATAPATTNS",  # defence electronic systems (co-movement 0.38)
            "MIDHANI",     # special alloys for defence, space and nuclear (0.34)
            "PARAS",       # defence and space optics and electronics (0.32)
            "AZAD",        # precision aerospace and energy components (0.29)
            "DCXINDIA",    # defence electronics manufacturing (0.26)
            "HAL",         # aircraft and aero-engines (0.25)
            "BEL",         # defence electronics (0.25)
            "ZENTEC",      # defence training systems (0.24)
            "ASTRAMICRO",  # radar and microwave electronics (0.23)
            "UNIMECH",     # precision aerospace parts; listed December 2024 (0.20)
        ],
        "theme": ["COCHINSHIP"],  # defence-theme gauge (shipbuilding), not a business peer
    },
}

# Every stock any focus needs; loaded together so the parsed-price cache stays valid.
EQUITIES = sorted({s for sym, p in STOCKS.items() for s in [sym] + p["peers"] + p["theme"]})

# The stock being worked on (switched by use()).
FOCUS = "NETWEB"
PEERS = STOCKS[FOCUS]["peers"]
THEME = STOCKS[FOCUS]["theme"]


def use(symbol):
    """Make `symbol` the focus stock for everything that runs next."""
    global FOCUS, PEERS, THEME
    symbol = symbol.upper()
    if symbol not in STOCKS:
        raise KeyError(f"{symbol} is not in dossier/universe.py STOCKS")
    FOCUS, PEERS, THEME = symbol, STOCKS[symbol]["peers"], STOCKS[symbol]["theme"]
    return symbol


# Panel column -> index name exactly as NSE's ind_close_all file spells it.
INDICES = {
    "NIFTY": "Nifty 50",
    "BROAD": "Nifty 500",
    "SECTOR_IT": "Nifty IT",
    "DIGITAL": "Nifty India Digital",
    "MANUFACTURING": "Nifty India Manufacturing",
    "MIDSMALL_IT_TELECOM": "Nifty MidSmall IT & Telecom",
    "MIDCAP": "Nifty Midcap 150",
    "SMALLCAP": "Nifty Smallcap 250",
    "VIX": "India VIX",
}

# First day of history to collect (a few weeks before NETWEB listed on
# 27 July 2023, so rolling windows on peers are warm by then).
HISTORY_START = "2023-07-01"
