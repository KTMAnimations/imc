"""
IMC Prosperity 4 — Tutorial Round Strategy (v3)
=================================================
Products: EMERALDS (stationary @ 10,000) and TOMATOES (random walk with drift)

v2 → v3 change:
  Position-adjusted passive sizing for TOMATOES only. When heavily
  positioned, reduce size on the adding side to limit worst-case
  inventory build-up during one-directional taker streaks. Prices
  stay the same (preserving edge per fill).

  EMERALDS unchanged from v2 — stationary product, no position risk.

Core approach: quote 1 tick inside existing best bid/ask for price
priority over deep-liquidity makers.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle


class Trader:

    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}

    # ── EMERALDS ─────────────────────────────────────────────────────
    EMERALDS_FAIR = 10_000

    # ── TOMATOES ─────────────────────────────────────────────────────
    TOMATOES_EMA_ALPHA = 0.6

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

        # Phase 1: Take any order priced strictly better than fair
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
        if best_bid is not None and best_ask is not None:
            our_bid = best_bid + 1
            our_ask = best_ask - 1

            our_bid = min(our_bid, fair - 1)
            our_ask = max(our_ask, fair + 1)

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

        # Phase 1: Take mispriced orders (strictly better than fair)
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
        our_bid = best_bid + 1
        our_ask = best_ask - 1
        fair_int = int(round(fair))

        our_bid = min(our_bid, fair_int - 1)
        our_ask = max(our_ask, fair_int + 1)

        buy_room = limit - pos
        sell_room = limit + pos

        # Position-adjusted sizing: gentle reduction on the
        # position-adding side to limit inventory build-up
        base = 20
        frac = pos / limit if limit > 0 else 0
        bid_size = max(1, int(base * (1 - 0.5 * frac)))
        ask_size = max(1, int(base * (1 + 0.5 * frac)))

        if buy_room > 0 and our_bid < our_ask:
            orders.append(Order(product, our_bid, min(bid_size, buy_room)))
        if sell_room > 0 and our_ask > our_bid:
            orders.append(Order(product, our_ask, -min(ask_size, sell_room)))

        return orders, ts