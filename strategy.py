"""
IMC Prosperity 4 — Tutorial Round Strategy (v2 — platform-corrected)
=====================================================================
Products: EMERALDS (stationary @ 10,000) and TOMATOES (random walk with drift)

Key fix from v1: On the real platform, passive orders at the same price as
existing bot orders never fill (bots have time priority). We must quote
INSIDE the existing spread to get price priority.

EMERALDS: Post tight quotes inside the 9992/10008 spread. Fair = 10,000.
          Bots see our better prices and trade against us.

TOMATOES: Adaptive market-making. Post quotes strictly inside the current
          best bid/ask to guarantee price priority over deep-liquidity makers.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle


class Trader:

    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}

    # ── EMERALDS ─────────────────────────────────────────────────────
    EMERALDS_FAIR = 10_000

    # ── TOMATOES ─────────────────────────────────────────────────────
    TOMATOES_EMA_ALPHA = 0.5       # fast-tracking EMA

    def bid(self):
        return 15

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

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

        best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
        best_ask = min(od.sell_orders.keys()) if od.sell_orders else None

        # Phase 1: Take any order priced better than fair
        # Buy any sell order below fair value
        if od.sell_orders:
            for ask_price in sorted(od.sell_orders.keys()):
                if ask_price >= fair:
                    break
                ask_vol = -od.sell_orders[ask_price]
                can_buy = limit - pos
                if can_buy <= 0:
                    break
                qty = min(ask_vol, can_buy)
                orders.append(Order(product, ask_price, qty))
                pos += qty

        # Sell into any buy order above fair value
        if od.buy_orders:
            for bid_price in sorted(od.buy_orders.keys(), reverse=True):
                if bid_price <= fair:
                    break
                bid_vol = od.buy_orders[bid_price]
                can_sell = limit + pos
                if can_sell <= 0:
                    break
                qty = min(bid_vol, can_sell)
                orders.append(Order(product, bid_price, -qty))
                pos -= qty

        # Phase 2: Post passive quotes INSIDE the existing spread
        # Must be strictly better than existing L1 to get price priority
        if best_bid is not None and best_ask is not None:
            # Post 1 tick inside the existing best bid/ask
            our_bid = best_bid + 1   # e.g., 9993 if best_bid=9992
            our_ask = best_ask - 1   # e.g., 10007 if best_ask=10008

            # Never cross or touch fair value (ensures we profit per fill)
            our_bid = min(our_bid, fair - 1)  # max 9999
            our_ask = max(our_ask, fair + 1)  # min 10001

            buy_room = limit - pos
            sell_room = limit + pos

            if buy_room > 0 and our_bid < our_ask:
                orders.append(Order(product, our_bid, min(20, buy_room)))
            if sell_room > 0 and our_ask > our_bid:
                orders.append(Order(product, our_ask, -min(20, sell_room)))

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

        if not od.buy_orders or not od.sell_orders:
            return orders, ts

        best_bid = max(od.buy_orders.keys())
        best_ask = min(od.sell_orders.keys())

        # Compute volume-weighted mid from order book
        bid_vol = od.buy_orders[best_bid]
        ask_vol = -od.sell_orders[best_ask]
        total_vol = bid_vol + ask_vol
        if total_vol == 0:
            wmid = (best_bid + best_ask) / 2
        else:
            wmid = (best_bid * ask_vol + best_ask * bid_vol) / total_vol

        # Update EMA fair value
        ema_key = "tomatoes_ema"
        alpha = self.TOMATOES_EMA_ALPHA
        if ema_key in ts and ts[ema_key] is not None:
            ema = ts[ema_key] * (1 - alpha) + wmid * alpha
        else:
            ema = wmid
        ts[ema_key] = ema
        fair = ema

        # Phase 1: Take mispriced orders
        # Buy any sell order below our fair value
        for ask_price in sorted(od.sell_orders.keys()):
            if ask_price >= fair:
                break
            ask_vol = -od.sell_orders[ask_price]
            can_buy = limit - pos
            if can_buy <= 0:
                break
            qty = min(ask_vol, can_buy)
            orders.append(Order(product, ask_price, qty))
            pos += qty

        # Sell into any buy order above our fair value
        for bid_price in sorted(od.buy_orders.keys(), reverse=True):
            if bid_price <= fair:
                break
            bid_vol = od.buy_orders[bid_price]
            can_sell = limit + pos
            if can_sell <= 0:
                break
            qty = min(bid_vol, can_sell)
            orders.append(Order(product, bid_price, -qty))
            pos -= qty

        # Phase 2: Post passive quotes INSIDE the existing spread
        # 1 tick better than existing best bid/ask for price priority
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        fair_int = int(round(fair))

        # Don't cross our estimated fair value
        our_bid = min(our_bid, fair_int - 1)
        our_ask = max(our_ask, fair_int + 1)

        buy_room = limit - pos
        sell_room = limit + pos

        if buy_room > 0 and our_bid < our_ask:
            orders.append(Order(product, our_bid, min(20, buy_room)))
        if sell_room > 0 and our_ask > our_bid:
            orders.append(Order(product, our_ask, -min(20, sell_room)))

        return orders, ts
