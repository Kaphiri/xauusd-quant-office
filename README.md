# XAUUSD Quant Office — Professional Data Logger

A permanent, dedicated data logging system for XAUUSD via MetaTrader 5.
Captures every piece of market data needed for professional quantitative research.
Once running, you will **never need to re-log**.

---

## System Requirements

| Component | Requirement |
|-----------|-------------|
| OS | Windows 10/11 (64-bit) |
| Python | 3.11 (64-bit) |
| MetaTrader 5 | Installed and logged in to a broker |
| Broker | Must provide XAUUSD with tick data access |

---

## Repository Structure

```
C:\quant\xauusd-quant-office\
├── logging\
│   └── mt5_logger.py            # Main data logger (never edit while running)
├── system_controller.ps1        # Watchdog: monitors and restarts logger
├── setup_scheduled_task.ps1     # Run once as Admin to enable auto-start on boot
├── requirements.txt             # Python dependencies
├── .gitignore                   # Excludes all data files from git
└── README.md                    # This file
```

> ⚠️ The `data/` folder is **never committed to git**. All raw data stays on disk only.

---

## Data Output Structure

```
data/
├── ticks/XAUUSD/
│   ├── xauusd_ticks_raw.csv     ← Every tick, forever
│   └── state.json               ← Resume pointer (do not delete)
├── ohlcv/XAUUSD/
│   ├── M1.csv
│   ├── M5.csv
│   ├── M15.csv
│   ├── M30.csv
│   ├── H1.csv
│   ├── H4.csv
│   ├── D1.csv
│   ├── W1.csv
│   └── MN1.csv
├── dom/XAUUSD/
│   └── dom_snapshots.csv        ← Order book depth (if broker supports)
└── metadata/
    ├── symbol_info.csv          ← Contract specs, logged hourly
    ├── session_log.csv          ← Session transition log
    └── heartbeat.csv            ← System uptime and health log
```

---

## What Is Logged

### Ticks (`xauusd_ticks_raw.csv`)
Every market tick with millisecond precision.

| Column | Description |
|--------|-------------|
| `time_msc` | Timestamp in milliseconds (Unix) |
| `time_dt` | ISO 8601 UTC datetime string |
| `bid` | Bid price |
| `ask` | Ask price |
| `last` | Last traded price |
| `volume` | Tick volume |
| `volume_real` | Real volume (if available) |
| `flags` | Raw MT5 tick flags (integer) |
| `flag_desc` | Decoded flags (BID/ASK/LAST/BUY/SELL) |
| `spread` | Raw spread in points |
| `spread_pct` | Spread as % of bid price |
| `mid` | Mid price `(bid + ask) / 2` |
| `bid_ask_imbalance` | `bid / ask` ratio |
| `session` | Asia / London / NewYork / LondonNY_Overlap |
| `day_of_week` | Monday–Friday |
| `hour_utc` | UTC hour (0–23) |

### OHLCV Bars (`M1.csv` … `MN1.csv`)

| Column | Description |
|--------|-------------|
| `time` | Bar open time (Unix seconds) |
| `time_dt` | ISO 8601 UTC datetime string |
| `open / high / low / close` | Price levels |
| `tick_volume` | Number of ticks in bar |
| `real_volume` | Real traded volume (if available) |
| `spread` | Average spread during bar |

### DOM Snapshots (`dom_snapshots.csv`)
Full order book snapshot every 5 seconds (if supported by broker).

| Column | Description |
|--------|-------------|
| `time_msc` | Snapshot timestamp (ms) |
| `time_dt` | ISO 8601 UTC |
| `type` | BID or ASK |
| `price` | Price level |
| `volume` | Volume at that level |

### Symbol Metadata (`symbol_info.csv`)
Contract specifications re-logged every hour: tick size, tick value,
contract size, margin, swap rates, spread float flag, digits, etc.

### Session Log (`session_log.csv`)
Every session transition stamped with time, session name, previous session, weekday.

### Heartbeat Log (`heartbeat.csv`)
Every 10 seconds: tick file size, OHLCV size, DOM size, total ticks logged,
last tick timestamp, current session.

---

## Installation

### 1. Install Python 3.11

Download from: https://www.python.org/downloads/release/python-3119/

During install: ✅ check **"Add python.exe to PATH"**

### 2. Install dependencies

```powershell
py -3.11 -m pip install -r requirements.txt
```

### 3. Set up auto-start on boot (run once as Administrator)

```powershell
# Right-click PowerShell > Run as administrator
cd C:\quant\xauusd-quant-office
.\setup_scheduled_task.ps1
```

---

## Running the Logger

**Manually (for testing):**
```powershell
py -3.11 "C:\quant\xauusd-quant-office\logging\mt5_logger.py"
```

**Via controller (recommended):**
```powershell
py -3.11 "C:\quant\xauusd-quant-office\system_controller.ps1"
```

**Start the scheduled task immediately (no reboot needed):**
```powershell
Start-ScheduledTask -TaskName "XAUUSD_Quant_Controller"
```

---

## Safe Operation Rules

| Rule | Detail |
|------|--------|
| ✅ Use the controller | Always start via `system_controller.ps1` or the scheduled task |
| ❌ Never run two instances | Check Task Manager before starting manually |
| ❌ Never delete `state.json` | This is the resume pointer — deleting it causes gap |
| ❌ Never delete `xauusd_ticks_raw.csv` while running | Close logger first |
| ✅ Monitor heartbeat | Check `metadata/heartbeat.csv` to confirm logging is alive |
| ✅ Keep MT5 logged in | Logger cannot fetch ticks if MT5 is disconnected |

---

## Stopping the Logger Safely

Press `Ctrl+C` in the terminal window. The logger will save state cleanly before exiting.
Do **not** force-kill the process while it is writing to CSV.

---

## Controller Log

The system controller writes a detailed log to:
```
logs\controller.log
```

Check this file if you suspect the logger stopped or failed to restart.