"""
SOURCE: CMU Physics (Chris Roberts, Nirav Koley, Aditya Dabeer, Timur Takhtarov)
       7th Place Global, 1st Place USA, IMC Prosperity 3
REPO: https://github.com/chrispyroberts/imc-prosperity-3
FILE: ROUND 1/final_round_1_trader.py
PRODUCT: KELP (trending/drifting product), SQUID_INK (high volatility drifting)

KEY TECHNIQUES FOR KELP:
- "Wall mid" fair value: uses WORST bid + WORST ask (deepest liquidity) to
  identify the persistent market maker. This eliminates noise from small orders.
- Market making around fair value: take any mispriced orders, then penny the
  best competing bid/ask that's below/above fair
- Position-aware: won't buy at fair when already long, won't sell at fair when short

KEY TECHNIQUES FOR SQUID_INK (their final version):
- Short/long window moving average crossover (50 vs 250 periods)
- Disables one side of market making when trend is detected:
  - Up-trending: disables buy side (only sells)
  - Down-trending: disables sell side (only buys)
- Volatility tracking with delta-volatility flash crash detection
- Safety: re-enables both sides when near position limit (80%+)
"""

from typing import List
import string
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

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
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
            for o in arr:
                compressed.append([o.symbol, o.price, o.quantity])
        return compressed

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
        if len(value) <= max_length: return value
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

        # Resin
        self.resin_buy_orders = 0
        self.resin_sell_orders = 0
        self.resin_position = 0

        # Kelp
        self.kelp_position = 0
        self.kelp_buy_orders = 0
        self.kelp_sell_orders = 0

        # squid
        self.squid_ink_position = 0
        self.squid_ink_buy_orders = 0
        self.squid_ink_sell_orders = 0

        # windows for trend detection
        self.squid_ink_short_window_prices = []
        self.squid_ink_long_window_prices = []
        self.volatility_window_price_diffs = []

        self.prev_price = None
        self.prev_vol = None

        # squid hyperparams
        self.volatility_threshold = 2
        self.volatility_window = 50
        self.squid_ink_short_window = 50
        self.squid_ink_long_window = 250

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None: logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, int(price), amount))
        if msg is not None: logger.print(msg)

    def get_product_pos(self, state, product):
        return state.position.get(product, 0)

    def search_buys(self, state, product, acceptable_price, depth=1):
        """Take any asks that are below our acceptable price."""
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            orders = list(order_depth.sell_orders.items())
            for ask, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(ask) < acceptable_price or (abs(ask - acceptable_price) < 1 and (pos < 0 and abs(pos - amount) < abs(pos))):
                    if product == 'RAINFOREST_RESIN':
                        size = min(50-self.resin_position-self.resin_buy_orders, -amount)
                        self.resin_buy_orders += size
                        self.send_buy_order(product, ask, size)
                    elif product == 'KELP':
                        size = min(50-self.kelp_position-self.kelp_buy_orders, -amount)
                        self.kelp_buy_orders += size
                        self.send_buy_order(product, ask, size)
                    elif product == 'SQUID_INK':
                        size = min(50-self.squid_ink_position-self.squid_ink_buy_orders, -amount)
                        self.squid_ink_buy_orders += size
                        self.send_buy_order(product, ask, size)

    def search_sells(self, state, product, acceptable_price, depth=1):
        """Take any bids that are above our acceptable price."""
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            orders = list(order_depth.buy_orders.items())
            for bid, amount in orders[0:max(len(orders), depth)]:
                pos = self.get_product_pos(state, product)
                if int(bid) > acceptable_price or (abs(bid-acceptable_price) < 1 and (pos > 0 and abs(pos - amount) < abs(pos))):
                    if product == 'RAINFOREST_RESIN':
                        size = min(self.resin_position + 50 - self.resin_sell_orders, amount)
                        self.resin_sell_orders += size
                        self.send_sell_order(product, bid, -size)
                    elif product == 'KELP':
                        size = min(self.kelp_position + 50 - self.kelp_sell_orders, amount)
                        self.kelp_sell_orders += size
                        self.send_sell_order(product, bid, -size)
                    elif product == 'SQUID_INK':
                        size = min(self.squid_ink_position + 50 - self.squid_ink_sell_orders, amount)
                        self.squid_ink_sell_orders += size
                        self.send_sell_order(product, bid, -size)

    def get_bid(self, state, product, price):
        """Find best bid that's below our target price (for pennying)."""
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) != 0:
            for bid, _ in order_depth.buy_orders.items():
                if bid < price:
                    return bid
        return None

    def get_ask(self, state, product, price):
        """Find best ask that's above our target price (for pennying)."""
        order_depth = state.order_depths[product]
        if len(order_depth.sell_orders) != 0:
            for ask, _ in order_depth.sell_orders.items():
                if ask > price:
                    return ask
        return None

    def trade_resin(self, state):
        """Rainforest Resin: static fair value at 10000."""
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
        """
        KELP STRATEGY - KEY TRENDING PRODUCT APPROACH:

        Fair value = midpoint of WORST bid and WORST ask.
        The worst bid/ask correspond to the persistent market maker's deep quotes,
        which track the true price as it drifts.

        Then: take mispriced orders + penny competing quotes.
        """
        position = state.position.get("KELP", 0)

        order_book = state.order_depths['KELP']
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders

        if len(sell_orders) != 0 and len(buy_orders) != 0:
            # WORST ask and WORST bid = market maker's wall quotes
            ask, _ = list(sell_orders.items())[-1]  # worst ask (highest)
            bid, _ = list(buy_orders.items())[-1]   # worst bid (lowest)

            fair_price = int(math.ceil((ask + bid) / 2))
            decimal_fair_price = (ask + bid) / 2

            logger.print(f"KELP FAIR PRICE: {decimal_fair_price}")

            # Phase 1: Take any mispriced orders
            self.search_buys(state, 'KELP', decimal_fair_price, depth=3)
            self.search_sells(state, 'KELP', decimal_fair_price, depth=3)

            # Phase 2: Find best competing quotes to penny
            best_ask = self.get_ask(state, 'KELP', fair_price)
            best_bid = self.get_bid(state, 'KELP', fair_price)

            # Default spread: fair -2 / fair +2
            buy_price = math.floor(decimal_fair_price) - 2
            sell_price = math.ceil(decimal_fair_price) + 2

            # Penny the competition if they're offering better prices
            if best_ask is not None and best_bid is not None:
                if best_ask - 1 > decimal_fair_price:
                    sell_price = best_ask - 1
                if best_bid + 1 < decimal_fair_price:
                    buy_price = best_bid + 1

            max_buy = 50 - self.kelp_position - self.kelp_buy_orders
            max_sell = self.kelp_position + 50 - self.kelp_sell_orders

            pos = self.get_product_pos(state, 'KELP')
            # Position-aware: don't add to position if buy/sell price IS the fair price
            if not(pos > 0 and float(buy_price) == decimal_fair_price):
                self.send_buy_order('KELP', buy_price, max_buy)

            if not(pos < 0 and float(sell_price) == decimal_fair_price):
                self.send_sell_order('KELP', sell_price, -max_sell)

    def trade_squid(self, state):
        """
        SQUID INK STRATEGY - TRENDING WITH VOLATILITY:

        Uses dual moving average crossover to detect trends:
        - Short window (50): recent price tendency
        - Long window (250): longer-term baseline

        When short > long: UPTREND -> disable buy-side market making
        When short < long: DOWNTREND -> disable sell-side market making

        Also detects flash crashes via delta-volatility spikes and
        aggressively trades the reversal.
        """
        order_book = state.order_depths['SQUID_INK']
        sell_orders = order_book.sell_orders
        buy_orders = order_book.buy_orders

        if len(sell_orders) != 0 and len(buy_orders) != 0:
            ask, _ = list(sell_orders.items())[-1]
            bid, _ = list(buy_orders.items())[-1]
            decimal_fair_price = (ask + bid) / 2

            # Maintain moving average windows
            self.squid_ink_long_window_prices.append(decimal_fair_price)
            self.squid_ink_long_window_prices = self.squid_ink_long_window_prices[-self.squid_ink_long_window:]
            self.squid_ink_short_window_prices.append(decimal_fair_price)
            self.squid_ink_short_window_prices = self.squid_ink_short_window_prices[-self.squid_ink_short_window:]

            if self.prev_price is not None:
                price_diff = decimal_fair_price - self.prev_price
                self.volatility_window_price_diffs.append(price_diff)
                self.volatility_window_price_diffs = self.volatility_window_price_diffs[-self.volatility_window:]

            sell_side = True
            buy_side = True

            # Check volatility
            volatility = 0
            if len(self.volatility_window_price_diffs) == self.volatility_window:
                volatility = np.std(self.volatility_window_price_diffs)

            # Trend detection via moving average crossover
            if len(self.squid_ink_long_window_prices) == self.squid_ink_long_window:
                short_mean = np.mean(self.squid_ink_short_window_prices)
                long_mean = np.mean(self.squid_ink_long_window_prices)

                if long_mean < short_mean:
                    # Market is UP-TRENDING -> don't provide buy-side liquidity
                    buy_side = False
                elif long_mean > short_mean:
                    # Market is DOWN-TRENDING -> don't provide sell-side liquidity
                    sell_side = False

                # Safety: if near position limit, re-enable both sides
                size = self.get_product_pos(state, 'SQUID_INK')
                squid_pos_size = abs(size/50)
                if squid_pos_size > 0.8:
                    buy_side = True
                    sell_side = True

                # Flash crash detection via delta-volatility
                if self.prev_vol is not None:
                    delta_vol = abs(volatility - self.prev_vol)
                    self.prev_vol = volatility
                    if delta_vol > 2:
                        # Huge volatility spike -> trade the reversal
                        if self.prev_price > decimal_fair_price:
                            self.search_buys(state, 'SQUID_INK', decimal_fair_price+4, depth=3)
                        elif self.prev_price < decimal_fair_price:
                            self.search_sells(state, 'SQUID_INK', decimal_fair_price-4, depth=3)
                else:
                    self.prev_vol = volatility

            self.make_squid_market(state, sell_side=sell_side, buy_side=buy_side)
            self.prev_price = decimal_fair_price

    def make_squid_market(self, state, sell_side=True, buy_side=True):
        """Market making for squid ink with selective side enabling."""
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

            max_buy = max(0, 50 - state.position.get("SQUID_INK", 0) - self.squid_ink_buy_orders)
            max_sell = max(0, state.position.get("SQUID_INK", 0) + 50 - self.squid_ink_sell_orders)

            if buy_side:
                self.send_buy_order('SQUID_INK', buy_price, max_buy)
            if sell_side:
                self.send_sell_order('SQUID_INK', sell_price, -max_sell)

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
