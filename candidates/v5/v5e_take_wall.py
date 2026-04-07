"""
v5e: Take up to ask_wall (or down to bid_wall for sells), in limited qty.
Rationale: the walls represent the main bot liquidity levels. Taking to
the wall captures cheap inventory that baseline skips when fair < ask_wall.
Limited by TAKE_WALL_CAP per side per ts to prevent position blowup.
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
TAKE_WALL_CAP = 10  # max extra qty to take up to the wall


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
        # Get walls (from the raw book, since od may not have them any more)
        ask_wall_price = None
        bid_wall_price = None
        if od.buy_orders:
            bid_wall_price = max(od.buy_orders, key=lambda p: od.buy_orders[p])
        if od.sell_orders:
            ask_wall_price = min(od.sell_orders, key=lambda p: -od.sell_orders[p])

        # Normal take: ask < fair
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

        # Extra take: up to the ask_wall (cheap structural reference)
        if ask_wall_price is not None:
            for ask in sorted(od.sell_orders.keys()):
                if ask > ask_wall_price: break
                vol = -od.sell_orders[ask]
                # Cap extra take per side
                extra_room = TAKE_WALL_CAP - bv  # reserve wall-take budget
                qty = min(vol, TOMATOES_LIMIT - pos - bv, max(0, extra_room))
                if qty > 0:
                    orders.append(Order("TOMATOES", ask, qty))
                    bv += qty
                    od.sell_orders[ask] += qty
                    if od.sell_orders[ask] == 0: del od.sell_orders[ask]
        if bid_wall_price is not None:
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                if bid < bid_wall_price: break
                vol = od.buy_orders[bid]
                extra_room = TAKE_WALL_CAP - sv
                qty = min(vol, TOMATOES_LIMIT + pos - sv, max(0, extra_room))
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
