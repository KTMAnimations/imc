"""
Aggregated log-based simulator for IMC Prosperity web backtester.

Loads one or more `.log` files (JSON activities + tradeHistory) produced by the
web backtester, unifies the order book per timestamp (they should agree since
all logs replay the same market data), and unions the trade histories into a
richer "passive liquidity menu" for the simulated matching engine.

The matching rules mirror IMC Prosperity enforcement:
  - BUY(sym, price, qty): take sell_orders at price <= given, cheapest first.
  - SELL(sym, price, qty): hit buy_orders at price >= given, highest first.
  - Residual (unfilled) becomes passive and is matched against aggregated
    reference passive trades whose quoted side/price is consistent with our
    order.

A 'passive' reference trade is one whose trade price is strictly inside the
visible best bid / best ask at that timestamp. Aggregating these across many
logs gives a denser, more realistic picture of what would actually fill.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import traceback
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from datamodel import Order, OrderDepth, TradingState  # noqa: E402


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class Book:
    """Order book snapshot at one (ts, product)."""

    bids: Dict[int, int] = field(default_factory=dict)  # price -> volume
    asks: Dict[int, int] = field(default_factory=dict)


@dataclass
class PassiveQuote:
    """A single bot-liquidity event at a (ts, product, side) key.

    After aggregation there is AT MOST ONE quote per (ts, product, side) —
    all historical passive-trade observations for that key collapse into
    one entry, because they all represent the same underlying bot event
    observed through different historical strategies' quote prices.

    Fields:
      side: the side OUR order must be on to match this event:
        'BUY'  → a bot was willing to sell, so our BUY  at price >= threshold hits.
        'SELL' → a bot was willing to buy,  so our SELL at price <= threshold hits.
      threshold_price: the minimum (BUY) / maximum (SELL) price our order
        must satisfy to hit. Derived conservatively from the historical
        observations — the LOWEST observed fill price across logs for
        BUY-side, the HIGHEST observed for SELL-side. This is the strictest
        defensible threshold: if any historical strategy filled at P, we
        know the bot was willing to trade at P.
      qty: the MAX observed fill quantity across logs at this key — a
        lower bound on the bot's total willingness at this ts.
      source: last log that contributed to this entry (for debugging).

    IMPORTANT: unlike the previous version, the FILL price is NOT stored
    here. When a residual order matches this quote in `_match_passive`,
    the fill happens at OUR ORDER'S price, not at `threshold_price`. This
    reflects reality: if our quote is the best bid (because it beats the
    historical strategy's bid that recorded this observation), the bot
    trades at OUR price, not at the stale historical price. Filling at
    `threshold_price` was the phantom-edge bug that caused tradestrategy_v2
    to look good in simulation but underperform in reality.
    """

    side: str  # 'BUY' or 'SELL' — side our order must be on to hit this
    threshold_price: int
    qty: int
    source: str  # log file the trade came from (for debugging)


@dataclass
class Timeline:
    timestamps: List[int]
    books: Dict[int, Dict[str, Book]]  # ts -> product -> Book
    passive_menu: Dict[int, Dict[str, List[PassiveQuote]]]
    mids: Dict[int, Dict[str, float]]  # ts -> product -> mid
    final_mids: Dict[str, float]
    products: List[str]
    log_count: int
    log_paths: List[str]


@dataclass
class TradeRecord:
    ts: int
    product: str
    price: int
    qty: int  # signed: +buy / -sell
    passive: bool  # whether this was a passive fill


@dataclass
class SimResult:
    timestamps: List[int]
    pnl_history: Dict[str, List[float]]  # per product, mark-to-market over time
    position_history: Dict[str, List[int]]
    cashflow_history: Dict[str, List[float]]
    final_pnl: Dict[str, float]
    total_pnl: float
    trades: List[TradeRecord]
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Log loading and aggregation
# ---------------------------------------------------------------------------


def _parse_activities(activities: str) -> Tuple[Dict[int, Dict[str, Book]], Dict[int, Dict[str, float]]]:
    """Parse the CSV activitiesLog block into books + mids."""
    lines = activities.strip().split("\n")
    books: Dict[int, Dict[str, Book]] = defaultdict(dict)
    mids: Dict[int, Dict[str, float]] = defaultdict(dict)

    # header: day;timestamp;product;bid_price_1;bid_volume_1;bid_price_2;bid_volume_2;bid_price_3;bid_volume_3;ask_price_1;ask_volume_1;ask_price_2;ask_volume_2;ask_price_3;ask_volume_3;mid_price;profit_and_loss
    for line in lines[1:]:
        parts = line.split(";")
        if len(parts) < 17:
            continue
        try:
            ts = int(parts[1])
        except ValueError:
            continue
        product = parts[2]
        book = Book()
        for i in range(3):
            bp = parts[3 + 2 * i]
            bv = parts[4 + 2 * i]
            ap = parts[9 + 2 * i]
            av = parts[10 + 2 * i]
            if bp and bv:
                book.bids[int(bp)] = int(bv)
            if ap and av:
                book.asks[int(ap)] = int(av)
        books[ts][product] = book
        try:
            mids[ts][product] = float(parts[15]) if parts[15] else 0.0
        except ValueError:
            mids[ts][product] = 0.0

    return dict(books), dict(mids)


def _classify_passive_trade(trade: Dict[str, Any], book: Book) -> Optional[Tuple[str, int, int]]:
    """
    Return (counterparty_side, price, qty) if the trade looks passive in the
    visible book, else None.

    `counterparty_side` is the side a *new* order of ours would need to be on
    to match this resting liquidity: if the reference SUBMISSION was a BUYER
    passively at price P, then there was a bot SELLER at P — so our order to
    match that bot would need to be a BUY (we hit them) ... wait no, the bot
    SELLER already lifted our old bid. That means "liquidity was willing to
    sell at P" → we can also sell at P to them if we're SELLING, not buying.

    Let's re-do this carefully. A 'passive' trade means the trade price was
    strictly between best bid and best ask. If SUBMISSION was the buyer, our
    resting BID at price P got filled (bot sold to us at P). That means there
    was a bot SELLER that reached down to P. Reusing this as a liquidity
    event: "at ts T, there was a bot willing to SELL at P". So a new BUY from
    us at price >= P can also fill. We store side='SELL' meaning "bot was
    selling, hit with a BUY".

    Symmetrically SUBMISSION seller passive → 'bot was buying, hit with a SELL'.

    For bot-to-bot trades (where neither side is SUBMISSION), we still know a
    trade crossed between two bots at price P — but we can't tell which side
    reached out. We conservatively record both (a BUY-hittable and a
    SELL-hittable) at that price, each with the observed qty.
    """
    price = int(trade["price"])
    qty = int(trade["quantity"])
    bb = max(book.bids) if book.bids else None
    ba = min(book.asks) if book.asks else None
    if bb is None or ba is None:
        return None
    # inside-spread test
    if not (bb < price < ba):
        return None
    return (price, qty, None)  # side decided by caller


def _load_log(log_path: str) -> Optional[Dict[str, Any]]:
    """
    Load a .log file written by the web backtester or prosperity-tools
    backtester. Returns None for unrecognised formats or empty files.
    """
    with open(log_path, "r") as f:
        text = f.read().strip()
    if not text:
        return None
    # web backtester logs are a single JSON object
    if text.startswith("{"):
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and "activitiesLog" in data and "tradeHistory" in data:
            return data
        return None
    # prosperity-tools logs have 'Activities log:' and 'Trade History:' sections
    if "Activities log:" in text and "Trade History:" in text:
        try:
            _, rest = text.split("Activities log:", 1)
            activities_block, rest = rest.split("Trade History:", 1)
            activities = activities_block.strip()
            trade_history_raw = rest.strip()
            trade_history = json.loads(trade_history_raw) if trade_history_raw else []
            return {"activitiesLog": activities, "tradeHistory": trade_history}
        except (ValueError, json.JSONDecodeError):
            return None
    return None


def get_log_day(log_path: str) -> Optional[int]:
    """Return the `day` field from the first data row of a log's activitiesLog."""
    data = _load_log(log_path)
    if data is None:
        return None
    lines = data["activitiesLog"].strip().split("\n")
    if len(lines) < 2:
        return None
    try:
        return int(lines[1].split(";")[0])
    except (ValueError, IndexError):
        return None


def group_logs_by_day(log_paths: Sequence[str]) -> Dict[int, List[str]]:
    """Group a flat list of log paths by their `day` field."""
    groups: Dict[int, List[str]] = defaultdict(list)
    for lp in log_paths:
        day = get_log_day(lp)
        if day is None:
            continue
        groups[day].append(lp)
    return {k: sorted(v) for k, v in sorted(groups.items())}


def build_timeline(log_paths: Sequence[str]) -> Timeline:
    """
    Load and aggregate multiple log files into a single Timeline. All logs
    must share the same `day` field; logs from other days are silently
    skipped (use `group_logs_by_day` to filter beforehand).

    Passive fills observed across multiple logs are deduplicated by
    (ts, product, side), NOT by (ts, product, side, price). This is
    important: two historical logs that observed a passive fill at the
    same (ts, side) but at different prices are NOT two independent
    events — they are the same underlying bot activity observed through
    different historical strategies' quote prices. The previous per-price
    dedup left both entries in the menu, creating phantom liquidity that
    a wide-quoting strategy could double-dip on.

    For each (ts, product, side) we keep:
      - the MAX qty observed across logs (lower bound on bot willingness)
      - a conservative threshold price: MIN observed for BUY-side,
        MAX observed for SELL-side. This is the weakest price any
        historical strategy got filled at, and is the strictest price
        threshold we can defend from the evidence.
    """
    if not log_paths:
        raise ValueError("no log paths provided")

    merged_books: Dict[int, Dict[str, Book]] = {}
    merged_mids: Dict[int, Dict[str, float]] = {}
    # (ts, prod, side) -> {"qty": max_qty, "threshold": conservative_threshold,
    #                       "source": last_source}
    quote_agg: Dict[Tuple[int, str, str], Dict[str, Any]] = {}
    all_products: set = set()
    loaded_paths: List[str] = []
    target_day: Optional[int] = None

    for lp in log_paths:
        data = _load_log(lp)
        if data is None:
            continue
        # Enforce single-day — pick the first log's day as target.
        lines = data["activitiesLog"].strip().split("\n")
        if len(lines) < 2:
            continue
        try:
            day = int(lines[1].split(";")[0])
        except (ValueError, IndexError):
            continue
        if target_day is None:
            target_day = day
        elif day != target_day:
            continue
        loaded_paths.append(lp)

        books, mids = _parse_activities(data["activitiesLog"])
        # Books should be identical across logs; keep first-seen.
        for ts, per_prod in books.items():
            if ts not in merged_books:
                merged_books[ts] = {}
                merged_mids[ts] = {}
            for prod, book in per_prod.items():
                all_products.add(prod)
                if prod not in merged_books[ts]:
                    merged_books[ts][prod] = book
                    merged_mids[ts][prod] = mids[ts].get(prod, 0.0)

        # Build the passive liquidity menu from this log's tradeHistory.
        for t in data["tradeHistory"]:
            ts = int(t["timestamp"])
            prod = t["symbol"]
            if ts not in merged_books or prod not in merged_books[ts]:
                continue
            book = merged_books[ts][prod]
            bb = max(book.bids) if book.bids else None
            ba = min(book.asks) if book.asks else None
            if bb is None or ba is None:
                continue
            price = int(t["price"])
            qty = int(t["quantity"])
            if qty <= 0:
                continue
            if not (bb < price < ba):
                # not inside spread → not a passive fill (either aggressive take
                # or on-the-touch); skip.
                continue

            buyer = t.get("buyer") or ""
            seller = t.get("seller") or ""
            source = os.path.basename(lp)

            # PassiveQuote.side = the side OUR order must be on to hit this liquidity.
            # SUBMISSION buyer passive  → a bot was selling at P → we can BUY at >=P
            # SUBMISSION seller passive → a bot was buying at P  → we can SELL at <=P
            # Bot-to-bot passive        → we don't know which side rested, record both
            if buyer == "SUBMISSION":
                sides = ("BUY",)
            elif seller == "SUBMISSION":
                sides = ("SELL",)
            else:
                sides = ("BUY", "SELL")
            for s in sides:
                key = (ts, prod, s)
                cur = quote_agg.get(key)
                if cur is None:
                    quote_agg[key] = {
                        "qty": qty,
                        "threshold": price,
                        "source": source,
                    }
                else:
                    cur["qty"] = max(cur["qty"], qty)
                    # BUY-side: our BUY threshold = min observed fill price
                    # (lowest bid any historical strategy was filled at).
                    # SELL-side: our SELL threshold = max observed fill price.
                    if s == "BUY":
                        if price < cur["threshold"]:
                            cur["threshold"] = price
                    else:
                        if price > cur["threshold"]:
                            cur["threshold"] = price
                    cur["source"] = source

    timestamps = sorted(merged_books.keys())
    final_mids: Dict[str, float] = {}
    for prod in all_products:
        # find the latest ts that has this product
        for ts in reversed(timestamps):
            if prod in merged_books[ts]:
                book = merged_books[ts][prod]
                if book.bids and book.asks:
                    final_mids[prod] = (max(book.bids) + min(book.asks)) / 2
                else:
                    final_mids[prod] = merged_mids[ts].get(prod, 0.0)
                break
        else:
            final_mids[prod] = 0.0

    # Rebuild passive_menu from the deduped quote_agg dict.
    frozen_menu: Dict[int, Dict[str, List[PassiveQuote]]] = {}
    for (ts, prod, side), info in quote_agg.items():
        frozen_menu.setdefault(ts, {}).setdefault(prod, []).append(
            PassiveQuote(
                side=side,
                threshold_price=info["threshold"],
                qty=info["qty"],
                source=info["source"],
            )
        )

    if not timestamps:
        raise ValueError(
            f"no usable logs in {len(log_paths)} input path(s) — "
            f"all were unrecognised or empty"
        )

    return Timeline(
        timestamps=timestamps,
        books=merged_books,
        passive_menu=frozen_menu,
        mids=merged_mids,
        final_mids=final_mids,
        products=sorted(all_products),
        log_count=len(loaded_paths),
        log_paths=loaded_paths,
    )


# ---------------------------------------------------------------------------
# Trader loading
# ---------------------------------------------------------------------------


def load_trader_from_file(script_path: str):
    """Load an arbitrary .py file and return an instance of its Trader class."""
    script_path = os.path.abspath(script_path)
    if not os.path.isfile(script_path):
        raise FileNotFoundError(script_path)
    module_name = f"_user_trader_{abs(hash(script_path))}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load spec for {script_path}")
    module = importlib.util.module_from_spec(spec)
    # Make the script's own directory importable too, in case of sibling modules.
    script_dir = os.path.dirname(script_path)
    added = False
    if script_dir and script_dir not in sys.path:
        sys.path.insert(0, script_dir)
        added = True
    try:
        spec.loader.exec_module(module)
    finally:
        if added:
            try:
                sys.path.remove(script_dir)
            except ValueError:
                pass
    if not hasattr(module, "Trader"):
        raise AttributeError(f"{script_path} does not define a `Trader` class")
    return module.Trader()


# ---------------------------------------------------------------------------
# Simulation engine
# ---------------------------------------------------------------------------


def _match_aggressive(
    orders: List[Order],
    book_asks: Dict[int, int],
    book_bids: Dict[int, int],
) -> Tuple[List[Tuple[int, int, bool]], List[Order]]:
    """
    Match aggressive portions of orders against the visible book. Returns
    (fills, residuals) where each fill is (price, signed_qty, passive_flag).
    Residuals carry the un-filled remainder.

    Mutates book_asks / book_bids in place.
    """
    fills: List[Tuple[int, int, bool]] = []
    residuals: List[Order] = []

    for order in orders:
        price = order.price
        qty = order.quantity
        if qty > 0:
            remaining = qty
            for ap in sorted(book_asks.keys()):
                if ap > price or remaining <= 0:
                    break
                take = min(remaining, book_asks[ap])
                if take > 0:
                    fills.append((ap, take, False))
                    book_asks[ap] -= take
                    if book_asks[ap] == 0:
                        del book_asks[ap]
                    remaining -= take
            if remaining > 0:
                residuals.append(Order(order.symbol, price, remaining))
        elif qty < 0:
            remaining = -qty
            for bp in sorted(book_bids.keys(), reverse=True):
                if bp < price or remaining <= 0:
                    break
                take = min(remaining, book_bids[bp])
                if take > 0:
                    fills.append((bp, -take, False))
                    book_bids[bp] -= take
                    if book_bids[bp] == 0:
                        del book_bids[bp]
                    remaining -= take
            if remaining > 0:
                residuals.append(Order(order.symbol, price, -remaining))

    return fills, residuals


def _match_passive(
    residuals: List[Order],
    menu: List[PassiveQuote],
) -> List[Tuple[int, int, bool]]:
    """
    Match residual (passive) orders against the aggregated passive liquidity
    menu at this ts for this product. Consume quote qty as orders fill.

    Matching rules:
      - A residual BUY  at price P hits 'BUY'  quotes with threshold_price <= P.
      - A residual SELL at price P hits 'SELL' quotes with threshold_price >= P.

    Fill price is OUR ORDER'S price (P), NOT the quote's threshold. This is
    the key fix: if our quote beats the historical strategy that generated
    the observation, then in reality our quote would be the new best bid/ask
    and the bot would trade at our price, not at the stale historical price.
    Filling at the historical price was the phantom-edge bug.

    If we are willing to pay more than any historical strategy did, we pay
    more — just like in reality. There is no longer a free lunch from
    quoting wider.
    """
    fills: List[Tuple[int, int, bool]] = []

    for order in residuals:
        price = order.price
        qty = order.quantity
        if qty > 0:
            remaining = qty
            for q in menu:
                if remaining <= 0:
                    break
                if q.side != "BUY" or q.qty <= 0 or q.threshold_price > price:
                    continue
                take = min(remaining, q.qty)
                if take > 0:
                    fills.append((price, take, True))  # fill at OUR price
                    q.qty -= take
                    remaining -= take
        elif qty < 0:
            remaining = -qty
            for q in menu:
                if remaining <= 0:
                    break
                if q.side != "SELL" or q.qty <= 0 or q.threshold_price < price:
                    continue
                take = min(remaining, q.qty)
                if take > 0:
                    fills.append((price, -take, True))  # fill at OUR price
                    q.qty -= take
                    remaining -= take

    return fills


def simulate(trader: Any, timeline: Timeline) -> SimResult:
    """
    Run `trader.run(state)` over every timestamp in the timeline, match
    resulting orders, and return a SimResult with per-ts PnL/position history.
    """
    products = timeline.products
    positions: Dict[str, int] = {p: 0 for p in products}
    cashflows: Dict[str, float] = {p: 0.0 for p in products}

    pnl_history: Dict[str, List[float]] = {p: [] for p in products}
    pos_history: Dict[str, List[int]] = {p: [] for p in products}
    cash_history: Dict[str, List[float]] = {p: [] for p in products}
    trades: List[TradeRecord] = []

    # Working copies of the passive menu (qty will be decremented).
    working_menu: Dict[int, Dict[str, List[PassiveQuote]]] = {}
    for ts, per_prod in timeline.passive_menu.items():
        working_menu[ts] = {
            prod: [PassiveQuote(q.side, q.threshold_price, q.qty, q.source) for q in qs]
            for prod, qs in per_prod.items()
        }

    trader_data = ""
    error: Optional[str] = None

    try:
        for ts in timeline.timestamps:
            per_prod = timeline.books.get(ts, {})

            order_depths = {}
            live_asks: Dict[str, Dict[int, int]] = {}
            live_bids: Dict[str, Dict[int, int]] = {}
            for prod, book in per_prod.items():
                od = OrderDepth()
                od.buy_orders = dict(book.bids)
                od.sell_orders = {p: -v for p, v in book.asks.items()}
                order_depths[prod] = od
                live_asks[prod] = dict(book.asks)
                live_bids[prod] = dict(book.bids)

            state = TradingState(
                traderData=trader_data,
                timestamp=ts,
                listings={},
                order_depths=order_depths,
                own_trades={},
                market_trades={},
                position=dict(positions),
                observations=None,
            )

            try:
                result, _conversions, new_trader_data = trader.run(state)
            except Exception:
                raise RuntimeError(
                    f"trader.run() crashed at ts={ts}:\n{traceback.format_exc()}"
                )
            if isinstance(new_trader_data, str):
                trader_data = new_trader_data

            # Match each product's orders
            for sym, orders in (result or {}).items():
                if sym not in live_asks or sym not in live_bids:
                    continue
                fills, residuals = _match_aggressive(
                    list(orders), live_asks[sym], live_bids[sym]
                )
                passive_fills = _match_passive(
                    residuals, working_menu.get(ts, {}).get(sym, [])
                )
                for price, signed_qty, passive in fills + passive_fills:
                    cashflows[sym] -= price * signed_qty
                    positions[sym] += signed_qty
                    trades.append(
                        TradeRecord(
                            ts=ts,
                            product=sym,
                            price=price,
                            qty=signed_qty,
                            passive=passive,
                        )
                    )

            # Mark-to-market using this ts's mid
            for prod in products:
                mid = timeline.mids.get(ts, {}).get(prod)
                if mid is None or mid == 0.0:
                    mid = timeline.final_mids.get(prod, 0.0)
                pnl = cashflows[prod] + positions[prod] * mid
                pnl_history[prod].append(pnl)
                pos_history[prod].append(positions[prod])
                cash_history[prod].append(cashflows[prod])

    except Exception:
        error = traceback.format_exc()

    final_pnl = {
        prod: cashflows[prod] + positions[prod] * timeline.final_mids.get(prod, 0.0)
        for prod in products
    }
    total = sum(final_pnl.values())

    return SimResult(
        timestamps=timeline.timestamps[: len(pnl_history[products[0]])] if products and pnl_history[products[0]] else [],
        pnl_history=pnl_history,
        position_history=pos_history,
        cashflow_history=cash_history,
        final_pnl=final_pnl,
        total_pnl=total,
        trades=trades,
        error=error,
    )


# ---------------------------------------------------------------------------
# Log discovery helpers
# ---------------------------------------------------------------------------


def discover_logs(repo_root: str = REPO_ROOT) -> List[str]:
    """Return a sorted list of all .log files under the repo root."""
    results: List[str] = []
    for dirpath, _dirs, files in os.walk(repo_root):
        # Skip anything under sim_gui itself and __pycache__
        if "__pycache__" in dirpath or "/sim_gui" in dirpath:
            continue
        for f in files:
            if f.endswith(".log"):
                results.append(os.path.join(dirpath, f))
    return sorted(results)


# ---------------------------------------------------------------------------
# CLI entry point (for quick sanity checks)
# ---------------------------------------------------------------------------


def _main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="Aggregated backtest simulator")
    ap.add_argument("trader", help="path to a trader .py file (defines class Trader)")
    ap.add_argument(
        "--logs",
        nargs="*",
        help="paths to one or more .log files to aggregate; default=all discovered",
    )
    ap.add_argument(
        "--day",
        type=int,
        default=None,
        help="restrict to logs from this `day`; default=pick day with most logs",
    )
    args = ap.parse_args()

    raw_logs = args.logs if args.logs else discover_logs()
    if not raw_logs:
        ap.error("no log files found")

    groups = group_logs_by_day(raw_logs)
    if not groups:
        ap.error("no parsable log files found")

    if args.day is not None:
        if args.day not in groups:
            ap.error(f"no logs for day={args.day}; available: {sorted(groups.keys())}")
        day = args.day
    else:
        day = max(groups.keys(), key=lambda k: len(groups[k]))
    logs = groups[day]

    print(f"Using day={day}, aggregating {len(logs)} log(s):")
    for lp in logs:
        print(f"  - {lp}")

    timeline = build_timeline(logs)
    print(
        f"Timeline: {len(timeline.timestamps)} timestamps, "
        f"{len(timeline.products)} products {timeline.products}"
    )
    menu_rows = sum(len(v) for per in timeline.passive_menu.values() for v in per.values())
    print(f"Aggregated passive menu entries: {menu_rows}")

    trader = load_trader_from_file(args.trader)
    result = simulate(trader, timeline)

    print("\n=== Final PnL ===")
    for prod in sorted(result.final_pnl.keys()):
        print(f"  {prod}: {result.final_pnl[prod]:.2f}")
    print(f"  TOTAL: {result.total_pnl:.2f}")
    print(f"  Trades: {len(result.trades)}")
    if result.error:
        print("\n[error during simulation]")
        print(result.error)


if __name__ == "__main__":
    _main()
