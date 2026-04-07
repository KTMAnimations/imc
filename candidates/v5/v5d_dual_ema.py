"""
v5d: Dual EMA on TOMATOES. Track both a fast EMA (alpha=0.5) and a slow
EMA (alpha=0.05, ~20-ts effective horizon). Take asks below the MAX of
fast and slow; sell bids above the MIN. This should capture dip
opportunities where fast drops but slow is still high (dip-buy pattern).
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
TOMATOES_EMA_FAST = 0.5
TOMATOES_EMA_SLOW = 0.05
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

    def tomatoes_quote_prices(self, od, fair, eff_pos):
        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
        if best_bid is None or best_ask is None: return None, None
        max_bid = math.ceil(fair) - 1
        min_ask = math.floor(fair) + 1
        if eff_pos <= -TOMATOES_SOFT_LIMIT: max_bid += 1
        if eff_pos <= -TOMATOES_HARD_LIMIT: max_bid += 1
        if eff_pos >= TOMATOES_SOFT_LIMIT: min_ask -= 1
        if eff_pos >= TOMATOES_HARD_LIMIT: min_ask -= 1
        bid_ceiling = min(max_bid, best_ask - 1)
        ask_floor = max(min_ask, best_bid + 1)
        if bid_ceiling <= best_bid or ask_floor >= best_ask: return None, None
        normal_bid = min(best_bid + 1, bid_ceiling)
        normal_ask = max(best_ask - 1, ask_floor)
        if eff_pos <= -TOMATOES_HARD_LIMIT: bid = bid_ceiling
        elif eff_pos <= -TOMATOES_SOFT_LIMIT: bid = min(bid_ceiling, normal_bid + 1)
        else: bid = normal_bid
        if eff_pos >= TOMATOES_HARD_LIMIT: ask = ask_floor
        elif eff_pos >= TOMATOES_SOFT_LIMIT: ask = max(ask_floor, normal_ask - 1)
        else: ask = normal_ask
        return bid, ask

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
        orders = []; net = pos + bv - sv
        if net > 0:
            price = EMERALDS_FAIR + EMERALDS_CLEAR_WIDTH
            avail = sum(v for p, v in od.buy_orders.items() if p >= price)
            qty = min(avail, net, EMERALDS_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("EMERALDS", price, -qty)); sv += qty
        elif net < 0:
            price = EMERALDS_FAIR - EMERALDS_CLEAR_WIDTH
            avail = sum(-v for p, v in od.sell_orders.items() if p <= price)
            qty = min(avail, -net, EMERALDS_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("EMERALDS", price, qty)); bv += qty
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
        if not od.sell_orders or not od.buy_orders: return None, None, trader_data
        bid_wall = max(od.buy_orders.keys(), key=lambda p: od.buy_orders[p])
        ask_wall = min(od.sell_orders.keys(), key=lambda p: -od.sell_orders[p])
        wall_mid = (bid_wall + ask_wall) / 2

        prev_fast = trader_data.get("tomatoes_ema_fast")
        prev_slow = trader_data.get("tomatoes_ema_slow")
        fast = prev_fast*(1-TOMATOES_EMA_FAST) + wall_mid*TOMATOES_EMA_FAST if prev_fast is not None else wall_mid
        slow = prev_slow*(1-TOMATOES_EMA_SLOW) + wall_mid*TOMATOES_EMA_SLOW if prev_slow is not None else wall_mid
        trader_data["tomatoes_ema_fast"] = fast
        trader_data["tomatoes_ema_slow"] = slow

        # Inventory-adjusted
        fair_fast = fast - TOMATOES_INV_SKEW * pos
        fair_slow = slow - TOMATOES_INV_SKEW * pos
        return fair_fast, fair_slow, trader_data

    def tomatoes_take(self, od, fair_fast, fair_slow, pos, bv, sv):
        orders = []
        # Take if ask below max of fast/slow (catches dips where fast dropped)
        take_fair = max(fair_fast, fair_slow)
        sell_fair = min(fair_fast, fair_slow)
        for ask in sorted(od.sell_orders.keys()):
            if ask >= take_fair: break
            vol = -od.sell_orders[ask]
            qty = min(vol, TOMATOES_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("TOMATOES", ask, qty))
                bv += qty
                od.sell_orders[ask] += qty
                if od.sell_orders[ask] == 0: del od.sell_orders[ask]
        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid <= sell_fair: break
            vol = od.buy_orders[bid]
            qty = min(vol, TOMATOES_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("TOMATOES", bid, -qty))
                sv += qty
                od.buy_orders[bid] -= qty
                if od.buy_orders[bid] == 0: del od.buy_orders[bid]
        return orders, bv, sv

    def tomatoes_clear(self, od, fair, pos, bv, sv):
        orders = []; net = pos + bv - sv
        if net > 0:
            price = self.tomatoes_clear_price(fair, net)
            avail = sum(v for p, v in od.buy_orders.items() if p >= price)
            qty = min(avail, net, TOMATOES_LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order("TOMATOES", price, -qty)); sv += qty
        elif net < 0:
            price = self.tomatoes_clear_price(fair, net)
            avail = sum(-v for p, v in od.sell_orders.items() if p <= price)
            qty = min(avail, -net, TOMATOES_LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order("TOMATOES", price, qty)); bv += qty
        return orders, bv, sv

    def tomatoes_make(self, od, fair, pos, bv, sv):
        orders = []
        eff_pos = pos + bv - sv
        bid, ask = self.tomatoes_quote_prices(od, fair, eff_pos)
        if bid is None or ask is None: return orders
        half = TOMATOES_LIMIT // 2
        base = TOMATOES_PASSIVE_CAP
        if eff_pos >= half: bid_cap = 0
        elif eff_pos > 0: bid_cap = max(1, int(base * (1 - eff_pos / half)))
        else: bid_cap = base
        if eff_pos <= -half: ask_cap = 0
        elif eff_pos < 0: ask_cap = max(1, int(base * (1 + eff_pos / half)))
        else: ask_cap = base
        buy_qty = min(bid_cap, TOMATOES_LIMIT - pos - bv)
        sell_qty = min(ask_cap, TOMATOES_LIMIT + pos - sv)
        if buy_qty > 0: orders.append(Order("TOMATOES", bid, buy_qty))
        if sell_qty > 0: orders.append(Order("TOMATOES", ask, -sell_qty))
        return orders

    def trade_tomatoes(self, state, trader_data):
        pos = state.position.get("TOMATOES", 0)
        od = state.order_depths["TOMATOES"]
        fair_fast, fair_slow, trader_data = self.tomatoes_fair(od, pos, trader_data)
        if fair_fast is None: return [], trader_data
        bv = sv = 0
        take, bv, sv = self.tomatoes_take(od, fair_fast, fair_slow, pos, bv, sv)
        # Use fast for clear and make (consistency with baseline)
        clear, bv, sv = self.tomatoes_clear(od, fair_fast, pos, bv, sv)
        make = self.tomatoes_make(od, fair_fast, pos, bv, sv)
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
