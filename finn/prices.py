"""End-of-day price & volume via yfinance, plus configurable alert signals."""
import time

import pandas as pd

import config
from finn.storage import data_path

COLUMNS = ["Open", "High", "Low", "Close", "Volume"]


def _download(yahoo_symbol: str, period: str) -> pd.DataFrame:
    import yfinance as yf  # imported here so offline tests don't need it

    df = yf.Ticker(yahoo_symbol).history(period=period, interval="1d", auto_adjust=True)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[[c for c in COLUMNS if c in df.columns]].copy()
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.index.name = "Date"
    return df.dropna(subset=["Close"])


def fetch_prices(symbol: str, period: str = config.PRICE_HISTORY_PERIOD) -> pd.DataFrame:
    """Fetch EOD data for one NSE symbol, falling back to BSE (.BO). Saves a CSV."""
    for suffix in (".NS", ".BO"):
        try:
            df = _download(symbol + suffix, period)
        except Exception as exc:  # network errors, Yahoo hiccups
            print(f"  ! {symbol}{suffix}: {exc}")
            df = pd.DataFrame()
        if not df.empty:
            df.to_csv(data_path("prices", f"{symbol}.csv"))
            return df
    return pd.DataFrame()


def load_prices(symbol: str) -> pd.DataFrame:
    path = data_path("prices", f"{symbol}.csv")
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path, index_col="Date", parse_dates=True)


def fetch_all_prices(symbols, period: str = config.PRICE_HISTORY_PERIOD) -> dict:
    out = {}
    for sym in symbols:
        df = fetch_prices(sym, period)
        status = f"{len(df)} days, last {df.index[-1].date()}" if not df.empty else "FAILED"
        print(f"  {sym:<12} {status}")
        if not df.empty:
            out[sym] = df
        time.sleep(0.3)
    return out


def compute_signals(df: pd.DataFrame, rules: dict = None) -> pd.DataFrame:
    """Add daily % change and volume-vs-average columns, and flag alert days.

    The average excludes the current day (shift(1)), so a spike can't inflate
    its own baseline.
    """
    rules = {**config.ALERTS, **(rules or {})}
    out = df.sort_index().copy()
    out["change_pct"] = out["Close"].pct_change() * 100
    lookback = int(rules["volume_lookback_days"])
    out["avg_volume"] = out["Volume"].shift(1).rolling(lookback, min_periods=max(5, lookback // 2)).mean()
    out["volume_ratio"] = out["Volume"] / out["avg_volume"]
    out["volume_alert"] = out["volume_ratio"] >= rules["volume_multiple"]
    out["price_alert"] = out["change_pct"].abs() >= rules["price_move_pct"]
    return out


def scan_alerts(symbol: str, df: pd.DataFrame, last_n_days: int = 1, rules: dict = None) -> list:
    """Alerts in the last N trading days, newest first, as plain dicts."""
    sig = compute_signals(df, rules)
    recent = sig.tail(last_n_days)
    alerts = []
    for date, row in recent[recent["volume_alert"] | recent["price_alert"]].iterrows():
        reasons = []
        if row["price_alert"]:
            reasons.append(f"price {row['change_pct']:+.1f}%")
        if row["volume_alert"]:
            reasons.append(f"volume {row['volume_ratio']:.1f}x avg")
        alerts.append({
            "symbol": symbol,
            "date": pd.Timestamp(date).date().isoformat(),
            "close": round(float(row["Close"]), 2),
            "change_pct": round(float(row["change_pct"]), 2),
            "volume": int(row["Volume"]),
            "volume_ratio": round(float(row["volume_ratio"]), 2) if pd.notna(row["volume_ratio"]) else None,
            "reasons": reasons,
        })
    return sorted(alerts, key=lambda a: a["date"], reverse=True)
