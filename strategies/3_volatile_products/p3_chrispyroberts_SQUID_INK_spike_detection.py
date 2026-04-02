# ============================================================================
# SOURCE: https://github.com/chrispyroberts/imc-prosperity-3
# TEAM: chrispyroberts - Top-performing team, Prosperity 3
# FILE: ROUND 1/final_round_1_trader.py
#
# KEY SQUID INK STRATEGY (trade_squid + make_squid_market methods):
#   - Dual moving average crossover: short_window=50, long_window=250
#   - Volatility spike detection: rolling std dev on price diffs (window=50)
#   - Flash crash detection: delta_vol > 2 triggers aggressive counter-trade
#   - One-sided market making: only quote buy/sell based on trend direction
#   - Position management: cap at 80% utilization, then revert to two-sided
#
# This is the most sophisticated volatility-aware approach found,
# combining trend following, mean reversion, and crash detection.
# ============================================================================

from typing import List
import numpy as np
import json
from typing import Any
import math

from datamodel import *
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data):
        base_length = len(self.to_json([
            self.compress_state(state, ""),
            self.compress_orders(orders),
            conversions, "", "",
        ]))
        max_item_length = (self.max_log_length - base_length) // 3
        print(self.to_json([
            self.compress_state(state, self.truncate(state.traderData, max_item_length)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item_length),
            self.truncate(self.logs, max_item_length),
        ]))
        self.logs = ""

    def compress_state(self, state, trader_data):
        return [state.timestamp, trader_data,
                self.compress_listings(state.listings),
                self.compress_order_depths(state.order_depths),
                self.compress_trades(state.own_trades),
                self.compress_trades(state.market_trades),
                state.position,
                self.compress_observations(state.observations)]

    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths):
        return {s: [od.buy_orders, od.sell_orders] for s, od in order_depths.items()}

    def compress_trades(self, trades):
        compressed = []
        for arr in trades.values():
            for t in arr:
                compressed.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return compressed

    def compress_observations(self, observations):
        conv = {}
        for product, obs in observations.conversionObservations.items():
            conv[product] = [obs.bidPrice, obs.askPrice, obs.transportFees,
                            obs.exportTariff, obs.importTariff, obs.sugarPrice, obs.sunlightIndex]
        return [observations.plainValueObservations, conv]

    def compress_orders(self, orders):
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
        if len(value) <= max_length:
            return value
        return value[:max_length - 3] + "..."


logger = Logger()


class Trader:
    def __init__(self):
        self.limits = {
            'RAINFOREST_RESIN': 50,
            'SQUID_INK': 50,
            'KELP': 50,
        }
        self.orders = {}
        self.conversions = 0
        self.traderData = "SAMPLE"

        # Resin tracking
        self.resin_buy_orders = 0
        self.resin_sell_orders = 0
        self.resin_position = 0

        # Kelp tracking
        self.kelp_position = 0
        self.kelp_buy_orders = 0
        self.kelp_sell_orders = 0

        # Squid tracking
        self.squid_ink_position = 0
        self.squid_ink_buy_orders = 0
        self.squid_ink_sell_orders = 0

        # =============================================
        # SQUID INK VOLATILITY WINDOWS
        # =============================================
        self.squid_ink_short_window_prices = []   # fast MA (50 ticks)
        self.squid_ink_long_window_prices = []    # slow MA (250 ticks)
        self.volatility_window_price_diffs = []   # rolling diffs for vol

        self.prev_price = None
        self.prev_vol = None

        # =============================================
        # SQUID INK HYPERPARAMS
        # =============================================
        self.volatility_threshold = 2       # baseline vol threshold
        self.volatility_window = 50         # window for rolling std dev
        self.squid_ink_short_window = 50    # fast moving average window
        self.squid_ink_long_window = 250    # slow moving average window

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))
        if msg is not None:
            logger.print(msg)

    def get_product_pos(self, state, product):
        return state.position.get(product, 0)

    def search_buys(self, state, product, acceptable_price, depth=1):
        """Buy from asks below acceptable price."""
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            orders = list(order_depth.sell_orders.items())
            for ask, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(ask) < acceptable_price or (abs(ask - acceptable_price) < 1 and (pos < 0 and abs(pos - amount) < abs(pos))):
                    if product == 'SQUID_INK':
                        size = min(50 - self.squid_ink_position - self.squid_ink_buy_orders, -amount)
                        self.squid_ink_buy_orders += size
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {size} x @ {ask}")
                    elif product == 'RAINFOREST_RESIN':
                        size = min(50 - self.resin_position - self.resin_buy_orders, -amount)
                        self.resin_buy_orders += size
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {size} x @ {ask}")
                    elif product == 'KELP':
                        size = min(50 - self.kelp_position - self.kelp_buy_orders, -amount)
                        self.kelp_buy_orders += size
                        self.send_buy_order(product, ask, size, msg=f"TRADE BUY {size} x @ {ask}")

    def search_sells(self, state, product, acceptable_price, depth=1):
        """Sell to bids above acceptable price."""
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            for bid, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(bid) > acceptable_price or (abs(bid - acceptable_price) < 1 and (pos > 0 and abs(pos - amount) < abs(pos))):
                    if product == 'SQUID_INK':
                        size = min(self.squid_ink_position + 50 - self.squid_ink_sell_orders, amount)
                        self.squid_ink_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {-size} x @ {bid}")
                    elif product == 'RAINFOREST_RESIN':
                        size = min(self.resin_position + 50 - self.resin_sell_orders, amount)
                        self.resin_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {-size} x @ {bid}")
                    elif product == 'KELP':
                        size = min(self.kelp_position + 50 - self.kelp_sell_orders, amount)
                        self.kelp_sell_orders += size
                        self.send_sell_order(product, bid, -size, msg=f"TRADE SELL {-size} x @ {bid}")

    def get_bid(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            for bid, _ in order_depth.buy_orders.items():
                if bid < price:
                    return bid
        return None

    def get_ask(self, state, product, price):
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            for ask, _ in order_depth.sell_orders.items():
                if ask > price:
                    return ask
        return None

    def trade_resin(self, state):
        """Market-making for RAINFOREST_RESIN at fair=10000."""
        self.search_buys(state, 'RAINFOREST_RESIN', 10000, depth=3)
        self.search_sells(state, 'RAINFOREST_RESIN', 10000, depth=3)
        best_ask = self.get_ask(state, 'RAINFOREST_RESIN', 10000)
        best_bid = self.get_bid(state, 'RAINFOREST_RESIN', 10000)
        buy_price = 9996
        sell_price = 10004
        if best_ask is not None and best_bid is not None:
            sell_price = best_ask - 1
            buy_price = best_bid + 1
        max_buy = 50 - self.resin_position - self.resin_buy_orders
        max_sell = self.resin_position + 50 - self.resin_sell_orders
        self.send_sell_order('RAINFOREST_RESIN', sell_price, -max_sell)
        self.send_buy_order('RAINFOREST_RESIN', buy_price, max_buy)

    def trade_kelp(self, state):
        """Market-making for KELP based on wall-mid fair value."""
        order_book = state.order_depths['KELP']
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders
        if len(sell_orders) != 0 and len(buy_orders) != 0:
            ask, _ = list(sell_orders.items())[-1]
            bid, _ = list(buy_orders.items())[-1]
            fair_price = int(math.ceil((ask + bid) / 2))
            decimal_fair_price = (ask + bid) / 2
            self.search_buys(state, 'KELP', decimal_fair_price, depth=3)
            self.search_sells(state, 'KELP', decimal_fair_price, depth=3)
            best_ask = self.get_ask(state, 'KELP', fair_price)
            best_bid = self.get_bid(state, 'KELP', fair_price)
            buy_price = math.floor(decimal_fair_price) - 2
            sell_price = math.ceil(decimal_fair_price) + 2
            if best_ask is not None and best_bid is not None:
                if best_ask - 1 > decimal_fair_price:
                    sell_price = best_ask - 1
                if best_bid + 1 < decimal_fair_price:
                    buy_price = best_bid + 1
            max_buy = 50 - self.kelp_position - self.kelp_buy_orders
            max_sell = self.kelp_position + 50 - self.kelp_sell_orders
            pos = self.get_product_pos(state, 'KELP')
            if not (pos > 0 and float(buy_price) == decimal_fair_price):
                self.send_buy_order('KELP', buy_price, max_buy)
            if not (pos < 0 and float(sell_price) == decimal_fair_price):
                self.send_sell_order('KELP', sell_price, -max_sell)

    def make_squid_market(self, state, sell_side=True, buy_side=True,
                          take_buys=True, take_sells=True, max_pos_percent=1):
        """
        Market-making for SQUID_INK with directional bias control.
        Can disable buy or sell side based on trend signals.
        """
        order_book = state.order_depths['SQUID_INK']
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders

        if len(sell_orders) != 0 and len(buy_orders) != 0:
            ask, _ = list(sell_orders.items())[-1]
            bid, _ = list(buy_orders.items())[-1]
            fair_price = int(math.ceil((ask + bid) / 2))
            decimal_fair_price = (ask + bid) / 2

            if buy_side:
                self.search_buys(state, 'SQUID_INK', decimal_fair_price, depth=3)
            if sell_side:
                self.search_sells(state, 'SQUID_INK', decimal_fair_price, depth=3)

            best_ask = self.get_ask(state, 'SQUID_INK', fair_price)
            best_bid = self.get_bid(state, 'SQUID_INK', fair_price)
            buy_price = math.floor(decimal_fair_price) - 2
            sell_price = math.ceil(decimal_fair_price) + 2

            if best_ask is not None and best_bid is not None:
                if best_ask - 1 > decimal_fair_price:
                    sell_price = best_ask - 1
                if best_bid + 1 < decimal_fair_price:
                    buy_price = best_bid + 1

            maximum_sizing = 50
            max_buy = maximum_sizing - state.position.get("SQUID_INK", 0) - self.squid_ink_buy_orders
            max_sell = state.position.get("SQUID_INK", 0) + maximum_sizing - self.squid_ink_sell_orders
            max_buy = max(0, max_buy)
            max_sell = max(0, max_sell)
            max_pos = 50 * max_pos_percent
            max_buy = min(max_buy, max_pos)
            max_sell = min(max_sell, max_pos)

            if buy_side:
                self.send_buy_order('SQUID_INK', buy_price, max_buy)
            if sell_side:
                self.send_sell_order('SQUID_INK', sell_price, -max_sell)

    def trade_squid(self, state):
        """
        SQUID INK VOLATILE PRODUCT STRATEGY

        Multi-signal approach:
        1. DUAL MOVING AVERAGE CROSSOVER (short=50, long=250):
           - short_mean > long_mean -> uptrend -> disable buy side (only sell)
           - short_mean < long_mean -> downtrend -> disable sell side (only buy)

        2. VOLATILITY SPIKE DETECTION (rolling std of price diffs, window=50):
           - Tracks rolling standard deviation of price changes
           - Uses as regime indicator

        3. FLASH CRASH DETECTION (delta_vol > 2):
           - Monitors change in volatility between ticks
           - If delta_vol > 2: massive volatility spike detected
           - Aggressively trade opposite direction (mean reversion)
           - Price dropped -> buy aggressively (fair_price + 4 edge)
           - Price spiked -> sell aggressively (fair_price - 4 edge)

        4. POSITION GUARD (>80% position utilization):
           - When near position limits, enable both sides of market
           - Prevents getting stuck at max position during volatility
        """
        order_book = state.order_depths['SQUID_INK']
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders

        if len(sell_orders) != 0 and len(buy_orders) != 0:
            ask, _ = list(sell_orders.items())[-1]
            bid, _ = list(buy_orders.items())[-1]
            decimal_fair_price = (ask + bid) / 2

            # Update price windows
            self.squid_ink_long_window_prices.append(decimal_fair_price)
            self.squid_ink_long_window_prices = self.squid_ink_long_window_prices[-self.squid_ink_long_window:]
            self.squid_ink_short_window_prices.append(decimal_fair_price)
            self.squid_ink_short_window_prices = self.squid_ink_short_window_prices[-self.squid_ink_short_window:]

            # Update volatility window
            if self.prev_price is not None:
                price_diff = decimal_fair_price - self.prev_price
                self.volatility_window_price_diffs.append(price_diff)
                self.volatility_window_price_diffs = self.volatility_window_price_diffs[-self.volatility_window:]

            sell_side = True
            buy_side = True

            # Calculate volatility
            volatility = 0
            if len(self.volatility_window_price_diffs) == self.volatility_window:
                volatility = np.std(self.volatility_window_price_diffs)
                logger.print("SQUID_INK: VOLATILITY: " + str(volatility))

            # DUAL MOVING AVERAGE CROSSOVER
            if len(self.squid_ink_long_window_prices) == self.squid_ink_long_window:
                short_mean = np.mean(self.squid_ink_short_window_prices)
                long_mean = np.mean(self.squid_ink_long_window_prices)

                if long_mean < short_mean:
                    # Market uptrending -> only sell side
                    buy_side = False
                    logger.print("SQUID_INK: UP TRENDING, BUY SIDE OFF")
                elif long_mean > short_mean:
                    # Market downtrending -> only buy side
                    sell_side = False
                    logger.print("SQUID_INK: DOWN TRENDING, SELL SIDE OFF")

                # POSITION GUARD
                size = self.get_product_pos(state, 'SQUID_INK')
                squid_pos_size = abs(size / 50)
                if squid_pos_size > 0.8:
                    buy_side = True
                    sell_side = True
                    logger.print("SQUID_INK: NEAR POSITION LIMIT, BOTH SIDES ON")

                # FLASH CRASH DETECTION
                if self.prev_vol is not None:
                    delta_vol = abs(volatility - self.prev_vol)
                    self.prev_vol = volatility
                    logger.print("delta volatility: " + str(delta_vol))

                    if delta_vol > 2:
                        # MASSIVE VOLATILITY SPIKE -> trade opposite direction
                        logger.print("SQUID_INK: HUGE VOL MOVE - MEAN REVERSION TRIGGERED")
                        if self.prev_price > decimal_fair_price:
                            # Price crashed -> BUY aggressively
                            self.search_buys(state, 'SQUID_INK', decimal_fair_price + 4, depth=3)
                        elif self.prev_price < decimal_fair_price:
                            # Price spiked -> SELL aggressively
                            self.search_sells(state, 'SQUID_INK', decimal_fair_price - 4, depth=3)
                else:
                    self.prev_vol = volatility

            # Place market-making orders with directional bias
            self.make_squid_market(state, sell_side=sell_side, buy_side=buy_side, max_pos_percent=1)
            self.prev_price = decimal_fair_price

    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0
        self.resin_position = self.get_product_pos(state, 'RAINFOREST_RESIN')
        self.resin_buy_orders = 0
        self.resin_sell_orders = 0
        self.kelp_position = self.get_product_pos(state, 'KELP')
        self.kelp_buy_orders = 0
        self.kelp_sell_orders = 0
        self.squid_ink_position = self.get_product_pos(state, 'SQUID_INK')
        self.squid_ink_buy_orders = 0
        self.squid_ink_sell_orders = 0
        for product in state.order_depths:
            self.orders[product] = []

    def run(self, state: TradingState):
        self.reset_orders(state)
        self.trade_resin(state)
        self.trade_kelp(state)
        self.trade_squid(state)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData
