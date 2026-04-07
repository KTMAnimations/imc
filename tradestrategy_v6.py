"""
tradestrategy_v6 — robust tutorial-round strategy chosen for joint
improvement across all available backtests.

Why v6 is not "v5 plus more"
----------------------------
v5's fixed-anchor TOMATOES position targeting beats the historical
round-0 backtests by a large margin, but it loses badly in the external
Monte Carlo backtester. That is the expected failure mode for a strategy
that hardcodes an absolute price anchor into a process that is closer to
random-walk / regime-switching under simulation.

v6 therefore reverts to the strongest *portable* point found in testing:
the v4 family. Among the candidates tested locally, the exact v4 logic
was the best robust configuration:

  baseline tradestrategy.py
    sim_gui aggregated: 2715.5
    prosperity4bt CLI:  31,116
    prosperity4mcbt:    16,663.85 mean total PnL (100 sessions)

  v6 (this file)
    sim_gui aggregated: 2723.0   (+7.5)
    prosperity4bt CLI:  31,216   (+100)
    prosperity4mcbt:    16,724.91 mean total PnL (+61.06)

Design choices retained
-----------------------
1. TOMATOES_PASSIVE_CAP = 25
   Captures extra tutorial-day bot volume in the CLI backtester without
   hurting the other backtests.

2. TOMATOES fair = 0.80 * wall_mid + 0.20 * bb_mid
   A small blend toward the visible best-bid / best-ask mid improves
   take/clear timing slightly while remaining robust in Monte Carlo.

What is intentionally excluded
------------------------------
- Fixed absolute price anchors or target-position logic
- Trend / drift offsets
- More aggressive EMERALDS quoting

Those variants improved one backtest at the expense of another. v6 is
the stable point that clears all three evaluation surfaces.
"""

from datamodel import OrderDepth, TradingState, Order
import json
import math

# ---- EMERALDS (unchanged from baseline) ----
EMERALDS_LIMIT = 80
EMERALDS_FAIR = 10000
EMERALDS_TAKE_WIDTH = 1
EMERALDS_CLEAR_WIDTH = 0
EMERALDS_MAKE_EDGE = 7
EMERALDS_SOFT_LIMIT = 35
EMERALDS_HARD_LIMIT = 60

# ---- TOMATOES ----
TOMATOES_LIMIT = 80
TOMATOES_EMA_ALPHA = 0.5
TOMATOES_INV_SKEW = 0.05
TOMATOES_SOFT_LIMIT = 40
TOMATOES_HARD_LIMIT = 60
TOMATOES_PASSIVE_CAP = 25
TOMATOES_BBMID_WEIGHT = 0.20


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

        bid_wall = max(od.buy_orders.keys(), key=lambda p: od.buy_orders[p])
        ask_wall = min(od.sell_orders.keys(), key=lambda p: -od.sell_orders[p])
        wall_mid = (bid_wall + ask_wall) / 2

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        bb_mid = (best_bid + best_ask) / 2

        blended_mid = (1 - TOMATOES_BBMID_WEIGHT) * wall_mid + TOMATOES_BBMID_WEIGHT * bb_mid

        alpha = TOMATOES_EMA_ALPHA
        prev = trader_data.get("tomatoes_ema")
        if prev is not None:
            ema = prev * (1 - alpha) + blended_mid * alpha
        else:
            ema = blended_mid
        trader_data["tomatoes_ema"] = ema

        fair = ema - TOMATOES_INV_SKEW * pos

        return fair, trader_data

    def tomatoes_take(self, od, fair, pos, bv, sv):
        orders = []
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
