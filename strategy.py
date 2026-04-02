"""
IMC Prosperity 4 — Tutorial Round Strategy (v6)
================================================
Products: EMERALDS (stationary @ 10,000) and TOMATOES (random walk)

Retains v5 bug fixes, removes inventory sizing and fair adjustment that
caused -86 regression on real test. The sizing ramp (zero at |pos|>=40)
prevented profitable position building during a late rally, accounting
for 65 of the 86 deficit. For a random walk, inventory management has
zero expected PnL — it trades reduced variance for reduced return.
Position limits already cap maximum exposure.

Bug fixes retained from v5:
- ceil(fair)-1 / floor(fair)+1 for strictly-profitable TOMATOES bounds
- Skip passive quote when fair-bound clamp pushes behind existing best
- agg_buy/agg_sell for correct TOMATOES position limit tracking
- EMERALDS inventory clearing at fair value
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle
import math


class Trader:

    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}

    EMERALDS_FAIR = 10_000

    TOMATOES_EMA_ALPHA = 0.5

    PASSIVE_CAP = 20

    def bid(self):
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        ts = {}
        if state.traderData and state.traderData != "":
            try:
                ts = jsonpickle.decode(state.traderData)
            except Exception:
                ts = {}

        for product in state.order_depths:
            if product == "EMERALDS":
                orders, ts = self._trade_emeralds(state, ts)
            elif product == "TOMATOES":
                orders, ts = self._trade_tomatoes(state, ts)
            else:
                orders = []
            result[product] = orders

        return result, 0, jsonpickle.encode(ts)

    # ==================================================================
    #  EMERALDS
    # ==================================================================
    def _trade_emeralds(self, state: TradingState, ts: dict):
        product = "EMERALDS"
        orders: List[Order] = []
        od: OrderDepth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]
        fair = self.EMERALDS_FAIR

        best_bid = max(od.buy_orders) if od.buy_orders else None
        best_ask = min(od.sell_orders) if od.sell_orders else None

        agg_buy = 0
        agg_sell = 0

        # Phase 1: Take strictly better than fair
        if od.sell_orders:
            for ask_price in sorted(od.sell_orders):
                if ask_price >= fair:
                    break
                vol = -od.sell_orders[ask_price]
                room = limit - pos - agg_buy
                if room <= 0:
                    break
                qty = min(vol, room)
                orders.append(Order(product, ask_price, qty))
                agg_buy += qty

        if od.buy_orders:
            for bid_price in sorted(od.buy_orders, reverse=True):
                if bid_price <= fair:
                    break
                vol = od.buy_orders[bid_price]
                room = limit + pos - agg_sell
                if room <= 0:
                    break
                qty = min(vol, room)
                orders.append(Order(product, bid_price, -qty))
                agg_sell += qty

        # Phase 2: Inventory clearing at fair
        eff_pos = pos + agg_buy - agg_sell

        if eff_pos < 0 and fair in od.sell_orders:
            vol = -od.sell_orders[fair]
            room = limit - pos - agg_buy
            clear = min(vol, room, -eff_pos)
            if clear > 0:
                orders.append(Order(product, fair, clear))
                agg_buy += clear

        if eff_pos > 0 and fair in od.buy_orders:
            vol = od.buy_orders[fair]
            room = limit + pos - agg_sell
            clear = min(vol, room, eff_pos)
            if clear > 0:
                orders.append(Order(product, fair, -clear))
                agg_sell += clear

        # Phase 3: Passive quotes
        buy_room = limit - pos - agg_buy
        sell_room = limit + pos - agg_sell
        bid_size = min(self.PASSIVE_CAP, buy_room)
        ask_size = min(self.PASSIVE_CAP, sell_room)

        if best_bid is not None and best_ask is not None:
            our_bid = min(best_bid + 1, fair - 1)
            our_ask = max(best_ask - 1, fair + 1)

            # Only post if we have price priority (strictly inside spread)
            if bid_size > 0 and our_bid > best_bid:
                orders.append(Order(product, our_bid, bid_size))
            if ask_size > 0 and our_ask < best_ask:
                orders.append(Order(product, our_ask, -ask_size))

        return orders, ts

    # ==================================================================
    #  TOMATOES
    # ==================================================================
    def _trade_tomatoes(self, state: TradingState, ts: dict):
        product = "TOMATOES"
        orders: List[Order] = []
        od: OrderDepth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]

        if not od.buy_orders or not od.sell_orders:
            return orders, ts

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())

        # L1 volume-weighted mid
        bid_vol = od.buy_orders[best_bid]
        ask_vol = -od.sell_orders[best_ask]
        total_vol = bid_vol + ask_vol
        if total_vol == 0:
            wmid = (best_bid + best_ask) / 2
        else:
            wmid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol

        # EMA fair value
        ema_key = "tomatoes_ema"
        alpha = self.TOMATOES_EMA_ALPHA
        if ema_key in ts and ts[ema_key] is not None:
            ema = ts[ema_key] * (1 - alpha) + wmid * alpha
        else:
            ema = wmid
        ts[ema_key] = ema
        fair = ema

        agg_buy = 0
        agg_sell = 0

        # Phase 1: Take mispriced orders
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price >= fair:
                break
            vol = -od.sell_orders[ask_price]
            room = limit - pos - agg_buy
            if room <= 0:
                break
            qty = min(vol, room)
            orders.append(Order(product, ask_price, qty))
            agg_buy += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            vol = od.buy_orders[bid_price]
            room = limit + pos - agg_sell
            if room <= 0:
                break
            qty = min(vol, room)
            orders.append(Order(product, bid_price, -qty))
            agg_sell += qty

        # Phase 2: Passive quotes
        buy_room = limit - pos - agg_buy
        sell_room = limit + pos - agg_sell

        # Strictly-profitable bounds (fix: ceil/floor, not round)
        max_bid = math.ceil(fair) - 1
        min_ask = math.floor(fair) + 1

        our_bid = min(best_bid + 1, max_bid)
        our_ask = max(best_ask - 1, min_ask)

        bid_size = min(self.PASSIVE_CAP, buy_room)
        ask_size = min(self.PASSIVE_CAP, sell_room)

        # Only post if we have price priority
        if bid_size > 0 and our_bid > best_bid:
            orders.append(Order(product, our_bid, bid_size))
        if ask_size > 0 and our_ask < best_ask:
            orders.append(Order(product, our_ask, -ask_size))

        return orders, ts
