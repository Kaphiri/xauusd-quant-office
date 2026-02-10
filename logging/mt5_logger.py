"""
=============================================================================
  XAUUSD PROFESSIONAL QUANT DATA LOGGER
  Version : 2.0.0
  Author  : XAUUSD Quant Office
=============================================================================

  PURPOSE
  -------
  Permanent, dedicated tick-level data logger for XAUUSD via MetaTrader 5.
  Designed to run indefinitely on a dedicated Windows machine. Once running,
  all data required for professional quantitative research is captured —
  you will never need to re-log.

  DATA CAPTURED
  -------------
  1. RAW TICKS          — every bid/ask change, millisecond-stamped
                          with derived fields (mid, spread_pct, imbalance,
                          session tag, flag decode, day_of_week, hour_utc)

  2. OHLCV BARS         — M1, M5, M15, M30, H1, H4, D1, W1, MN1
                          synced every 60 seconds, no gaps

  3. DOM SNAPSHOTS      — full order book depth every 5 seconds
                          (auto-disabled if broker does not support)

  4. SYMBOL METADATA    — contract specs logged hourly
                          (tick size, margin, swap rates, digits, etc.)

  5. SESSION LOG        — timestamped record of every session transition
                          (Asia / London / NewYork / LondonNY_Overlap)

  6. HEARTBEAT LOG      — system uptime, file sizes, tick counts every 10s

  OUTPUT STRUCTURE
  ----------------
  data/
    ticks/XAUUSD/
      xauusd_ticks_raw.csv
      state.json
    ohlcv/XAUUSD/
      M1.csv  M5.csv  M15.csv  M30.csv
      H1.csv  H4.csv  D1.csv   W1.csv  MN1.csv
    dom/XAUUSD/
      dom_snapshots.csv
    metadata/
      symbol_info.csv
      session_log.csv
      heartbeat.csv

  TICK CSV COLUMNS
  ----------------
  time_msc, time_dt, bid, ask, last, volume, volume_real,
  flags, flag_desc, spread, spread_pct, mid, bid_ask_imbalance,
  session, day_of_week, hour_utc

  OHLCV CSV COLUMNS
  -----------------
  time, time_dt, open, high, low, close, tick_volume, real_volume, spread

  DOM CSV COLUMNS
  ---------------
  time_msc, time_dt, type (BID/ASK), price, volume

=============================================================================
"""

import MetaTrader5 as mt5
import pandas as pd
import time
import json
from pathlib import Path
from datetime import datetime, timezone

# ─────────────────────────────────────────────────────────────────────────────
#  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

SYMBOL          = "XAUUSD"
TICK_BATCH      = 1000       # ticks fetched per MT5 call
LOOP_SLEEP      = 0.25       # seconds between tick fetch cycles
HEARTBEAT_SEC   = 10         # console + CSV heartbeat interval (seconds)
OHLCV_SYNC_SEC  = 60         # sync OHLCV bars every N seconds
DOM_SNAP_SEC    = 5          # DOM order book snapshot every N seconds
META_LOG_SEC    = 3600       # re-log symbol metadata every hour
MAX_FAILS       = 5          # consecutive failures before timestamp reset

TIMEFRAMES = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
    "W1":  mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}

OHLCV_LOOKBACK = {
    "M1": 500, "M5": 500, "M15": 500, "M30": 500,
    "H1": 500, "H4": 500, "D1": 500, "W1": 200, "MN1": 100,
}

# ─────────────────────────────────────────────────────────────────────────────
#  DIRECTORY SETUP
# ─────────────────────────────────────────────────────────────────────────────

BASE      = Path(__file__).parent.parent / "data"
TICK_DIR  = BASE / "ticks"  / SYMBOL
OHLCV_DIR = BASE / "ohlcv"  / SYMBOL
DOM_DIR   = BASE / "dom"    / SYMBOL
META_DIR  = BASE / "metadata"

for _dir in [TICK_DIR, OHLCV_DIR, DOM_DIR, META_DIR]:
    _dir.mkdir(parents=True, exist_ok=True)

TICK_CSV      = TICK_DIR  / "xauusd_ticks_raw.csv"
STATE_FILE    = TICK_DIR  / "state.json"
DOM_CSV       = DOM_DIR   / "dom_snapshots.csv"
META_CSV      = META_DIR  / "symbol_info.csv"
SESSION_CSV   = META_DIR  / "session_log.csv"
HEARTBEAT_CSV = META_DIR  / "heartbeat.csv"

# ─────────────────────────────────────────────────────────────────────────────
#  UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def log(msg: str):
    print(f"[{now_utc().isoformat()}] {msg}", flush=True)

def msc_to_dt(time_msc: int) -> datetime:
    return datetime.fromtimestamp(time_msc / 1000.0, tz=timezone.utc)

def get_session(dt: datetime) -> str:
    h = dt.hour + dt.minute / 60.0
    if 12 <= h < 16:
        return "LondonNY_Overlap"
    elif 7 <= h < 16:
        return "London"
    elif 12 <= h < 21:
        return "NewYork"
    else:
        return "Asia"

def flag_description(flags: int) -> str:
    parts = []
    if flags & 0x02: parts.append("BID")
    if flags & 0x04: parts.append("ASK")
    if flags & 0x08: parts.append("LAST")
    if flags & 0x10: parts.append("VOLUME")
    if flags & 0x20: parts.append("BUY")
    if flags & 0x40: parts.append("SELL")
    return "|".join(parts) if parts else "TICK"

def save_state(last_time_msc: int):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "last_time_msc": int(last_time_msc),
                "last_time_dt":  msc_to_dt(last_time_msc).isoformat(),
                "updated_at":    now_utc().isoformat(),
            }, f, indent=2)
    except Exception as e:
        log(f"[STATE] Failed to save state: {e}")

def load_state() -> int:
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        v = state.get("last_time_msc", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        v = 0
    now_msc = int(time.time() * 1000)
    if v <= 0 or v > now_msc:
        v = now_msc - 2000
    return v

# ─────────────────────────────────────────────────────────────────────────────
#  TICK PROCESSING & LOGGING
# ─────────────────────────────────────────────────────────────────────────────

TICK_COLUMNS = [
    "time_msc", "time_dt",
    "bid", "ask", "last",
    "volume", "volume_real",
    "flags", "flag_desc",
    "spread", "spread_pct", "mid", "bid_ask_imbalance",
    "session", "day_of_week", "hour_utc",
]

def process_ticks(ticks_raw) -> pd.DataFrame:
    df = pd.DataFrame(ticks_raw)

    if "volume_real" not in df.columns:
        df["volume_real"] = 0.0

    # Derived price fields
    df["time_dt"]           = df["time_msc"].apply(lambda x: msc_to_dt(x).isoformat())
    df["spread_pct"]        = ((df["ask"] - df["bid"]) / df["bid"] * 100).round(6)
    df["mid"]               = ((df["bid"] + df["ask"]) / 2).round(5)
    df["bid_ask_imbalance"] = (df["bid"] / df["ask"]).round(6)
    df["flag_desc"]         = df["flags"].apply(flag_description)

    # Time metadata
    dts                 = pd.to_datetime(df["time_msc"], unit="ms", utc=True)
    df["session"]       = dts.apply(lambda x: get_session(x))
    df["day_of_week"]   = dts.dt.day_name()
    df["hour_utc"]      = dts.dt.hour

    return df[[c for c in TICK_COLUMNS if c in df.columns]]

def append_ticks(df: pd.DataFrame):
    if df is None or len(df) == 0:
        return
    write_header = not TICK_CSV.exists()
    df.to_csv(TICK_CSV, mode="a", index=False, header=write_header)

# ─────────────────────────────────────────────────────────────────────────────
#  OHLCV BAR LOGGING
# ─────────────────────────────────────────────────────────────────────────────

OHLCV_COLUMNS = [
    "time", "time_dt", "open", "high", "low", "close",
    "tick_volume", "real_volume", "spread",
]

ohlcv_last_bar: dict = {tf: 0 for tf in TIMEFRAMES}

def sync_ohlcv(tf_name: str, tf_const: int):
    try:
        rates = mt5.copy_rates_from_pos(SYMBOL, tf_const, 0, OHLCV_LOOKBACK[tf_name])
        if rates is None or len(rates) == 0:
            return

        df = pd.DataFrame(rates)
        df["time_dt"] = (
            pd.to_datetime(df["time"], unit="s", utc=True)
            .dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        )
        if "real_volume" not in df.columns:
            df["real_volume"] = 0.0

        df       = df[[c for c in OHLCV_COLUMNS if c in df.columns]]
        new_df   = df[df["time"] > ohlcv_last_bar[tf_name]]
        if len(new_df) == 0:
            return

        csv_path     = OHLCV_DIR / f"{tf_name}.csv"
        write_header = not csv_path.exists()
        new_df.to_csv(csv_path, mode="a", index=False, header=write_header)
        ohlcv_last_bar[tf_name] = int(df["time"].max())

    except Exception as e:
        log(f"[OHLCV] Sync error ({tf_name}): {e}")

def sync_all_ohlcv():
    for tf_name, tf_const in TIMEFRAMES.items():
        sync_ohlcv(tf_name, tf_const)

# ─────────────────────────────────────────────────────────────────────────────
#  DOM (DEPTH OF MARKET) LOGGING
# ─────────────────────────────────────────────────────────────────────────────

DOM_COLUMNS   = ["time_msc", "time_dt", "type", "price", "volume"]
dom_supported = None  # auto-detected on first attempt

def snap_dom():
    global dom_supported
    if dom_supported is False:
        return
    try:
        mt5.market_book_add(SYMBOL)
        book = mt5.market_book_get(SYMBOL)

        if book is None or len(book) == 0:
            if dom_supported is None:
                log("[DOM] Not supported by this broker — DOM logging disabled")
                dom_supported = False
            return

        dom_supported = True
        t_msc = int(time.time() * 1000)
        t_dt  = msc_to_dt(t_msc).isoformat()

        rows = [{
            "time_msc": t_msc,
            "time_dt":  t_dt,
            "type":     "BID" if entry.type == mt5.BOOK_TYPE_BUY else "ASK",
            "price":    entry.price,
            "volume":   entry.volume,
        } for entry in book]

        if rows:
            df           = pd.DataFrame(rows)[DOM_COLUMNS]
            write_header = not DOM_CSV.exists()
            df.to_csv(DOM_CSV, mode="a", index=False, header=write_header)

    except Exception as e:
        log(f"[DOM] Snapshot error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  SYMBOL METADATA LOGGING
# ─────────────────────────────────────────────────────────────────────────────

META_FIELDS = [
    "name", "description", "currency_base", "currency_profit", "currency_margin",
    "digits", "point", "trade_tick_size", "trade_tick_value",
    "trade_contract_size", "volume_min", "volume_max", "volume_step",
    "spread", "spread_float", "swap_long", "swap_short",
    "trade_stops_level", "trade_freeze_level",
    "margin_initial", "margin_maintenance", "margin_hedged",
]

def log_metadata():
    try:
        info = mt5.symbol_info(SYMBOL)
        if info is None:
            return
        row = {"logged_at": now_utc().isoformat()}
        row.update({f: getattr(info, f, None) for f in META_FIELDS})
        write_header = not META_CSV.exists()
        pd.DataFrame([row]).to_csv(META_CSV, mode="a", index=False, header=write_header)
    except Exception as e:
        log(f"[META] Log error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  SESSION TRANSITION LOGGING
# ─────────────────────────────────────────────────────────────────────────────

_current_session: str = None

def check_session_change(dt: datetime):
    global _current_session
    sess = get_session(dt)
    if sess != _current_session:
        row = {
            "time_dt":  dt.isoformat(),
            "session":  sess,
            "prev":     _current_session,
            "weekday":  dt.strftime("%A"),
        }
        _current_session = sess
        write_header = not SESSION_CSV.exists()
        pd.DataFrame([row]).to_csv(SESSION_CSV, mode="a", index=False, header=write_header)
        log(f"[SESSION] {row['prev']} → {sess}")

# ─────────────────────────────────────────────────────────────────────────────
#  HEARTBEAT LOGGING
# ─────────────────────────────────────────────────────────────────────────────

def log_heartbeat(last_time_msc: int, ticks_batch: int, total_ticks: int):
    try:
        tick_mb  = TICK_CSV.stat().st_size  / 1024**2 if TICK_CSV.exists()  else 0.0
        ohlcv_mb = sum(f.stat().st_size for f in OHLCV_DIR.glob("*.csv")) / 1024**2
        dom_mb   = DOM_CSV.stat().st_size   / 1024**2 if DOM_CSV.exists()   else 0.0

        row = {
            "time_dt":       now_utc().isoformat(),
            "last_time_msc": last_time_msc,
            "last_tick_dt":  msc_to_dt(last_time_msc).isoformat(),
            "ticks_batch":   ticks_batch,
            "total_ticks":   total_ticks,
            "tick_mb":       round(tick_mb, 3),
            "ohlcv_mb":      round(ohlcv_mb, 3),
            "dom_mb":        round(dom_mb, 3),
            "session":       get_session(now_utc()),
        }
        write_header = not HEARTBEAT_CSV.exists()
        pd.DataFrame([row]).to_csv(HEARTBEAT_CSV, mode="a", index=False, header=write_header)

        log(
            f"[HEARTBEAT] batch={ticks_batch:>4}  total={total_ticks:>10,}  "
            f"tick={tick_mb:>7.2f}MB  ohlcv={ohlcv_mb:>6.2f}MB  "
            f"dom={dom_mb:>5.2f}MB  session={row['session']}"
        )
    except Exception as e:
        log(f"[HEARTBEAT] Log error: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  STARTUP
# ─────────────────────────────────────────────────────────────────────────────

log("=" * 70)
log("  XAUUSD PROFESSIONAL QUANT DATA LOGGER  v2.0.0")
log("=" * 70)
log(f"  Ticks     : {TICK_CSV}")
log(f"  OHLCV     : {OHLCV_DIR}")
log(f"  DOM       : {DOM_CSV}")
log(f"  Metadata  : {META_DIR}")
log("=" * 70)

if not mt5.initialize():
    raise RuntimeError(f"MT5 initialization failed: {mt5.last_error()}")
log("[INIT] MT5 connected successfully")

log_metadata()
log("[INIT] Symbol metadata logged")

log("[INIT] Syncing historical OHLCV bars for all timeframes...")
sync_all_ohlcv()
log("[INIT] OHLCV sync complete")

last_time_msc   = load_state()
last_heartbeat  = time.time()
last_ohlcv_sync = time.time()
last_dom_snap   = time.time()
last_meta_log   = time.time()
fail_count      = 0
total_ticks     = 0

log(f"[INIT] Resuming from {msc_to_dt(last_time_msc).isoformat()}")
log("[INIT] Logger is running. Press Ctrl+C to stop safely.")
log("=" * 70)

# ─────────────────────────────────────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

while True:
    try:
        now = time.time()

        # ── Periodic: OHLCV sync ─────────────────────────────────────────────
        if now - last_ohlcv_sync >= OHLCV_SYNC_SEC:
            sync_all_ohlcv()
            last_ohlcv_sync = now

        # ── Periodic: DOM snapshot ───────────────────────────────────────────
        if now - last_dom_snap >= DOM_SNAP_SEC:
            snap_dom()
            last_dom_snap = now

        # ── Periodic: Metadata re-log ────────────────────────────────────────
        if now - last_meta_log >= META_LOG_SEC:
            log_metadata()
            last_meta_log = now

        # ── Fetch ticks ──────────────────────────────────────────────────────
        ticks_raw = []
        try:
            from_dt   = msc_to_dt(last_time_msc)
            ticks_raw = mt5.copy_ticks_from(SYMBOL, from_dt, TICK_BATCH, mt5.COPY_TICKS_ALL)
            if ticks_raw is None:
                err = mt5.last_error()
                if err[0] not in (0, 1):
                    log(f"[TICKS] MT5 error: {err}")
                ticks_raw = []
            fail_count = 0

        except Exception as e:
            fail_count += 1
            log(f"[TICKS] copy_ticks_from attempt {fail_count}/{MAX_FAILS} failed: {e}")
            time.sleep(0.5)
            if fail_count >= MAX_FAILS:
                last_time_msc = int(time.time() * 1000) - 1000
                log(f"[TICKS] Timestamp reset after {MAX_FAILS} consecutive failures")
                fail_count = 0
            continue

        # ── Process & write ticks ────────────────────────────────────────────
        n = len(ticks_raw)
        if n > 0:
            new_last = int(ticks_raw["time_msc"].max())
            if new_last > last_time_msc:
                df            = process_ticks(ticks_raw)
                append_ticks(df)
                total_ticks  += len(df)
                last_time_msc = new_last + 1
                save_state(last_time_msc)
                check_session_change(msc_to_dt(new_last))

        # ── Heartbeat ────────────────────────────────────────────────────────
        if now - last_heartbeat >= HEARTBEAT_SEC:
            log_heartbeat(last_time_msc, n, total_ticks)
            last_heartbeat = now

        time.sleep(LOOP_SLEEP)

    except KeyboardInterrupt:
        log("[SHUTDOWN] Interrupt received. Saving state...")
        save_state(last_time_msc)
        mt5.shutdown()
        log("[SHUTDOWN] Logger stopped cleanly. State saved.")
        break

    except Exception as e:
        log(f"[ERROR] Outer loop exception: {e}")
        time.sleep(1)
