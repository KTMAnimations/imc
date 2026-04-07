"""
tradestrategy_v3 — improvements over tradestrategy.py validated with the
prosperity4bt CLI backtester (NOT sim_gui).

Background: my first pass at v3 used sim_gui to tune parameters. Two of
the three changes I picked that way turned out to be simulator noise when
verified against the CLI backtester — one was a regression. The sim_gui
still has residual bias even after the phantom-liquidity fix, because its
"passive menu" is reconstructed from historical logs that all ran variants
of this baseline. Any candidate that moves *into* a price regime the
historical logs didn't cover gets zero evidence from the menu, so sim_gui
either under- or over-rates it.

The prosperity4bt CLI runs the strategy against the RAW bundled price and
trade data (10000 ts/day × 2 days for round 0), matching orders against
bot-to-bot market trades at OUR quote price. This gives a direct, faithful
ground truth.

Two CLI-validated changes vs baseline. Both days of round 0 improve;
total delta +2,551 (+8.2%).

Change 1: EMERALDS_MAKE_EDGE 7 -> 8                             [main win]
-----------------------------------------------------------------
Baseline quoted at 10000 +- 7 (9993 / 10007). v3 quotes at 10000 +- 8
(9992 / 10008). The CLI matches passive orders at OUR quote price against
market trades with `trade_price <= our_bid` (for BUY) / `>= our_ask`
(for SELL). Every bot-to-bot EMERALDS trade happens at some price <= 9993,
so both edges catch essentially the same set of trades, but at edge=8 we
pay 1 tick LESS per share (9992 vs 9993) and receive 1 tick MORE per
share (10008 vs 10007). Net: roughly +1 tick per fill × thousands of
fills = +2,136 profit across the two days. Edge=9 gives zero EMERALDS
fills because bid 9991 and ask 10009 fall outside the bulk of the trade
distribution.

This was the biggest win and sim_gui missed it entirely — sim_gui's
passive menu contained threshold_prices of exactly 9993 and 10007 (from
the historical logs, which all ran edge=7), so quoting at 9992/10008
"missed" every menu entry in sim_gui. That was a pure artifact of the
menu being a reconstruction, not reality.

Change 2: TOMATOES fair mid = 0.90 * wall_mid + 0.10 * bb_mid   [smaller]
-----------------------------------------------------------------
Baseline uses only wall_mid. A small (10%) weight toward the visible
best_bid/best_ask mid makes fair track tightened visible spreads instead
of being stuck on the deep walls. On top of change 1 this adds another
+415 to the combined total.

Everything else is unchanged
-----------------------------
CLI sweeps of every other parameter (TOMATOES_EMA_ALPHA, TOMATOES_INV_SKEW,
TOMATOES_SOFT/HARD, TOMATOES_PASSIVE_CAP, EMERALDS_TAKE_WIDTH,
EMERALDS_CLEAR_WIDTH, EMERALDS_SOFT/HARD) confirmed baseline values are
at or near the optimum. Notably, TOMATOES_EMA_ALPHA=0.5 is clearly best;
my earlier sim_gui-picked 0.4 was a regression.

CLI results (prosperity4bt round 0, both days merged):
                      d-2      d-1     total
  baseline         15,360   15,756    31,116
  v3 (this file)   16,519   17,148    33,667   (+2,551, +8.2%)

Both days improve, confirming this is not overfit to a single market.
"""

from datamodel import OrderDepth, TradingState, Order
import json
import math

# ---- EMERALDS ----
EMERALDS_LIMIT = 80
EMERALDS_FAIR = 10000
EMERALDS_TAKE_WIDTH = 1
EMERALDS_CLEAR_WIDTH = 0
# v3 change 1: 7 -> 8 (see module docstring)
EMERALDS_MAKE_EDGE = 8
EMERALDS_SOFT_LIMIT = 35
EMERALDS_HARD_LIMIT = 60

# ---- TOMATOES ----
TOMATOES_LIMIT = 80
TOMATOES_EMA_ALPHA = 0.5
TOMATOES_INV_SKEW = 0.05
TOMATOES_SOFT_LIMIT = 40
TOMATOES_HARD_LIMIT = 60
TOMATOES_PASSIVE_CAP = 20
# v3 change 2: blend bb_mid into the wall_mid-based fair (see module docstring)
TOMATOES_BBMID_WEIGHT = 0.10


class Trader:

    def tomatoes_clear_price(self, fair, net):
        if net >= TOMATOES_HARD_LIMIT:
            return math.floor(fair) - 1
        if net >= TOMATOES_SOFT_LIMIT:
            return math.floor(fair)
        if net <= -TOMATOES_HARD_LIMIT:
            return math.ceil(fair) + 1
        if net <= -TOMATOES_SOFT_LIMIT:
            return math.ceil(fair)
        return round(fair)

    def tomatoes_quote_prices(self, od, fair, eff_pos):
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        if best_bid is None or best_ask is None:
            return None, None

        max_bid = math.ceil(fair) - 1
        min_ask = math.floor(fair) + 1

        if eff_pos <= -TOMATOES_SOFT_LIMIT:
            max_bid += 1
        if eff_pos <= -TOMATOES_HARD_LIMIT:
            max_bid += 1
        if eff_pos >= TOMATOES_SOFT_LIMIT:
            min_ask -= 1
        if eff_pos >= TOMATOES_HARD_LIMIT:
            min_ask -= 1

        bid_ceiling = min(max_bid, best_ask - 1)
        ask_floor = max(min_ask, best_bid + 1)

        if bid_ceiling <= best_bid or ask_floor >= best_ask:
            return None, None

        normal_bid = min(best_bid + 1, bid_ceiling)
        normal_ask = max(best_ask - 1, ask_floor)

        if eff_pos <= -TOMATOES_HARD_LIMIT:
            bid = bid_ceiling
        elif eff_pos <= -TOMATOES_SOFT_LIMIT:
            bid = min(bid_ceiling, normal_bid + 1)
        else:
            bid = normal_bid

        if eff_pos >= TOMATOES_HARD_LIMIT:
            ask = ask_floor
        elif eff_pos >= TOMATOES_SOFT_LIMIT:
            ask = max(ask_floor, normal_ask - 1)
        else:
            ask = normal_ask

        return bid, ask

    # ---- EMERALDS ----

    def emeralds_take(self, od, pos, bv, sv):
        orders = []
        for ask in sorted(od.sell_orders.keys()):
            if ask > EMERALDS_FAIR - EMERALDS_TAKE_WIDTH:
                break
            vol = -od.sell_orders[ask]
            qty = min(vol, EMERALDS_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("EMERALDS", ask, qty))
                bv += qty
                od.sell_orders[ask] += qty
                if od.sell_orders[ask] == 0:
                    del od.sell_orders[ask]

        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid < EMERALDS_FAIR + EMERALDS_TAKE_WIDTH:
                break
            vol = od.buy_orders[bid]
            qty = min(vol, EMERALDS_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("EMERALDS", bid, -qty))
                sv += qty
                od.buy_orders[bid] -= qty
                if od.buy_orders[bid] == 0:
                    del od.buy_orders[bid]

        return orders, bv, sv

    def emeralds_clear(self, od, pos, bv, sv):
        orders = []
        net = pos + bv - sv

        if net > 0:
            price = EMERALDS_FAIR + EMERALDS_CLEAR_WIDTH
            avail = sum(v for p, v in od.buy_orders.items() if p >= price)
            qty = min(avail, net, EMERALDS_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("EMERALDS", price, -qty))
                sv += qty

        elif net < 0:
            price = EMERALDS_FAIR - EMERALDS_CLEAR_WIDTH
            avail = sum(-v for p, v in od.sell_orders.items() if p <= price)
            qty = min(avail, -net, EMERALDS_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("EMERALDS", price, qty))
                bv += qty

        return orders, bv, sv

    def emeralds_make(self, pos, bv, sv):
        orders = []
        bid = EMERALDS_FAIR - EMERALDS_MAKE_EDGE
        ask = EMERALDS_FAIR + EMERALDS_MAKE_EDGE

        if pos > EMERALDS_SOFT_LIMIT:
            ask -= 1
        if pos > EMERALDS_HARD_LIMIT:
            ask -= 2
        if pos < -EMERALDS_SOFT_LIMIT:
            bid += 1
        if pos < -EMERALDS_HARD_LIMIT:
            bid += 2

        buy_qty = EMERALDS_LIMIT - pos - bv
        if buy_qty > 0:
            orders.append(Order("EMERALDS", bid, buy_qty))
        sell_qty = EMERALDS_LIMIT + pos - sv
        if sell_qty > 0:
            orders.append(Order("EMERALDS", ask, -sell_qty))

        return orders

    def trade_emeralds(self, state):
        pos = state.position.get("EMERALDS", 0)
        od = state.order_depths["EMERALDS"]
        bv = sv = 0

        take, bv, sv = self.emeralds_take(od, pos, bv, sv)
        clear, bv, sv = self.emeralds_clear(od, pos, bv, sv)
        make = self.emeralds_make(pos, bv, sv)

        return take + clear + make

    # ---- TOMATOES ----

    def tomatoes_fair(self, od, pos, trader_data):
        if not od.sell_orders or not od.buy_orders:
            return None, trader_data

        # Wall mid: deepest liquidity on each side (stable, bot-anchored)
        bid_wall = max(od.buy_orders.keys(), key=lambda p: od.buy_orders[p])
        ask_wall = min(od.sell_orders.keys(), key=lambda p: -od.sell_orders[p])
        wall_mid = (bid_wall + ask_wall) / 2

        # Visible best-bid/ask mid (responsive to tightened spreads)
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        bb_mid = (best_bid + best_ask) / 2

        # v3 change 2: small blend (10%) of bb_mid into wall_mid.
        blended_mid = (1 - TOMATOES_BBMID_WEIGHT) * wall_mid + TOMATOES_BBMID_WEIGHT * bb_mid

        alpha = TOMATOES_EMA_ALPHA
        prev = trader_data.get("tomatoes_ema")
        if prev is not None:
            ema = prev * (1 - alpha) + blended_mid * alpha
        else:
            ema = blended_mid
        trader_data["tomatoes_ema"] = ema

        # Inventory-adjusted fair: shifts against position to encourage unwinding
        fair = ema - TOMATOES_INV_SKEW * pos

        return fair, trader_data

    def tomatoes_take(self, od, fair, pos, bv, sv):
        orders = []
        # Aggressive: take anything strictly below fair
        for ask in sorted(od.sell_orders.keys()):
            if ask >= fair:
                break
            vol = -od.sell_orders[ask]
            qty = min(vol, TOMATOES_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("TOMATOES", ask, qty))
                bv += qty
                od.sell_orders[ask] += qty
                if od.sell_orders[ask] == 0:
                    del od.sell_orders[ask]

        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid <= fair:
                break
            vol = od.buy_orders[bid]
            qty = min(vol, TOMATOES_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("TOMATOES", bid, -qty))
                sv += qty
                od.buy_orders[bid] -= qty
                if od.buy_orders[bid] == 0:
                    del od.buy_orders[bid]

        return orders, bv, sv

    def tomatoes_clear(self, od, fair, pos, bv, sv):
        orders = []
        net = pos + bv - sv

        if net > 0:
            price = self.tomatoes_clear_price(fair, net)
            avail = sum(v for p, v in od.buy_orders.items() if p >= price)
            qty = min(avail, net, TOMATOES_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("TOMATOES", price, -qty))
                sv += qty

        elif net < 0:
            price = self.tomatoes_clear_price(fair, net)
            avail = sum(-v for p, v in od.sell_orders.items() if p <= price)
            qty = min(avail, -net, TOMATOES_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("TOMATOES", price, qty))
                bv += qty

        return orders, bv, sv

    def tomatoes_make(self, od, fair, pos, bv, sv):
        orders = []

        eff_pos = pos + bv - sv
        bid, ask = self.tomatoes_quote_prices(od, fair, eff_pos)
        if bid is None or ask is None:
            return orders

        # Inventory-aware sizing: scale down the side that builds inventory
        half = TOMATOES_LIMIT // 2
        base = TOMATOES_PASSIVE_CAP

        if eff_pos >= half:
            bid_cap = 0
        elif eff_pos > 0:
            bid_cap = max(1, int(base * (1 - eff_pos / half)))
        else:
            bid_cap = base

        if eff_pos <= -half:
            ask_cap = 0
        elif eff_pos < 0:
            ask_cap = max(1, int(base * (1 + eff_pos / half)))
        else:
            ask_cap = base

        buy_qty = min(bid_cap, TOMATOES_LIMIT - pos - bv)
        sell_qty = min(ask_cap, TOMATOES_LIMIT + pos - sv)

        if buy_qty > 0:
            orders.append(Order("TOMATOES", bid, buy_qty))
        if sell_qty > 0:
            orders.append(Order("TOMATOES", ask, -sell_qty))

        return orders

    def trade_tomatoes(self, state, trader_data):
        pos = state.position.get("TOMATOES", 0)
        od = state.order_depths["TOMATOES"]

        fair, trader_data = self.tomatoes_fair(od, pos, trader_data)
        if fair is None:
            return [], trader_data

        bv = sv = 0
        take, bv, sv = self.tomatoes_take(od, fair, pos, bv, sv)
        clear, bv, sv = self.tomatoes_clear(od, fair, pos, bv, sv)
        make = self.tomatoes_make(od, fair, pos, bv, sv)

        return take + clear + make, trader_data

    # ---- RUN ----

    def run(self, state: TradingState):
        result = {}

        trader_data = {}
        if state.traderData:
            try:
                trader_data = json.loads(state.traderData)
            except:
                trader_data = {}

        if "EMERALDS" in state.order_depths:
            result["EMERALDS"] = self.trade_emeralds(state)

        if "TOMATOES" in state.order_depths:
            tomatoes_orders, trader_data = self.trade_tomatoes(state, trader_data)
            result["TOMATOES"] = tomatoes_orders

        return result, 0, json.dumps(trader_data)
