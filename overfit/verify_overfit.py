"""
Simulate overfit_trader.py against the 44890 order book and estimate the
expected PnL on the web-based backtester.

Mechanics mirror the IMC Prosperity matching rules:
  - BUY(sym, price, qty) matches sell_orders with price' <= price, from
    cheapest level up, paying the level prices.
  - SELL(sym, price, qty) matches buy_orders with price' >= price, from
    highest bid down, receiving the level prices.
  - Any residual becomes passive and is matched against 'bot trades' that we
    model from the reference tradeHistory: at ts=T, if our passive BUY is
    priced >= ref_trade_price and ref_trade was a BUY (ie. bot sold at that
    price), we fill. Similarly for sells.

  Since we derive the passive-fill schedule directly from the reference
  tradeHistory, the simulation captures the replicated passive fills exactly.

This is a best-effort simulator — the real web backtester may differ in
subtle ways, but it should give a good estimate.
"""

import json
import os
import sys
from collections import defaultdict

HERE = os.path.dirname(__file__)
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from datamodel import OrderDepth, TradingState, Order
import overfit_trader

LOG_PATH = os.path.join(ROOT, "44890", "44890.log")
POSITION_LIMIT = 80


def build_timeline(log_path):
    with open(log_path, "r") as f:
        data = json.load(f)

    # Parse order book per (ts, product)
    books = defaultdict(dict)  # ts -> product -> (bids:[(p,v)], asks:[(p,v)])
    timestamps = set()
    for l in data["activitiesLog"].strip().split("\n")[1:]:
        parts = l.split(";")
        if len(parts) < 17:
            continue
        ts = int(parts[1])
        prod = parts[2]
        bids = []
        asks = []
        for i in range(3):
            bp = parts[3 + 2 * i]
            bv = parts[4 + 2 * i]
            ap = parts[9 + 2 * i]
            av = parts[10 + 2 * i]
            if bp and bv:
                bids.append((int(bp), int(bv)))
            if ap and av:
                asks.append((int(ap), int(av)))
        books[ts][prod] = {"bids": dict(bids), "asks": dict(asks)}
        timestamps.add(ts)

    # Classify reference trades as passive fills available at each ts
    tops = {}
    for ts, prods in books.items():
        for prod, ob in prods.items():
            bb = max(ob["bids"].keys()) if ob["bids"] else None
            ba = min(ob["asks"].keys()) if ob["asks"] else None
            tops[(ts, prod)] = (bb, ba)

    ref_passive = defaultdict(lambda: defaultdict(list))
    for t in data["tradeHistory"]:
        ts = t["timestamp"]
        prod = t["symbol"]
        price = int(t["price"])
        qty = int(t["quantity"])
        side = "BUY" if t["buyer"] == "SUBMISSION" else "SELL"
        bb, ba = tops.get((ts, prod), (None, None))
        if bb is None or ba is None:
            continue
        is_aggressive = (side == "BUY" and price >= ba) or (
            side == "SELL" and price <= bb
        )
        if is_aggressive:
            continue
        ref_passive[ts][prod].append((side, price, qty))

    return sorted(timestamps), books, ref_passive


def simulate():
    timestamps, books, ref_passive = build_timeline(LOG_PATH)
    trader = overfit_trader.Trader()

    position = defaultdict(int)
    cashflow = 0.0
    product_cash = defaultdict(float)
    product_pos = defaultdict(int)
    final_mid = {}

    for ts in timestamps:
        prods = books[ts]
        order_depths = {}
        for prod, ob in prods.items():
            od = OrderDepth()
            od.buy_orders = dict(ob["bids"])
            od.sell_orders = {p: -v for p, v in ob["asks"].items()}
            order_depths[prod] = od
            final_mid[prod] = (max(ob["bids"]) + min(ob["asks"])) / 2 if ob["bids"] and ob["asks"] else 0

        state = TradingState(
            traderData="",
            timestamp=ts,
            listings={},
            order_depths=order_depths,
            own_trades={},
            market_trades={},
            position=dict(position),
            observations=None,
        )
        result, _, _ = trader.run(state)

        for sym, orders in result.items():
            ob = books[ts].get(sym)
            if ob is None:
                continue
            asks = dict(ob["asks"])
            bids = dict(ob["bids"])
            for order in orders:
                price = order.price
                qty = order.quantity
                if qty > 0:
                    # BUY: take asks at prices <= price, cheapest first
                    remaining = qty
                    for ap in sorted(asks.keys()):
                        if ap > price:
                            break
                        if remaining <= 0:
                            break
                        fill = min(remaining, asks[ap])
                        cashflow -= ap * fill
                        product_cash[sym] -= ap * fill
                        position[sym] += fill
                        product_pos[sym] += fill
                        asks[ap] -= fill
                        remaining -= fill
                    # Any residual is passive; try to match against ref_passive BUYs
                    if remaining > 0:
                        residual = remaining
                        new_list = []
                        for side, rp_price, rp_qty in ref_passive[ts].get(sym, []):
                            if side == "BUY" and residual > 0 and rp_price <= price:
                                fill = min(residual, rp_qty)
                                cashflow -= rp_price * fill
                                product_cash[sym] -= rp_price * fill
                                position[sym] += fill
                                product_pos[sym] += fill
                                residual -= fill
                                if fill < rp_qty:
                                    new_list.append((side, rp_price, rp_qty - fill))
                            else:
                                new_list.append((side, rp_price, rp_qty))
                        ref_passive[ts][sym] = new_list
                elif qty < 0:
                    # SELL: hit bids at prices >= price, highest first
                    remaining = -qty
                    for bp in sorted(bids.keys(), reverse=True):
                        if bp < price:
                            break
                        if remaining <= 0:
                            break
                        fill = min(remaining, bids[bp])
                        cashflow += bp * fill
                        product_cash[sym] += bp * fill
                        position[sym] -= fill
                        product_pos[sym] -= fill
                        bids[bp] -= fill
                        remaining -= fill
                    if remaining > 0:
                        residual = remaining
                        new_list = []
                        for side, rp_price, rp_qty in ref_passive[ts].get(sym, []):
                            if side == "SELL" and residual > 0 and rp_price >= price:
                                fill = min(residual, rp_qty)
                                cashflow += rp_price * fill
                                product_cash[sym] += rp_price * fill
                                position[sym] -= fill
                                product_pos[sym] -= fill
                                residual -= fill
                                if fill < rp_qty:
                                    new_list.append((side, rp_price, rp_qty - fill))
                            else:
                                new_list.append((side, rp_price, rp_qty))
                        ref_passive[ts][sym] = new_list

    # Final PnL including liquidation at final mid
    total_pnl = 0.0
    print("\nSimulation results:")
    for prod in sorted(product_cash.keys()):
        pnl = product_cash[prod] + product_pos[prod] * final_mid[prod]
        total_pnl += pnl
        print(
            f"  {prod}: final_pos={product_pos[prod]}, "
            f"cashflow={product_cash[prod]:.2f}, "
            f"liquidation={product_pos[prod]*final_mid[prod]:.2f}, "
            f"PnL={pnl:.2f}"
        )
    print(f"  TOTAL PnL: {total_pnl:.2f}")


if __name__ == "__main__":
    simulate()
