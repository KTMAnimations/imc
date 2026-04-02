"""
IMC Prosperity 4 — Tutorial Round Strategy (v3 — Optimized)
============================================================
Products: EMERALDS (stationary @ 10,000) and TOMATOES (random walk)

Key improvements over v2:
- EMERALDS: Inventory clearing at fair value — when the taker bot posts at
  10,000 (~3.3% of ticks), trade at zero edge to reduce position magnitude.
  This lowers mark-to-market risk and frees capacity for profitable fills.
- TOMATOES: Wall Mid fair value — uses max-volume bid/ask prices (deep
  liquidity makers) instead of noisy L1 volume-weighted mid. Filters out
  temporary taker-bot distortions that cause the EMA to overshoot.
- Both: Full remaining position capacity on passive quotes (was capped at 20).
- Both: Proper aggregate volume tracking across takes + makes to ensure
  position limit compliance without leaving capacity on the table.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle


class Trader:

    POSITION_LIMITS = {"EMERALDS": 80, "TOMATOES": 80}

    # ── EMERALDS ─────────────────────────────────────────────────────
    EMERALDS_FAIR = 10_000

    # ── TOMATOES ─────────────────────────────────────────────────────
    TOMATOES_EMA_ALPHA = 0.5       # fast-tracking EMA on wall mid input

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
    #  EMERALDS — Fixed fair-value MM with inventory clearing
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

        # Track aggregate buy/sell volume for position limit compliance.
        # The exchange cancels ALL orders if pos + total_buys > limit
        # or -pos + total_sells > limit.
        agg_buy = 0
        agg_sell = 0

        # ── Phase 1: Take orders strictly better than fair ──
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

        # ── Phase 2: Inventory clearing at fair value ──
        # The taker bot posts at exactly 10,000 ~330 times/day (5-10 units).
        # Trade at zero edge to reduce |position|, lowering MTM risk and
        # freeing capacity for profitable passive fills.
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

        # ── Phase 3: Passive quotes inside spread ──
        # 1 tick inside existing best bid/ask for price priority over bots.
        # Never cross or touch fair (ensures positive edge per fill).
        buy_room = limit - pos - agg_buy
        sell_room = limit + pos - agg_sell

        if best_bid is not None and best_ask is not None:
            our_bid = min(best_bid + 1, fair - 1)
            our_ask = max(best_ask - 1, fair + 1)

            if buy_room > 0 and our_bid < our_ask:
                orders.append(Order(product, our_bid, buy_room))
            if sell_room > 0 and our_ask > our_bid:
                orders.append(Order(product, our_ask, -sell_room))

        return orders, ts

    # ==================================================================
    #  TOMATOES — Adaptive MM with wall-mid fair value
    # ==================================================================
    def _trade_tomatoes(self, state: TradingState, ts: dict):
        product = "TOMATOES"
        orders: List[Order] = []
        od: OrderDepth = state.order_depths[product]
        pos = state.position.get(product, 0)
        limit = self.POSITION_LIMITS[product]

        if not od.buy_orders or not od.sell_orders:
            return orders, ts

        best_bid = max(od.buy_orders)
        best_ask = min(od.sell_orders)

        # ── Fair value: Wall Mid ──
        # Use the max-volume bid and ask prices as anchors. These are the
        # deep liquidity makers (~17-20 units at L2) whose prices are far
        # more stable than L1 (~7 units). This filters out temporary
        # taker-bot distortions that shift L1 and cause the EMA to
        # overshoot, reducing adverse fills.
        wall_bid = max(od.buy_orders, key=lambda p: od.buy_orders[p])
        # sell_orders values are negative; most negative = largest volume
        wall_ask = min(od.sell_orders, key=lambda p: od.sell_orders[p])
        wmid = (wall_bid + wall_ask) / 2.0

        # Smooth with EMA
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

        # ── Phase 1: Take mispriced orders ──
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

        # ── Phase 2: Passive quotes inside spread ──
        buy_room = limit - pos - agg_buy
        sell_room = limit + pos - agg_sell

        fair_int = int(round(fair))
        our_bid = min(best_bid + 1, fair_int - 1)
        our_ask = max(best_ask - 1, fair_int + 1)

        if buy_room > 0 and our_bid < our_ask:
            orders.append(Order(product, our_bid, buy_room))
        if sell_room > 0 and our_ask > our_bid:
            orders.append(Order(product, our_ask, -sell_room))

        return orders, ts