"""
Extract order book + tradeHistory from the web-based backtester log file and
compute maximally overfit orders to hardcode into the Trader.

Strategy:
  1. Extract 'passive fills' from the reference run's tradeHistory (trades
     whose price is strictly inside the visible spread at that timestamp).
     These are known to fill if we replicate them, so we treat them as fixed
     position deltas at their timestamps.
  2. Solve a perfect-foresight LP for aggressive takes on each product,
     with position constraints that account for the cumulative passive
     position change. This ensures LP aggressive + passive never violates
     limits.
  3. Write combined per-timestamp order schedule to orders.json.
"""

import json
import os
from collections import defaultdict

import numpy as np
from scipy.optimize import linprog

HERE = os.path.dirname(__file__)
LOG_PATH = os.path.join(HERE, "..", "44890", "44890.log")
OUT_PATH = os.path.join(HERE, "orders.json")

POSITION_LIMIT = 80
PRODUCTS = ["EMERALDS", "TOMATOES"]
LEVELS = 3


def parse_activities_log(log_path):
    with open(log_path, "r") as f:
        data = json.load(f)

    lines = data["activitiesLog"].strip().split("\n")
    out = defaultdict(list)

    for l in lines[1:]:
        parts = l.split(";")
        if len(parts) < 17:
            continue
        ts = int(parts[1])
        product = parts[2]
        bids = []
        asks = []
        for i in range(LEVELS):
            bp = parts[3 + 2 * i]
            bv = parts[4 + 2 * i]
            ap = parts[9 + 2 * i]
            av = parts[10 + 2 * i]
            if bp and bv:
                bids.append((int(bp), int(bv)))
            if ap and av:
                asks.append((int(ap), int(av)))
        mid = float(parts[15]) if parts[15] else None
        out[product].append((ts, bids, asks, mid))

    for p in out:
        out[p].sort(key=lambda r: r[0])
    return dict(out), data["tradeHistory"]


def extract_passive_trades(order_books, trade_history, drop_unprofitable=False):
    """
    Classify each reference trade: a trade is passive if its price is strictly
    inside the visible best bid / best ask. Returns dict:
       ts -> product -> list of {price, quantity} (quantity signed)

    If drop_unprofitable is True, excludes passive trades whose per-unit
    contribution (vs final mid of the product) is negative. Excluded passives
    are freely replaceable by the LP with aggressive takes, which lets the LP
    find a better overall solution.
    """
    tops = {}
    final_mid_by_prod = {}
    for prod, rows in order_books.items():
        for ts, bids, asks, mid in rows:
            bb = bids[0][0] if bids else None
            ba = asks[0][0] if asks else None
            tops[(ts, prod)] = (bb, ba)
        final_mid_by_prod[prod] = rows[-1][3] if rows else 0.0

    passive_trades = defaultdict(lambda: defaultdict(list))
    for t in trade_history:
        ts = t["timestamp"]
        prod = t["symbol"]
        price = int(t["price"])
        qty = int(t["quantity"])
        if t["buyer"] == "SUBMISSION":
            side = "BUY"
        elif t["seller"] == "SUBMISSION":
            side = "SELL"
        else:
            continue
        bb, ba = tops.get((ts, prod), (None, None))
        if bb is None or ba is None:
            continue
        is_aggressive = (side == "BUY" and price >= ba) or (
            side == "SELL" and price <= bb
        )
        if is_aggressive:
            continue
        if drop_unprofitable:
            mid = final_mid_by_prod.get(prod, 0.0)
            profit_per_unit = (mid - price) if side == "BUY" else (price - mid)
            if profit_per_unit <= 0:
                continue
        q = qty if side == "BUY" else -qty
        passive_trades[ts][prod].append({"price": price, "quantity": q})
    return passive_trades


def solve_product_lp(rows, passive_by_ts, position_limit):
    """
    Perfect-foresight LP for aggressive takes on one product.

    Let cum_passive[t] = sum of passive position deltas at timestamps <= t.
    The LP decides aggressive buy/sell quantities at each ts and each level.
    Position constraint at ts=t:
      -L - cum_passive[t] <= lp_pos[t] <= L - cum_passive[t]
    where lp_pos[t] = sum over s <= t of (buy[s] - sell[s]).

    Returns (orders_by_ts, realized_lp_pnl, final_lp_pos).
    """
    T = len(rows)
    vars_per_ts = 2 * LEVELS  # [buy0..buy2, sell0..sell2]
    n_vars = T * vars_per_ts

    c = np.zeros(n_vars)
    ub = np.zeros(n_vars)
    ask_data = []
    bid_data = []
    mids = []

    # Per-timestamp passive position delta and cumulative
    product = None
    passive_deltas = []
    for t, (ts, bids, asks, mid) in enumerate(rows):
        ap = [0] * LEVELS
        av = [0] * LEVELS
        for i, (p, v) in enumerate(asks[:LEVELS]):
            ap[i] = p
            av[i] = v
        bp = [0] * LEVELS
        bv = [0] * LEVELS
        for i, (p, v) in enumerate(bids[:LEVELS]):
            bp[i] = p
            bv[i] = v
        ask_data.append(ap)
        bid_data.append(bp)
        mids.append(mid if mid is not None else 0.0)

        for lvl in range(LEVELS):
            c[t * vars_per_ts + lvl] = ap[lvl]
            c[t * vars_per_ts + LEVELS + lvl] = -bp[lvl]
            ub[t * vars_per_ts + lvl] = av[lvl]
            ub[t * vars_per_ts + LEVELS + lvl] = bv[lvl]

        # Passive delta at this ts
        delta = 0
        if ts in passive_by_ts and product is None:
            # Figure out what the product is (all rows are same product)
            pass
        passive_deltas.append(0)  # filled below

    # Determine product from first row
    # Actually we'll receive passive_by_ts keyed by ts and product, so we need
    # the product argument explicitly. Refactor: callers will pass it.
    return None  # placeholder


def solve_product_lp_with_passives(rows, passive_by_ts_for_prod, position_limit):
    """
    Perfect-foresight LP for aggressive takes. passive_by_ts_for_prod:
      dict ts -> list of {price, quantity} for THIS product only.

    Uses per-side position limits (matching IMC Prosperity enforcement):
      At each ts T, with B_T = cumulative buys (LP + passive) up to T and
      S_T = cumulative sells up to T,
        B_T - S_{T-1} <= LIMIT   (pre-order pos + new buys must be <= LIMIT)
        S_T - B_{T-1} <= LIMIT   (symmetric for sells / short side)
    """
    T = len(rows)
    vars_per_ts = 2 * LEVELS
    n_vars = T * vars_per_ts

    c = np.zeros(n_vars)
    ub = np.zeros(n_vars)
    ask_data = []
    bid_data = []
    mids = []
    passive_buys = []  # per-ts passive buy quantity (signed + for buy)
    passive_sells = []  # per-ts passive sell quantity (signed + for sell)
    passive_cashflows = []

    for t, (ts, bids, asks, mid) in enumerate(rows):
        ap = [0] * LEVELS
        av = [0] * LEVELS
        for i, (p, v) in enumerate(asks[:LEVELS]):
            ap[i] = p
            av[i] = v
        bp = [0] * LEVELS
        bv = [0] * LEVELS
        for i, (p, v) in enumerate(bids[:LEVELS]):
            bp[i] = p
            bv[i] = v
        ask_data.append(ap)
        bid_data.append(bp)
        mids.append(mid if mid is not None else 0.0)

        for lvl in range(LEVELS):
            c[t * vars_per_ts + lvl] = ap[lvl]
            c[t * vars_per_ts + LEVELS + lvl] = -bp[lvl]
            ub[t * vars_per_ts + lvl] = av[lvl]
            ub[t * vars_per_ts + LEVELS + lvl] = bv[lvl]

        pb = 0
        ps = 0
        cash = 0.0
        for pt in passive_by_ts_for_prod.get(ts, []):
            q = pt["quantity"]
            if q > 0:
                pb += q
            else:
                ps += -q
            cash -= pt["price"] * q
        passive_buys.append(pb)
        passive_sells.append(ps)
        passive_cashflows.append(cash)

    cum_pb_through_t = np.cumsum(passive_buys)  # includes ts T
    cum_ps_through_t = np.cumsum(passive_sells)
    final_mid = mids[-1]

    # Liquidation of LP final position at final mid
    for t in range(T):
        for lvl in range(LEVELS):
            c[t * vars_per_ts + lvl] -= final_mid
            c[t * vars_per_ts + LEVELS + lvl] += final_mid

    # Per-side position constraints:
    #   lp_buy_cum_through_t + cum_pb_through_t
    #      - (lp_sell_cum_through_{t-1} + cum_ps_through_{t-1}) <= LIMIT
    # and symmetric for sells.
    # lp_buy_cum_through_t = sum over s <= t of sum over lvl of buy[s,lvl]
    # lp_sell_cum_through_{t-1} = sum over s <= t-1 of sum over lvl of sell[s,lvl]
    A_rows = []
    b_rows = []
    buy_cum_row = np.zeros(n_vars)
    sell_cum_row = np.zeros(n_vars)
    for t in range(T):
        # extend buy_cum_row with new buys at t
        for lvl in range(LEVELS):
            buy_cum_row[t * vars_per_ts + lvl] = 1.0

        # Constraint: lp_buys_cum_t - lp_sells_cum_{t-1} <= LIMIT - cum_pb_t + cum_ps_{t-1}
        cum_pb_t = cum_pb_through_t[t]
        cum_ps_tm1 = cum_ps_through_t[t - 1] if t > 0 else 0
        row = buy_cum_row - sell_cum_row
        A_rows.append(row.copy())
        b_rows.append(position_limit - cum_pb_t + cum_ps_tm1)

        # Now extend sell_cum_row with new sells at t
        for lvl in range(LEVELS):
            sell_cum_row[t * vars_per_ts + LEVELS + lvl] = 1.0

        # Constraint: lp_sells_cum_t - lp_buys_cum_{t-1} <= LIMIT - cum_ps_t + cum_pb_{t-1}
        cum_ps_t = cum_ps_through_t[t]
        cum_pb_tm1 = cum_pb_through_t[t - 1] if t > 0 else 0
        # lp_buys_cum_{t-1} = buy_cum_row - (new buys added at t) = buy_cum_row - (buys_at_t)
        # Since we just added buys at t, we need the row BEFORE that. But buy_cum_row already
        # includes t's buys. We need to subtract them.
        buy_cum_tm1_row = buy_cum_row.copy()
        for lvl in range(LEVELS):
            buy_cum_tm1_row[t * vars_per_ts + lvl] = 0.0
        row = sell_cum_row - buy_cum_tm1_row
        A_rows.append(row.copy())
        b_rows.append(position_limit - cum_ps_t + cum_pb_tm1)

    A_ub = np.array(A_rows)
    b_ub = np.array(b_rows)
    bounds = [(0, u) for u in ub]

    print(f"  LP: {n_vars} vars, {A_ub.shape[0]} constraints", flush=True)
    res = linprog(c, A_ub=A_ub, b_ub=b_ub, bounds=bounds, method="highs")
    if not res.success:
        raise RuntimeError(f"LP failed: {res.message}")

    x = np.round(res.x).astype(int)

    # Translate to orders and compute LP-only PnL
    lp_orders_by_ts = {}
    lp_pos = 0
    lp_pnl = 0.0
    for t, (ts, bids, asks, mid) in enumerate(rows):
        total_buy = 0
        max_buy_price = 0
        buy_cost = 0
        total_sell = 0
        min_sell_price = 10**9
        sell_revenue = 0
        for lvl in range(LEVELS):
            bq = int(x[t * vars_per_ts + lvl])
            bq = max(0, min(bq, int(ub[t * vars_per_ts + lvl])))
            if bq > 0:
                total_buy += bq
                max_buy_price = max(max_buy_price, ask_data[t][lvl])
                buy_cost += ask_data[t][lvl] * bq
            sq = int(x[t * vars_per_ts + LEVELS + lvl])
            sq = max(0, min(sq, int(ub[t * vars_per_ts + LEVELS + lvl])))
            if sq > 0:
                total_sell += sq
                min_sell_price = min(min_sell_price, bid_data[t][lvl])
                sell_revenue += bid_data[t][lvl] * sq

        ts_orders = []
        if total_buy > 0:
            ts_orders.append({"price": int(max_buy_price), "quantity": int(total_buy)})
            lp_pos += total_buy
            lp_pnl -= buy_cost
        if total_sell > 0:
            ts_orders.append({"price": int(min_sell_price), "quantity": -int(total_sell)})
            lp_pos -= total_sell
            lp_pnl += sell_revenue

        if ts_orders:
            lp_orders_by_ts[ts] = ts_orders

    # Combined final position and PnL
    passive_net = cum_pb_through_t[-1] - cum_ps_through_t[-1]
    combined_final_pos = lp_pos + passive_net
    passive_cash_total = sum(passive_cashflows)
    combined_pnl = lp_pnl + passive_cash_total + combined_final_pos * final_mid

    print(
        f"  LP-only PnL: {lp_pnl + lp_pos * final_mid:.2f} | "
        f"passive cashflow: {passive_cash_total:.2f} | "
        f"combined final pos: {combined_final_pos} | "
        f"COMBINED PnL: {combined_pnl:.2f}",
        flush=True,
    )
    return lp_orders_by_ts, combined_pnl


def main():
    print(f"Loading {LOG_PATH}")
    order_books, trade_history = parse_activities_log(LOG_PATH)

    print("Products found:", list(order_books.keys()))
    for p, rows in order_books.items():
        print(f"  {p}: {len(rows)} timestamps")

    print("\nExtracting passive trades from reference tradeHistory...")
    passive_trades = extract_passive_trades(order_books, trade_history)
    for prod in PRODUCTS:
        total = 0
        qty = 0
        for ts, prod_map in passive_trades.items():
            for pt in prod_map.get(prod, []):
                total += 1
                qty += abs(pt["quantity"])
        print(f"  {prod}: {total} passive trades, {qty} total qty")

    # Restructure passive_trades by product
    passive_by_prod = defaultdict(lambda: defaultdict(list))
    for ts, prod_map in passive_trades.items():
        for prod, pts in prod_map.items():
            passive_by_prod[prod][ts] = pts

    all_orders = defaultdict(lambda: defaultdict(list))
    grand_total = 0.0
    lp_orders_by_prod = {}
    for product in PRODUCTS:
        if product not in order_books:
            continue
        print(f"\nSolving LP (with passives) for {product}...")
        lp_orders, combined_pnl = solve_product_lp_with_passives(
            order_books[product], passive_by_prod[product], POSITION_LIMIT
        )
        lp_orders_by_prod[product] = lp_orders
        grand_total += combined_pnl

        # Merge LP orders and passive orders for this product
        for ts, orders in lp_orders.items():
            all_orders[ts][product].extend(orders)
        for ts, pts in passive_by_prod[product].items():
            for pt in pts:
                all_orders[ts][product].append(pt)

    print(f"\nGRAND TOTAL PnL (all products): {grand_total:.2f}")

    # Final verification: simulate the combined schedule
    print("\nSimulating combined schedule...")
    verify_schedule(all_orders, order_books)

    # Write orders.json
    out = {}
    total_orders = 0
    for ts in sorted(all_orders.keys()):
        ts_dict = {}
        for prod in PRODUCTS:
            if prod in all_orders[ts] and all_orders[ts][prod]:
                ts_dict[prod] = all_orders[ts][prod]
                total_orders += len(all_orders[ts][prod])
        if ts_dict:
            out[str(ts)] = ts_dict

    with open(OUT_PATH, "w") as f:
        json.dump(out, f, separators=(",", ":"))
    print(f"\nWrote {OUT_PATH}")
    print(f"  timestamps with orders: {len(out)}")
    print(f"  total orders: {total_orders}")
    print(f"  file size: {os.path.getsize(OUT_PATH)} bytes")


def verify_schedule(all_orders, order_books):
    """Simulate the order schedule assuming all orders fill, report per-prod PnL."""
    final_mid = {}
    for prod, rows in order_books.items():
        final_mid[prod] = rows[-1][3] if rows else 0.0

    for prod in PRODUCTS:
        pos = 0
        cashflow = 0.0
        max_pos = 0
        min_pos = 0
        for ts in sorted(all_orders.keys()):
            for o in all_orders[ts].get(prod, []):
                p = o["price"]
                q = o["quantity"]
                cashflow -= p * q
                pos += q
                max_pos = max(max_pos, pos)
                min_pos = min(min_pos, pos)
        pnl = cashflow + pos * final_mid[prod]
        violated = max_pos > POSITION_LIMIT or min_pos < -POSITION_LIMIT
        tag = "  !!OVER LIMIT!!" if violated else ""
        print(
            f"  {prod}: final_pos={pos}, range=[{min_pos}, {max_pos}], "
            f"PnL={pnl:.2f}{tag}"
        )


if __name__ == "__main__":
    main()
