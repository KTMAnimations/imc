"""
Generate overfit_trader.py — a single-file Trader for the web backtester
that embeds the orders from orders.json as a Python dict literal and replays
them at each timestamp.
"""

import json
import os

HERE = os.path.dirname(__file__)
ORDERS_PATH = os.path.join(HERE, "orders.json")
OUT_PATH = os.path.join(HERE, "overfit_trader.py")


TEMPLATE = '''from datamodel import OrderDepth, TradingState, Order

# Hardcoded orders: {{ts: {{product: [(price, quantity), ...]}}}}
# Quantity sign: +ve = BUY, -ve = SELL
# Generated from overfit on the 44890 training run.
ORDERS = {orders_literal}


class Trader:
    def run(self, state: TradingState):
        result = {{}}
        ts_orders = ORDERS.get(state.timestamp)
        if ts_orders:
            for symbol, order_list in ts_orders.items():
                if symbol not in state.order_depths:
                    continue
                result[symbol] = [
                    Order(symbol, int(p), int(q)) for p, q in order_list
                ]
        return result, 0, ""
'''


def main():
    with open(ORDERS_PATH, "r") as f:
        orders = json.load(f)

    # Convert to a compact form: {int_ts: {product: [(price, quantity), ...]}}
    compact = {}
    total = 0
    for ts_str, prod_map in orders.items():
        ts = int(ts_str)
        tso = {}
        for prod, order_list in prod_map.items():
            pairs = [(int(o["price"]), int(o["quantity"])) for o in order_list]
            tso[prod] = pairs
            total += len(pairs)
        compact[ts] = tso

    # Pretty-print the dict with one ts per line so it stays readable
    lines = ["{"]
    for ts in sorted(compact.keys()):
        prod_items = []
        for prod in sorted(compact[ts].keys()):
            pairs_str = ", ".join(
                f"({p}, {q})" for p, q in compact[ts][prod]
            )
            prod_items.append(f"'{prod}': [{pairs_str}]")
        lines.append(f"    {ts}: {{{', '.join(prod_items)}}},")
    lines.append("}")
    orders_literal = "\n".join(lines)

    src = TEMPLATE.format(orders_literal=orders_literal)
    with open(OUT_PATH, "w") as f:
        f.write(src)

    size = os.path.getsize(OUT_PATH)
    print(f"Wrote {OUT_PATH} ({size} bytes)")
    print(f"  embedded {total} orders across {len(compact)} timestamps")


if __name__ == "__main__":
    main()
