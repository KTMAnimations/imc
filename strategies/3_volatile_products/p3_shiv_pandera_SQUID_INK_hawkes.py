# ============================================================================
# SOURCE: https://github.com/ShivUCSD1104/IMC-Prosperity-3
# TEAM: Pandera (ShivUCSD1104) - Prosperity 3
# FILE: Final Submissions/round1Final.py
#
# KEY SQUID INK STRATEGY (ink_strategy method):
#   - Autoregressive (ARX) model for Kelp, Hawkes process for Squid Ink
#   - Kelp: 5-lag AR model with spread and order book imbalance features
#   - Squid Ink: Hawkes process intensity model for bid depletion events
#   - Risk threshold based on self-exciting event intensity
#   - When intensity >= threshold OR position at limit -> aggressive short
#   - Otherwise, sweep all available asks (accumulate long)
#
# Notable: This is a very different approach from mean-reversion,
# treating Squid Ink as an event-driven product where large bid volumes
# signal upcoming price drops.
# ============================================================================

from typing import Dict, List
from datamodel import Order, OrderDepth, TradingState
import json
import numpy as np


class Trader:
    def resin_strategy(self, state: TradingState, order_depth: OrderDepth) -> List[Order]:
        """Rainforest Resin: Fixed fair value at 10000 with adaptive liquidation."""
        product = "RAINFOREST_RESIN"
        FAIR_VALUE = 10000
        LIMIT = 50
        WINDOW_SIZE = 10
        MIN_LOCKOUTS = 2

        position = state.position.get(product, 0)
        orders: List[Order] = []

        try:
            trader_data = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            trader_data = {}

        lockout_window = trader_data.get("lockout", [])[-WINDOW_SIZE:]
        lockout_window.append(abs(position) == LIMIT)
        if len(lockout_window) > WINDOW_SIZE:
            lockout_window.pop(0)

        lockout_count = sum(lockout_window)

        buy_orders = sorted(order_depth.buy_orders.items(), reverse=True)
        sell_orders = sorted(order_depth.sell_orders.items())

        buy_vol = LIMIT - position
        sell_vol = LIMIT + position

        max_buy_price = FAIR_VALUE - 1 if position > LIMIT * 0.5 else FAIR_VALUE
        min_sell_price = FAIR_VALUE + 1 if position < -LIMIT * 0.5 else FAIR_VALUE

        # Market taking
        for price, volume in sell_orders:
            if buy_vol > 0 and price <= max_buy_price:
                qty = min(buy_vol, -volume)
                orders.append(Order(product, price, qty))
                buy_vol -= qty

        for price, volume in buy_orders:
            if sell_vol > 0 and price >= min_sell_price:
                qty = min(sell_vol, volume)
                orders.append(Order(product, price, -qty))
                sell_vol -= qty

        # Adaptive forced liquidation
        if lockout_count >= MIN_LOCKOUTS:
            price_delta = max(0, 2 - (lockout_count - MIN_LOCKOUTS))
            liq_buy_price = FAIR_VALUE - price_delta
            liq_sell_price = FAIR_VALUE + price_delta
            if buy_vol > 0:
                orders.append(Order(product, liq_buy_price, buy_vol // 2))
            if sell_vol > 0:
                orders.append(Order(product, liq_sell_price, -sell_vol // 2))

        # Passive quoting
        if buy_vol > 0:
            best_bid = max(buy_orders, key=lambda x: x[1])[0] if buy_orders else FAIR_VALUE - 1
            orders.append(Order(product, min(max_buy_price, best_bid + 1), buy_vol))
        if sell_vol > 0:
            best_ask = min(sell_orders, key=lambda x: x[1])[0] if sell_orders else FAIR_VALUE + 1
            orders.append(Order(product, max(min_sell_price, best_ask - 1), -sell_vol))

        self.resin_lockout_data = {"lockout": lockout_window}
        return orders

    def kelp_strategy(self, state: TradingState, order_depth: OrderDepth, trader_data: Dict) -> List[Order]:
        """
        Kelp: Autoregressive model with order book features.
        Uses 5-lag AR model + spread + imbalance as predictors.
        """
        product = "KELP"
        LIMIT = 50
        position = state.position.get(product, 0)
        orders: List[Order] = []

        buy_orders = sorted(order_depth.sell_orders.items())
        sell_orders = sorted(order_depth.buy_orders.items(), reverse=True)

        kelp_data = trader_data.get("kelp_data_out", {})
        past_prices = kelp_data.get("past_prices", [])

        best_bid = max(order_depth.buy_orders.keys())
        best_ask = min(order_depth.sell_orders.keys())
        mid_price = int(best_bid + best_ask) / 2
        spread = best_ask - best_bid

        bid_vol = sum([v for _, v in buy_orders])
        ask_vol = sum([-v for _, v in sell_orders])
        imbalance = (bid_vol - ask_vol) / (bid_vol + ask_vol) if (bid_vol + ask_vol) > 0 else 0

        past_prices.append(mid_price)

        if len(past_prices) < 5:
            FAIR_VALUE = mid_price
        else:
            # AR(5) model with spread and imbalance features
            # Coefficients fitted on historical data
            coeffs = np.array([0.15251124, 0.15576791, 0.17976303, 0.21362462, 0.29735446,
                               -0.00146693, -0.01186836])
            intercept = 1.9887312933824433
            input_features = list(past_prices[-5:]) + [spread, imbalance]
            FAIR_VALUE = np.dot(coeffs, input_features) + intercept

        # Take mispriced orders
        for ask_price, ask_vol in buy_orders:
            if ask_price < FAIR_VALUE and position < LIMIT:
                vol = min(-ask_vol, LIMIT - position)
                orders.append(Order(product, ask_price, vol))
                position += vol

        for bid_price, bid_vol in sell_orders:
            if bid_price > FAIR_VALUE and position > -LIMIT:
                vol = min(bid_vol, position + LIMIT)
                orders.append(Order(product, bid_price, -vol))
                position -= vol

        # Market making with wide spread
        if spread >= 2:
            buy_price = int(FAIR_VALUE - 2)
            sell_price = int(FAIR_VALUE + 2)
            if position < LIMIT:
                orders.append(Order(product, buy_price, min(25, LIMIT - position)))
            if position > -LIMIT:
                orders.append(Order(product, sell_price, -min(25, position + LIMIT)))

        self.kelp_data_out = {"past_prices": past_prices}
        return orders

    def ink_strategy(self, state: TradingState, order_depth: OrderDepth, trader_data: Dict):
        """
        SQUID INK STRATEGY: Hawkes Process Intensity Model

        This treats Squid Ink as an event-driven product:
        1. Track "depletion events" - when best_bid_volume > 15
           (large bid-side resting orders signal informed selling)
        2. Model arrival intensity using Hawkes process:
           intensity = sum(exp(-(current_time - event_time))) for recent events
        3. Risk management:
           - If position maxed out (50) OR intensity >= threshold (2):
             Aggressively SHORT across all bid levels
           - Otherwise: sweep all available asks (accumulate LONG)

        This is an asymmetric strategy:
        - Default: accumulate long (buy everything)
        - Risk signal: dump everything and go short

        The Hawkes process captures self-exciting behavior where
        large orders cluster together before price drops.
        """
        product = "SQUID_INK"
        LIMIT = 50
        orders: List[Order] = []
        position = state.position.get(product, 0)

        ink_data = trader_data.get("INK", {})
        depletion_timestamps = ink_data.get("depletion_timestamps", [])
        normalized_time = state.timestamp / 100

        buy_orders = sorted(order_depth.sell_orders.items())
        sell_orders = sorted(order_depth.buy_orders.items(), reverse=True)

        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        best_bid_volume = order_depth.buy_orders[best_bid] if best_bid else 0

        # Detect depletion event: large bid volume signals informed selling
        if best_bid_volume > 15:
            depletion_timestamps.append(normalized_time)

        # Hawkes process: exponentially-decaying intensity of events
        intensity = sum(
            np.exp(-(normalized_time - t))
            for t in depletion_timestamps
            if normalized_time - t >= 0
        )

        risk_threshold = 2

        # RISK SIGNAL: position maxed or high Hawkes intensity -> GO SHORT
        if position == 50 or intensity >= risk_threshold:
            for bid_price, bid_vol in sell_orders:
                if position > -LIMIT:
                    vol = bid_vol
                    orders.append(Order(product, bid_price, -vol))
                    position -= vol

        # DEFAULT: accumulate long - sweep all asks
        if position < LIMIT:
            for ask_price, ask_vol in buy_orders:
                if position < LIMIT:
                    vol = ask_vol
                    orders.append(Order(product, ask_price, vol))
                    position += vol

        self.kelp_data_out["INK"] = {"depletion_timestamps": depletion_timestamps[-10:]}
        return orders

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        try:
            trader_data = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            trader_data = {}

        for product in state.order_depths:
            if product == "RAINFOREST_RESIN":
                result[product] = self.resin_strategy(state, state.order_depths[product])
            elif product == "KELP":
                result[product] = self.kelp_strategy(state, state.order_depths[product], trader_data)
            elif product == "SQUID_INK":
                result[product] = self.ink_strategy(state, state.order_depths[product], trader_data)

        traderData = json.dumps({
            "kelp_data_out": getattr(self, "kelp_data_out", {}),
            "lockout_data": getattr(self, "resin_lockout_data", {})
        })

        return result, conversions, traderData
