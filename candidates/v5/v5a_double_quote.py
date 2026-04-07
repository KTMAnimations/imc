"""
v5a: Double-quote TOMATOES make phase.
Submits two bid orders (at best_bid+1 AND at bid_ceiling if different)
and two ask orders (at best_ask-1 AND at ask_floor if different).
The idea: cheaper quote catches entries it matches; wider quote catches
higher-threshold entries the cheaper quote can't reach.
"""
from datamodel import OrderDepth, TradingState, Order
import json
import math

EMERALDS_LIMIT = 80
EMERALDS_FAIR = 10000
EMERALDS_TAKE_WIDTH = 1
EMERALDS_CLEAR_WIDTH = 0
EMERALDS_MAKE_EDGE = 7
EMERALDS_SOFT_LIMIT = 35
EMERALDS_HARD_LIMIT = 60

TOMATOES_LIMIT = 80
TOMATOES_EMA_ALPHA = 0.5
TOMATOES_INV_SKEW = 0.05
TOMATOES_SOFT_LIMIT = 40
TOMATOES_HARD_LIMIT = 60
TOMATOES_PASSIVE_CAP = 20


class Trader:

    def tomatoes_clear_price(self, fair, net):
        if net >= TOMATOES_HARD_LIMIT: return math.floor(fair) - 1
        if net >= TOMATOES_SOFT_LIMIT: return math.floor(fair)
        if net <= -TOMATOES_HARD_LIMIT: return math.ceil(fair) + 1
        if net <= -TOMATOES_SOFT_LIMIT: return math.ceil(fair)
        return round(fair)

    def emeralds_take(self, od, pos, bv, sv):
        orders = []
        for ask in sorted(od.sell_orders.keys()):
            if ask > EMERALDS_FAIR - EMERALDS_TAKE_WIDTH: break
            vol = -od.sell_orders[ask]
            qty = min(vol, EMERALDS_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("EMERALDS", ask, qty))
                bv += qty
                od.sell_orders[ask] += qty
                if od.sell_orders[ask] == 0: del od.sell_orders[ask]
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid < EMERALDS_FAIR + EMERALDS_TAKE_WIDTH: break
            vol = od.buy_orders[bid]
            qty = min(vol, EMERALDS_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("EMERALDS", bid, -qty))
                sv += qty
                od.buy_orders[bid] -= qty
                if od.buy_orders[bid] == 0: del od.buy_orders[bid]
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
        if pos > EMERALDS_SOFT_LIMIT: ask -= 1
        if pos > EMERALDS_HARD_LIMIT: ask -= 2
        if pos < -EMERALDS_SOFT_LIMIT: bid += 1
        if pos < -EMERALDS_HARD_LIMIT: bid += 2
        buy_qty = EMERALDS_LIMIT - pos - bv
        if buy_qty > 0: orders.append(Order("EMERALDS", bid, buy_qty))
        sell_qty = EMERALDS_LIMIT + pos - sv
        if sell_qty > 0: orders.append(Order("EMERALDS", ask, -sell_qty))
        return orders

    def trade_emeralds(self, state):
        pos = state.position.get("EMERALDS", 0)
        od = state.order_depths["EMERALDS"]
        bv = sv = 0
        take, bv, sv = self.emeralds_take(od, pos, bv, sv)
        clear, bv, sv = self.emeralds_clear(od, pos, bv, sv)
        make = self.emeralds_make(pos, bv, sv)
        return take + clear + make

    def tomatoes_fair(self, od, pos, trader_data):
        if not od.sell_orders or not od.buy_orders: return None, trader_data
        bid_wall = max(od.buy_orders.keys(), key=lambda p: od.buy_orders[p])
        ask_wall = min(od.sell_orders.keys(), key=lambda p: -od.sell_orders[p])
        wall_mid = (bid_wall + ask_wall) / 2
        alpha = TOMATOES_EMA_ALPHA
        prev = trader_data.get("tomatoes_ema")
        ema = prev*(1-alpha) + wall_mid*alpha if prev is not None else wall_mid
        trader_data["tomatoes_ema"] = ema
        fair = ema - TOMATOES_INV_SKEW * pos
        return fair, trader_data

    def tomatoes_take(self, od, fair, pos, bv, sv):
        orders = []
        for ask in sorted(od.sell_orders.keys()):
            if ask >= fair: break
            vol = -od.sell_orders[ask]
            qty = min(vol, TOMATOES_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("TOMATOES", ask, qty))
                bv += qty
                od.sell_orders[ask] += qty
                if od.sell_orders[ask] == 0: del od.sell_orders[ask]
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid <= fair: break
            vol = od.buy_orders[bid]
            qty = min(vol, TOMATOES_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("TOMATOES", bid, -qty))
                sv += qty
                od.buy_orders[bid] -= qty
                if od.buy_orders[bid] == 0: del od.buy_orders[bid]
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
        """v5a: submit both a 'cheap' quote at best_bid+1/best_ask-1 AND
        a 'wide' quote at bid_ceiling/ask_floor if they're different."""
        orders = []
        if not od.buy_orders or not od.sell_orders:
            return orders
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())

        max_bid = math.ceil(fair) - 1
        min_ask = math.floor(fair) + 1

        eff_pos = pos + bv - sv
        if eff_pos <= -TOMATOES_SOFT_LIMIT: max_bid += 1
        if eff_pos <= -TOMATOES_HARD_LIMIT: max_bid += 1
        if eff_pos >= TOMATOES_SOFT_LIMIT: min_ask -= 1
        if eff_pos >= TOMATOES_HARD_LIMIT: min_ask -= 1

        bid_ceiling = min(max_bid, best_ask - 1)
        ask_floor = max(min_ask, best_bid + 1)

        if bid_ceiling <= best_bid or ask_floor >= best_ask:
            return orders

        # "cheap" quotes — at best_bid+1 / best_ask-1
        cheap_bid = min(best_bid + 1, bid_ceiling)
        cheap_ask = max(best_ask - 1, ask_floor)

        # "wide" quotes — at bid_ceiling / ask_floor (higher bid, lower ask)
        wide_bid = bid_ceiling
        wide_ask = ask_floor

        # Sizing
        half = TOMATOES_LIMIT // 2
        base = TOMATOES_PASSIVE_CAP
        if eff_pos >= half: bid_cap = 0
        elif eff_pos > 0: bid_cap = max(1, int(base * (1 - eff_pos / half)))
        else: bid_cap = base
        if eff_pos <= -half: ask_cap = 0
        elif eff_pos < 0: ask_cap = max(1, int(base * (1 + eff_pos / half)))
        else: ask_cap = base

        buy_budget = min(bid_cap, TOMATOES_LIMIT - pos - bv)
        sell_budget = min(ask_cap, TOMATOES_LIMIT + pos - sv)

        # Submit cheap first (consumes low-threshold menu entries at low price),
        # then wide (catches higher-threshold entries the cheap missed).
        if buy_budget > 0:
            orders.append(Order("TOMATOES", cheap_bid, buy_budget))
            if wide_bid != cheap_bid:
                orders.append(Order("TOMATOES", wide_bid, buy_budget))
        if sell_budget > 0:
            orders.append(Order("TOMATOES", cheap_ask, -sell_budget))
            if wide_ask != cheap_ask:
                orders.append(Order("TOMATOES", wide_ask, -sell_budget))

        return orders

    def trade_tomatoes(self, state, trader_data):
        pos = state.position.get("TOMATOES", 0)
        od = state.order_depths["TOMATOES"]
        fair, trader_data = self.tomatoes_fair(od, pos, trader_data)
        if fair is None: return [], trader_data
        bv = sv = 0
        take, bv, sv = self.tomatoes_take(od, fair, pos, bv, sv)
        clear, bv, sv = self.tomatoes_clear(od, fair, pos, bv, sv)
        make = self.tomatoes_make(od, fair, pos, bv, sv)
        return take + clear + make, trader_data

    def run(self, state: TradingState):
        result = {}
        trader_data = {}
        if state.traderData:
            try: trader_data = json.loads(state.traderData)
            except: trader_data = {}
        if "EMERALDS" in state.order_depths:
            result["EMERALDS"] = self.trade_emeralds(state)
        if "TOMATOES" in state.order_depths:
            tom, trader_data = self.trade_tomatoes(state, trader_data)
            result["TOMATOES"] = tom
        return result, 0, json.dumps(trader_data)
