"""
IMC Prosperity 3 - chrispyroberts team
Round 2: Picnic Basket Z-Score Arbitrage with Full Hedging
Source: https://github.com/chrispyroberts/imc-prosperity-3/blob/main/ROUND%202/FINAL_FRENCH_GUY.py

Strategy:
- Two spread trades:
  1. Premium Difference: BASKET1_premium - BASKET2_premium (inter-basket spread)
     - z_score_threshold = 20
     - When z > threshold: short basket1, long basket2, hedge with constituents
     - When z < -threshold: long basket1, short basket2, hedge with constituents
  2. Basket2 Premium: BASKET2_price - (4*CROISSANTS + 2*JAMS) (basket vs synthetic)
     - z_score_threshold_basket_2 = 20
     - When z > threshold: short basket2, buy constituents
     - When z < -threshold: long basket2, sell constituents
- Full hedging: for each basket trade, simultaneously trades constituents
  - Basket1 trade: hedge with basket2 + 2*CROISSANTS + 1*JAMS + 1*DJEMBES
  - Basket2 trade: hedge with 4*CROISSANTS + 2*JAMS
- Market making on basket2 when not arb-trading
- Rolling z-score window of 30 ticks
"""

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
        if len(value) <= max_length:
            return value
        return value[:max_length - 3] + "..."

logger = Logger()

class Trader:
    def __init__(self):
        self.orders = {}
        self.conversions = 0
        self.traderData = "SAMPLE"

        # ROUND 2 STATE
        self.basket1_premiums = []
        self.basket1_pos = 0
        self.basket2_pos = 0
        self.basket2_premiums = []
        self.premium_difference = []
        self.trade_on_turn = False
        self.basket2_market_make_pos = 0
        self.basket2_buy_orders = 0
        self.basket2_sell_orders = 0

        # HARD CODED MEANS from historical data analysis
        self.basket_2_premium_mean = 48.82898734599846
        self.premium_diff_mean = 18.625755400487463

        # HYPERPARAMS FOR BASKET ARBING
        self.premium_diff_window = 30          # z-score rolling window
        self.z_score_threshold_basket_2 = 20   # entry/exit for basket2 premium
        self.z_score_threshold = 20            # entry/exit for premium difference

    def send_sell_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def send_buy_order(self, product, price, amount, msg=None):
        self.orders[product].append(Order(product, price, amount))
        if msg is not None:
            logger.print(msg)

    def get_product_pos(self, state, product):
        return state.position.get(product, 0)

    def get_market_data(self, state, product):
        order_depth = state.order_depths[product]
        if len(order_depth.buy_orders) == 0:
            raise ValueError('No orders')

        last_bid = None
        total_bid_volume = 0
        for bid, volume in order_depth.buy_orders.items():
            last_bid = bid
            total_bid_volume += abs(volume)

        last_ask = None
        total_ask_volume = 0
        for ask, volume in order_depth.sell_orders.items():
            last_ask = ask
            total_ask_volume += abs(volume)

        return {
            'bid': last_bid, 'bid_volume': total_bid_volume,
            'ask': last_ask, 'ask_volume': total_ask_volume,
            'mid_price': (last_ask + last_bid) / 2
        }

    def get_basket_premiums(self, state, product_data):
        jam_price = product_data['JAMS']['mid_price']
        crossaint_price = product_data['CROISSANTS']['mid_price']
        djembe_price = product_data['DJEMBES']['mid_price']

        basket1_theo_price = 6 * crossaint_price + 3 * jam_price + djembe_price
        basket2_theo_price = 4 * crossaint_price + 2 * jam_price

        basket1_premium = product_data['PICNIC_BASKET1']['mid_price'] - basket1_theo_price
        basket2_premium = product_data['PICNIC_BASKET2']['mid_price'] - basket2_theo_price

        return basket1_premium, basket2_premium

    def long_basket_1(self, state, product_data):
        """Long basket1, short basket2, sell constituents (2 CROISSANTS, 1 JAM, 1 DJEMBE)."""
        crossaint_volume = product_data['CROISSANTS']['bid_volume']
        jam_volume = product_data['JAMS']['bid_volume']
        djembe_volume = product_data['DJEMBES']['bid_volume']
        basket1_volume = product_data['PICNIC_BASKET1']['bid_volume']
        basket2_volume = product_data['PICNIC_BASKET2']['ask_volume']

        possible_buys = min(basket2_volume, basket1_volume,
                          djembe_volume, jam_volume,
                          crossaint_volume // 2)

        buy_limit = 60 - self.get_product_pos(state, 'PICNIC_BASKET1')
        basket1_pos = min(buy_limit, possible_buys)
        self.basket1_pos = basket1_pos

        # Sell CROISSANTS hedge
        self.send_sell_order('CROISSANTS', product_data['CROISSANTS']['bid'],
                           -basket1_pos * 2, msg=f'LONG-BASKET-1: SELL {abs(basket1_pos * 2)} CROISSANTS')
        # Sell DJEMBES hedge
        self.send_sell_order('DJEMBES', product_data['DJEMBES']['bid'],
                           -basket1_pos, msg=f'LONG-BASKET-1: SELL {abs(basket1_pos)} DJEMBES')
        # Sell JAMS hedge
        self.send_sell_order('JAMS', product_data['JAMS']['bid'],
                           -basket1_pos, msg=f'LONG-BASKET-1: SELL {abs(basket1_pos)} JAMS')
        # Buy basket1
        self.send_buy_order('PICNIC_BASKET1', product_data['PICNIC_BASKET1']['ask'],
                          basket1_pos, msg=f'LONG-BASKET-1: BUY {abs(basket1_pos)} PICNIC_BASKET1')
        # Sell basket2
        self.send_sell_order('PICNIC_BASKET2', product_data['PICNIC_BASKET2']['bid'],
                           -basket1_pos, msg=f'LONG-BASKET-1: SELL {abs(basket1_pos)} PICNIC_BASKET2')

    def short_basket_1(self, state, product_data):
        """Short basket1, long basket2, buy constituents."""
        crossaint_volume = product_data['CROISSANTS']['ask_volume']
        jam_volume = product_data['JAMS']['ask_volume']
        djembe_volume = product_data['DJEMBES']['ask_volume']
        basket1_volume = product_data['PICNIC_BASKET1']['bid_volume']
        basket2_volume = product_data['PICNIC_BASKET2']['ask_volume']

        possible_sells = min(basket2_volume, basket1_volume,
                           djembe_volume, jam_volume,
                           crossaint_volume // 2)

        sell_limit = 60 + self.get_product_pos(state, 'PICNIC_BASKET1')
        basket1_pos = min(sell_limit, possible_sells)
        self.basket1_pos = basket1_pos

        self.send_buy_order('CROISSANTS', product_data['CROISSANTS']['ask'],
                          basket1_pos * 2, msg=f'SHORT-BASKET-1: BUY {abs(basket1_pos * 2)} CROISSANTS')
        self.send_buy_order('DJEMBES', product_data['DJEMBES']['ask'],
                          basket1_pos, msg=f'SHORT-BASKET-1: BUY {abs(basket1_pos)} DJEMBES')
        self.send_buy_order('JAMS', product_data['JAMS']['ask'],
                          basket1_pos, msg=f'SHORT-BASKET-1: BUY {abs(basket1_pos)} JAMS')
        self.send_sell_order('PICNIC_BASKET1', product_data['PICNIC_BASKET1']['bid'],
                           -basket1_pos, msg=f'SHORT-BASKET-1: SELL {abs(basket1_pos)} PICNIC_BASKET1')
        self.send_buy_order('PICNIC_BASKET2', product_data['PICNIC_BASKET2']['ask'],
                          basket1_pos, msg=f'SHORT-BASKET-1: BUY {abs(basket1_pos)} PICNIC_BASKET2')

    def long_basket_2(self, state, product_data):
        """Long basket2, sell 4 CROISSANTS + 2 JAMS."""
        crossaint_volume = product_data['CROISSANTS']['bid_volume']
        jam_volume = product_data['JAMS']['bid_volume']
        basket2_volume = product_data['PICNIC_BASKET2']['ask_volume']

        possible_buys = min(basket2_volume, jam_volume // 2, crossaint_volume // 4)

        buy_limit = 32 - self.basket2_pos
        basket2_pos = min(buy_limit, possible_buys)

        if abs(basket2_pos) > 0:
            self.trade_on_turn = True

        self.send_sell_order('CROISSANTS', product_data['CROISSANTS']['bid'],
                           -basket2_pos * 4, msg=f'LONG-BASKET-2: SELL {abs(basket2_pos * 4)} CROISSANTS')
        self.send_sell_order('JAMS', product_data['JAMS']['bid'],
                           -basket2_pos * 2, msg=f'LONG-BASKET-2: SELL {abs(basket2_pos * 2)} JAMS')
        self.send_buy_order('PICNIC_BASKET2', product_data['PICNIC_BASKET2']['ask'],
                          basket2_pos, msg=f'LONG-BASKET-2: BUY {abs(basket2_pos)} PICNIC_BASKET2')
        self.basket2_pos += basket2_pos

    def short_basket_2(self, state, product_data):
        """Short basket2, buy 4 CROISSANTS + 2 JAMS."""
        crossaint_volume = product_data['CROISSANTS']['ask_volume']
        jam_volume = product_data['JAMS']['ask_volume']
        basket2_volume = product_data['PICNIC_BASKET2']['bid_volume']

        possible_sells = min(basket2_volume, jam_volume // 2, crossaint_volume // 4)

        max_sell = 32 + self.basket2_pos
        basket2_pos = min(max_sell, possible_sells)

        if abs(basket2_pos) > 0:
            self.trade_on_turn = True

        self.send_buy_order('CROISSANTS', product_data['CROISSANTS']['ask'],
                          basket2_pos * 4, msg=f'SHORT-BASKET-2: BUY {abs(basket2_pos * 4)} CROISSANTS')
        self.send_buy_order('JAMS', product_data['JAMS']['ask'],
                          basket2_pos * 2, msg=f'SHORT-BASKET-2: BUY {abs(basket2_pos * 2)} JAMS')
        self.send_sell_order('PICNIC_BASKET2', product_data['PICNIC_BASKET2']['bid'],
                           -basket2_pos, msg=f'SHORT-BASKET-2: SELL {abs(basket2_pos)} PICNIC_BASKET2')
        self.basket2_pos -= basket2_pos

    def trade_baskets(self, state):
        """Main basket trading logic with dual z-score strategies."""
        self.update_basket2_pos(state)
        products = ['PICNIC_BASKET1', 'PICNIC_BASKET2', 'JAMS', 'CROISSANTS', 'DJEMBES']
        product_data = {}
        for p in products:
            product_data[p] = self.get_market_data(state, p)

        basket1_premium, basket2_premium = self.get_basket_premiums(state, product_data)

        self.basket1_premiums.append(basket1_premium)
        self.basket2_premiums.append(basket2_premium)
        self.basket2_premiums = self.basket2_premiums[-self.premium_diff_window:]
        self.basket1_premiums = self.basket1_premiums[-self.premium_diff_window:]

        premium_diff = basket1_premium - basket2_premium

        self.premium_difference.append(premium_diff)
        self.premium_difference = self.premium_difference[-self.premium_diff_window:]

        if len(self.premium_difference) < self.premium_diff_window:
            logger.print("Not enough data to calculate z-score")
            return

        premium_difference_std = np.std(self.premium_difference)
        premium_difference_z_score = (premium_diff - self.premium_diff_mean) / premium_difference_std
        logger.print(f"Premium Difference Z-score: {premium_difference_z_score}")

        # STRATEGY 1: Inter-basket spread arbitrage
        if premium_difference_z_score > self.z_score_threshold:
            logger.print("Go short on basket 1 and long on basket 2")
            self.short_basket_1(state, product_data)
        elif premium_difference_z_score < -self.z_score_threshold:
            logger.print("Go long on basket 1 and short on basket 2")
            self.long_basket_1(state, product_data)

        if self.basket1_pos != 0:
            self.trade_on_turn = True
            return

        # STRATEGY 2: Basket2 vs synthetic arbitrage
        basket2_premium_std = np.std(self.basket2_premiums)
        basket2_z_score = (basket2_premium - self.basket_2_premium_mean) / basket2_premium_std
        logger.print(f"Basket 2 Premium Z-score: {basket2_z_score}")

        if basket2_z_score > self.z_score_threshold_basket_2:
            self.short_basket_2(state, product_data)
        elif basket2_z_score < -self.z_score_threshold_basket_2:
            self.long_basket_2(state, product_data)

    def update_basket2_pos(self, state):
        if self.trade_on_turn:
            self.trade_on_turn = False
            return
        for trade in state.own_trades.get('PICNIC_BASKET2', []):
            if trade.timestamp == state.timestamp - 100:
                if trade.buyer == 'SUBMISSION':
                    self.basket2_market_make_pos += abs(trade.quantity)
                elif trade.seller == 'SUBMISSION':
                    self.basket2_market_make_pos -= abs(trade.quantity)
        self.trade_on_turn = False

    def reset_orders(self, state):
        self.orders = {}
        self.conversions = 0
        self.basket1_pos = 0
        self.basket2_sell_orders = 0
        self.basket2_buy_orders = 0
        for product in state.order_depths:
            self.orders[product] = []

    def run(self, state: TradingState):
        self.reset_orders(state)
        self.trade_baskets(state)
        logger.flush(state, self.orders, self.conversions, self.traderData)
        return self.orders, self.conversions, self.traderData
