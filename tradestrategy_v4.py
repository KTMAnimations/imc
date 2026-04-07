"""
tradestrategy_v4 — improvements over tradestrategy.py validated against
BOTH backtesters: sim_gui (the in-repo log-based simulator) AND
prosperity4bt (the CLI backtester running raw bundled market data).

Background: v3 used aggressive E_MAKE_EDGE=8 + large blend that worked on
prosperity4bt CLI but tanked sim_gui by ~42% (because sim_gui's passive
liquidity menu has fixed thresholds at exactly 9993/10007 on EMERALDS,
the prices that historical baseline-like strategies got filled at — any
EMERALDS quote outside that range gets zero passive fills in sim_gui).

v4 only uses changes that are STRICT improvements in both backtesters,
verified by a dual-test harness (candidates/_v4_dual.py).

Two changes vs baseline:

Change 1: TOMATOES_PASSIVE_CAP 20 -> 25
----------------------------------------
sim_gui sees no change because its passive menu qty is already capped at
the historical strategies' fill quantities (baseline already captures
~99% of the menu's available qty). prosperity4bt CLI runs against raw
bot trade data which has more volume per ts than the historical logs
ever achieved, so a higher cap captures the extra volume. cap=24-26 are
tied at the CLI optimum of +100 over baseline.

Change 2: TOMATOES fair = 0.80 * wall_mid + 0.20 * bb_mid
----------------------------------------------------------
A small (20%) blend of the visible best-bid/best-ask mid into the
wall-anchored mid. This is the only blend weight that gives a strict
sim_gui improvement (+7.5) without hurting CLI badly. The mechanism is
that on tightened-spread timestamps, fair shifts slightly toward the
visible market, which lets a few more take/clear decisions execute
profitably. Other weights either don't help sim_gui or wreck CLI.

What did NOT make it into v4 (and why)
----------------------------------------
- EMERALDS_MAKE_EDGE=8: +2,136 on CLI but -1,050 on sim_gui (the v3
  story). sim_gui's menu literally cannot rate this quote regime.
- TOMATOES_EMA_ALPHA changes: any deviation from 0.50 hurts CLI.
- TOMATOES_INV_SKEW changes: 0.05 is the joint optimum.
- T_BBMID_WEIGHT outside [0.18, 0.20]: either no sim_gui win or CLI loss.
- T_SOFT/HARD, E_SOFT/HARD: no joint improvement.

Validated results:
                                sim_gui   CLI(round0 both days)
  baseline tradestrategy.py     2715.5    31,116
  v4 (this file)                2723.0    31,216
  delta                           +7.5       +100   (BOTH improve)

CLI per-day:
                       day -2   day -1   total
  baseline             15,360   15,756   31,116
  v4                   15,422   15,794   31,216
  delta                   +62      +38     +100   (both days improve)

Both improvements are small (~0.3% each). The dual constraint is tight:
sim_gui's reconstructed passive menu rejects most quote-price changes,
so the dual feasible set is much smaller than either single-backtester
optimum. v4 picks the highest-scoring point inside that intersection.
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
# v4 change 1: 20 -> 25 (CLI captures more bot trade volume per ts;
# sim_gui unchanged because its menu qty was the binding constraint).
TOMATOES_PASSIVE_CAP = 25
# v4 change 2: 20% blend of bb_mid into wall_mid for the fair input
# (small dual-positive sim_gui win).
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

        # Wall mid: deepest liquidity on each side (stable, bot-anchored)
        bid_wall = max(od.buy_orders.keys(), key=lambda p: od.buy_orders[p])
        ask_wall = min(od.sell_orders.keys(), key=lambda p: -od.sell_orders[p])
        wall_mid = (bid_wall + ask_wall) / 2

        # Visible best-bid/ask mid (responsive to tightened spreads)
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        bb_mid = (best_bid + best_ask) / 2

        # v4 change 2: 20% blend of bb_mid into wall_mid
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
