"""
IMC Prosperity 4 — Tutorial Round Strategy (Optimized)
========================================================
Products: EMERALDS (stationary @ 10,000) and TOMATOES (random walk with drift)

EMERALDS: Market-making at the known fair value of 10,000.
          Take any mispriced orders. Post passive quotes at L1 (9992/10008).

TOMATOES: Adaptive market-making with fast EMA fair-value tracking.
          High alpha EMA closely follows the weighted mid, letting us
          post profitable quotes even during drift. No inventory skew —
          drift exposure is net positive in expectation.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle


class Trader:

    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}

    # ── EMERALDS: fixed fair value, wide passive quotes ──────────────
    EMERALDS_FAIR = 10_000
    EMERALDS_TAKE_WIDTH = 1        # take if price within 1 tick of fair
    EMERALDS_MM_EDGE = 8           # post at 9992/10008 (matches existing L1)

    # ── TOMATOES: fast-tracking EMA, moderate passive quotes ─────────
    TOMATOES_EMA_ALPHA = 0.5       # high alpha = fast fair-value tracking
    TOMATOES_TAKE_WIDTH = 1        # take if price within 1 tick of fair
    TOMATOES_MM_EDGE = 6           # passive offset from estimated fair

    # ── Shared ───────────────────────────────────────────────────────
    MAX_PASSIVE_SIZE = 15

    def bid(self):
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        # ── Deserialize persistent state ─────────────────────────────
        trader_state = {}
        if state.traderData and state.traderData != "":
            try:
                trader_state = jsonpickle.decode(state.traderData)
            except Exception:
                trader_state = {}

        for product in state.order_depths:
            if product == "EMERALDS":
                orders, trader_state = self._trade_emeralds(state, trader_state)
            elif product == "TOMATOES":
                orders, trader_state = self._trade_tomatoes(state, trader_state)
            else:
                orders = []
            result[product] = orders

        trader_data = jsonpickle.encode(trader_state)
        return result, 0, trader_data

    # ==================================================================
    #  EMERALDS — Fixed fair-value market maker
    # ==================================================================
    def _trade_emeralds(self, state: TradingState, ts: dict):
        product = "EMERALDS"
        orders: List[Order] = []
        od: OrderDepth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]
        fair = self.EMERALDS_FAIR

        # Phase 1: Aggressively take any mispriced orders
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > fair - self.EMERALDS_TAKE_WIDTH:
                break
            ask_vol = -od.sell_orders[ask_price]
            can_buy = limit - pos
            if can_buy <= 0:
                break
            qty = min(ask_vol, can_buy)
            orders.append(Order(product, ask_price, qty))
            pos += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < fair + self.EMERALDS_TAKE_WIDTH:
                break
            bid_vol = od.buy_orders[bid_price]
            can_sell = limit + pos
            if can_sell <= 0:
                break
            qty = min(bid_vol, can_sell)
            orders.append(Order(product, bid_price, -qty))
            pos -= qty

        # Phase 2: Post passive quotes at L1 prices
        bid_price = fair - self.EMERALDS_MM_EDGE
        ask_price = fair + self.EMERALDS_MM_EDGE

        buy_room = limit - pos
        sell_room = limit + pos

        if buy_room > 0:
            orders.append(Order(product, bid_price, min(self.MAX_PASSIVE_SIZE, buy_room)))
        if sell_room > 0:
            orders.append(Order(product, ask_price, -min(self.MAX_PASSIVE_SIZE, sell_room)))

        return orders, ts

    # ==================================================================
    #  TOMATOES — Adaptive EMA market maker
    # ==================================================================
    def _trade_tomatoes(self, state: TradingState, ts: dict):
        product = "TOMATOES"
        orders: List[Order] = []
        od: OrderDepth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]

        # Compute volume-weighted mid from order book
        wmid = self._weighted_mid(od)
        if wmid is None:
            return orders, ts

        # Update EMA fair value (fast-tracking)
        ema_key = "tomatoes_ema"
        alpha = self.TOMATOES_EMA_ALPHA
        if ema_key in ts and ts[ema_key] is not None:
            ema = ts[ema_key] * (1 - alpha) + wmid * alpha
        else:
            ema = wmid
        ts[ema_key] = ema
        fair = round(ema, 1)
        fair_int = int(round(fair))

        # Phase 1: Take mispriced orders relative to EMA fair value
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price > fair - self.TOMATOES_TAKE_WIDTH:
                break
            ask_vol = -od.sell_orders[ask_price]
            can_buy = limit - pos
            if can_buy <= 0:
                break
            qty = min(ask_vol, can_buy)
            orders.append(Order(product, ask_price, qty))
            pos += qty

        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price < fair + self.TOMATOES_TAKE_WIDTH:
                break
            bid_vol = od.buy_orders[bid_price]
            can_sell = limit + pos
            if can_sell <= 0:
                break
            qty = min(bid_vol, can_sell)
            orders.append(Order(product, bid_price, -qty))
            pos -= qty

        # Phase 2: Post passive quotes around EMA fair value
        bid_price = fair_int - self.TOMATOES_MM_EDGE
        ask_price = fair_int + self.TOMATOES_MM_EDGE

        buy_room = limit - pos
        sell_room = limit + pos

        if buy_room > 0:
            orders.append(Order(product, bid_price, min(self.MAX_PASSIVE_SIZE, buy_room)))
        if sell_room > 0:
            orders.append(Order(product, ask_price, -min(self.MAX_PASSIVE_SIZE, sell_room)))

        return orders, ts

    # ==================================================================
    #  Helpers
    # ==================================================================
    @staticmethod
    def _weighted_mid(od: OrderDepth) -> float | None:
        """Volume-weighted mid price from best bid/ask."""
        if not od.buy_orders or not od.sell_orders:
            return None
        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())
        bid_vol = od.buy_orders[best_bid]
        ask_vol = -od.sell_orders[best_ask]
        total = bid_vol + ask_vol
        if total == 0:
            return (best_bid + best_ask) / 2
        return (best_bid * ask_vol + best_ask * bid_vol) / total