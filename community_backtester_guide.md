# Community Backtester Guide — IMC Prosperity 4

## Why Use a Community Backtester?

The IMC website only lets you upload your algorithm and wait for results. The community backtester runs **locally and instantly**, giving you:

- Unlimited runs (no upload cooldowns)
- Full local debugging (breakpoints, profilers, print statements)
- Control over which round/day data you test against
- Faster iteration: edit → run → see results in seconds

There are two community backtesters available. Both trace lineage to Jasper van Merle's Prosperity 3 backtester.

---

## Option A: `prosperity4bt` (pip-installable, recommended for most users)

**Repo:** https://github.com/xeeshan85/imc-prosperity-4-backtester
**Author:** Xeeshan (based on Jasper van Merle's work)

### Installation

```sh
pip install -U prosperity4bt
```

Run the same command again any time you want to update to the latest version.

**Dependencies (installed automatically):** jsonpickle, orjson, tqdm, typer, ipython

### Basic Usage

```sh
# Run on all data from round 0 (tutorial)
prosperity4bt algo.py 0

# Run on all data from round 1
prosperity4bt algo.py 1
```

### Selecting Specific Days

Round data is split into multiple days. You can target specific ones:

```sh
# Round 1, day 0
prosperity4bt algo.py 1-0

# Round 1, day -1 and day 0
prosperity4bt algo.py 1--1 1-0

# All days from rounds 1 and 2
prosperity4bt algo.py 1 2
```

### CLI Flags

| Flag | Description |
|---|---|
| `--merge-pnl` | Merge profit and loss across multiple days into one combined result |
| `--out <file>` | Write the output log to a custom file path |
| `--no-out` | Skip saving the output log entirely |
| `--data <dir>` | Use a custom data directory instead of the bundled data |
| `--print` | Print your algorithm's stdout in real time (useful for debugging crashes) |
| `--match-trades <mode>` | Configure how market trades are matched against your orders (see below) |

### Examples

```sh
# Merge PnL across all days in round 1
prosperity4bt algo.py 1 --merge-pnl

# Write output to a specific file
prosperity4bt algo.py 1 --out results.log

# Debug a broken algorithm by printing its output live
prosperity4bt algo.py 1 --print

# Use your own data directory
prosperity4bt algo.py 1 --data ./my_custom_data/
```

### Trade Matching Modes (`--match-trades`)

Orders are first matched against the order book (order depths). If the order book can't fully fill your order, the backtester matches against that timestamp's market trades.

| Mode | Behavior |
|---|---|
| `all` (default) | Match market trades with prices equal to or worse than your quotes |
| `worse` | Match only market trades with prices strictly worse than your quotes (inspired by team Linear Utility's Prosperity 2 write-up) |
| `none` | Do not match market trades against your orders at all |

When matching against market trades, your order executes at **your order's price**, not the market trade price. For example, if you place a sell at 9 and there's a market trade at 10, the fill is at 9 — consistent with the official Prosperity environment.

### Position Limit Enforcement

Position limits are enforced **before** orders are matched. If the aggregate volume of your orders for a product would exceed the position limit (assuming all get filled), **all orders for that product are cancelled** — same as the official environment.

### Environment Variables

During backtests, two environment variables are set:

| Variable | Description |
|---|---|
| `PROSPERITY4BT_ROUND` | The current round number |
| `PROSPERITY4BT_DAY` | The current day number |

**Warning:** These do not exist in the official submission environment. Do not write code that depends on them for your actual submission.

### Bundled Data

The pip package ships with data for:
- **Round 0 (Tutorial):** EMERALDS (position limit 80), TOMATOES (position limit 80)

Round 1+ data is added to the package as the competition progresses.

---

## Option B: kevin-fu1's OOP Backtester (clone-and-run, more transparent internals)

**Repo:** https://github.com/kevin-fu1/imc-prosperity-4-backtester

### Installation

```sh
git clone https://github.com/kevin-fu1/imc-prosperity-4-backtester.git
cd imc-prosperity-4-backtester
```

If you get `No module named 'datamodel'`, set your PYTHONPATH:

```sh
# macOS / Linux
export PYTHONPATH="$(pwd)/prosperity4bt"

# Windows PowerShell
$env:PYTHONPATH="<path to>\imc-prosperity-4-backtester\prosperity4bt"
```

### Basic Usage

```sh
# All data from round 0
python -m prosperity4bt algo.py 0

# Round 0, day -2 specifically
python -m prosperity4bt algo.py 0--2
```

### Architecture

This backtester is more modular / OOP-oriented. The execution flow:

```
BackTester (main controller)
├── Load Algorithm Module
├── For each round × each day:
│   └── TestRunner (daily simulator)
│       ├── BackDataReader → reads price + trade CSVs
│       └── For each timestamp:
│           ├── Build TradingState
│           ├── Call your Algorithm.run()
│           ├── ActivityLogCreator → logs state + orders
│           └── OrderMatchMaker → simulates order fills
├── Merge Results
└── Write Output File (e.g., 2026-03-01_08-35-51.log)
```

**Key modules:**
- **BackDataReader** — parses `prices_round_X_day_Y.csv` and `trades_round_X_day_Y.csv` into internal data models
- **ActivityLogCreator** — records market state, your orders, and positions at each timestamp
- **OrderMatchMaker** — simulates exchange mechanics, fills your orders against the historical order book

**Important:** Do not modify `datamodel.py` in this repo — it mirrors the official Prosperity 4 data model, and changes will break compatibility with the real environment.

### PyCharm Setup

Add a Run/Debug Configuration with:
- **Module name:** `prosperity4bt`
- **Parameters:** `<path to algo file> <round>`

This lets you set breakpoints and step through your algorithm.

### Companion Visualizer

This backtester pairs with a visualizer for graphical analysis of your results:
https://github.com/kevin-fu1/imc-prosperity-4-visualizer

Use the structured `Logger` class from the visualizer in your algorithm, and the backtester will capture structured data in the `lambda_log` field of the output.

---

## Which Backtester Should I Use?

| Consideration | pip `prosperity4bt` | kevin-fu1 clone |
|---|---|---|
| **Ease of setup** | One `pip install` | Clone repo + set PYTHONPATH |
| **CLI features** | Rich: `--merge-pnl`, `--match-trades`, `--print`, `--data` | Basic round/day selection |
| **Debugging** | `--print` flag for stdout | Full IDE debugger with breakpoints |
| **Transparency** | Packaged wheel | Source code visible, easy to read/modify |
| **Updates** | `pip install -U` | `git pull` |
| **Visualizer integration** | Use with jmerle's web visualizer | Has its own companion visualizer |

**Recommendation:** Start with the pip package for quick iteration. Use kevin-fu1's version if you want to step through the matching engine with a debugger or customize how the backtester works.

---

## Writing Your Algorithm

Both backtesters expect a file with a `Trader` class that has a `run()` method:

```python
from datamodel import OrderDepth, TradingState, Order
from typing import List

class Trader:
    def run(self, state: TradingState):
        result = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            # Your trading logic here
            # Example: buy below 9995, sell above 10005
            best_ask = min(order_depth.sell_orders.keys())
            best_bid = max(order_depth.buy_orders.keys())

            if best_ask < 9995:
                orders.append(Order(product, best_ask, -order_depth.sell_orders[best_ask]))
            if best_bid > 10005:
                orders.append(Order(product, best_bid, -order_depth.buy_orders[best_bid]))

            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData
```

### State Persistence

The backtester handles `traderData` round-tripping just like the real environment. Serialize state with `jsonpickle`:

```python
import jsonpickle

class Trader:
    def run(self, state: TradingState):
        # Restore state
        if state.traderData:
            my_state = jsonpickle.decode(state.traderData)
        else:
            my_state = {"tick_count": 0}

        my_state["tick_count"] += 1

        # ... trading logic ...

        traderData = jsonpickle.encode(my_state)
        return result, conversions, traderData
```

---

## Interpreting Output

Both backtesters produce a log file similar to the one you download from the IMC website. The log contains:

- **Activity logs** — per-timestamp snapshots of order book state, your orders, trades, and positions
- **PnL** — profit and loss per product and overall
- **Lambda log** — everything your algorithm printed via `print()`

Use the **Prosperity Visualizer** to turn these logs into charts:
https://jmerle.github.io/imc-prosperity-visualizer/

Upload your log file and you get interactive plots of price, position, and PnL over time.

---

## Common Pitfalls

1. **Backtester PnL ≠ official PnL.** The backtester approximates the matching engine. Differences in trade matching, especially around market trades, mean results won't be identical.

2. **Overfitting to sample data.** The official scoring runs on a different day than the sample data. If your strategy is tuned to specific price patterns in the sample, it may underperform on the real data.

3. **Position limit violations.** If your aggregate order volume could exceed the limit, ALL orders for that product are cancelled — not just the excess. This is a common source of "my algo did nothing" bugs.

4. **`run()` timeout.** The official environment kills your `run()` call after 900ms. The backtester doesn't enforce this. Profile locally to ensure you stay under ~100ms average.

5. **No filesystem/network access.** The official environment runs on AWS Lambda. The backtester runs locally so file/network access works, but any code using it will break on submission.

6. **Conversions not supported** in the pip backtester. If your strategy relies on conversion requests, test that part on the official platform.
