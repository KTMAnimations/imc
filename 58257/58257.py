"""
tradestrategy_v3 — improvement over tradestrategy.py, validated against the
fixed sim_gui simulator (which previously over-credited phantom liquidity).

Two principled changes, both in the TOMATOES fair-value model. Everything
else — take, clear, make, EMERALDS, sizing, inventory logic — is identical
to the baseline because parameter sweeps against the fixed simulator showed
baseline is near-optimal on every other axis.

Change 1: fair mid = 0.75 * wall_mid + 0.25 * bb_mid
----------------------------------------------------
Baseline uses ONLY wall_mid (midpoint of the deepest bid and ask levels).
Wall_mid is stable but anchors the fair value to the bots' resting levels,
which can lag the visible market when a narrower best_bid/best_ask prints
inside the walls. A small blend with (best_bid + best_ask) / 2 makes the
fair track tightened spreads without giving up the wall's noise-robustness.
25% is the sweet spot: more gives too much noise, less gives no lift.

Change 2: T_EMA_ALPHA 0.5 -> 0.4
--------------------------------
With the blended input, the fair is slightly more responsive per-tick than
before, so the EMA is slowed to keep the overall time constant similar.
0.4 empirically paired best with the 0.25 blend.

Why this is NOT the tradestrategy_v2 overfit pattern
-----------------------------------------------------
v2's "wins" came from the simulator's phantom passive liquidity — v2
quoted wider and got filled at stale historical prices that v2 itself
would never have seen in reality. The simulator has been fixed: passive
orders now fill at OUR quote price and passive-menu entries are
deduplicated per (ts, side) instead of per (ts, side, price). Under the
fixed simulator v2 scores ~1625 (matching its real-world 1621).

v3's changes were validated two ways:
1. Per-log consistency: v3 beats baseline on 16/17 single-log runs
   (+31.5 on most, +97.5 and +116.5 on two "low-performing" outlier
   logs, one -12 regression). Mean single-log delta = +35.4 per log,
   aggregated delta = +31.5 — they agree, which means the improvement
   is NOT driven by cross-log aggregation artifacts (that was the v2
   pattern: big aggregated gains with no per-log gains).
2. Holdout: on overfit/58011/58011.log (not in the training set) v3
   also beats baseline by +31.5, matching the in-sample improvement.

Numbers (fixed simulator, 17 day=-1 logs):
  baseline: agg=2715.5  mean=2457.7  min=869.0
  v3:       agg=2747.0  mean=2493.1  min=899.5    (all three improved)
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
# v3: slower EMA paired with the blended mid input (see Change 2 above).
TOMATOES_EMA_ALPHA = 0.4
TOMATOES_INV_SKEW = 0.05
TOMATOES_SOFT_LIMIT = 40
TOMATOES_HARD_LIMIT = 60
TOMATOES_PASSIVE_CAP = 20
# v3: fair = (1 - W) * wall_mid + W * bb_mid. See Change 1 above.
TOMATOES_BBMID_WEIGHT = 0.25


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

        # Visible best-bid/ask mid (responsive, tracks tightened spreads)
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        bb_mid = (best_bid + best_ask) / 2

        # v3 change: blend the two mids. wall_mid remains the dominant anchor;
        # the 25% bb_mid weight lifts fair into any narrower visible market.
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