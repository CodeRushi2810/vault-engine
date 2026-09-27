"""Yahoo Finance: an independent cross-check, never the source of record.

Yahoo's `Close` (auto_adjust=False) is split-adjusted but not
dividend-adjusted, which matches how the NSE series is adjusted here.
Unofficial and for personal use; if it fails the dossier still builds.
"""
import pandas as pd


def fetch(symbols, start):
    import yfinance as yf

    tickers = [f"{s}.NS" for s in symbols]
    raw = yf.download(tickers, start=start, progress=False, auto_adjust=False,
                      group_by="ticker", threads=False)
    out = {}
    for s, t in zip(symbols, tickers):
        try:
            df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
        except KeyError:
            continue
        df = df[["Open", "High", "Low", "Close", "Volume"]].dropna(how="all")
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
        if len(df):
            out[s] = df
    return out
