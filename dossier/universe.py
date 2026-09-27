"""Who the dossier studies: the focus stock, its peer group and benchmarks.

Peer group approved by Rushi on 27 September 2026. Business similarity was
judged from general knowledge; co-movement was measured on daily returns net
of NIFTY (see `python -m dossier.run peers`).
"""

FOCUS = "NETWEB"

# Business and behaviour peers: pooled with NETWEB to enlarge the sample.
PEERS = [
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
]

# Tracked as a signal for the data-centre theme, not pooled as a business peer.
THEME = ["ANANTRAJ"]

EQUITIES = [FOCUS] + PEERS + THEME

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
