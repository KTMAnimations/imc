"""
IMC Prosperity 3 - Market Making Algorithm (RAINFOREST_RESIN portion)
Team: Frankfurt Hedgehogs (2nd Place Overall, 1,433,876 SeaShells)
Source: https://github.com/TimoDiehm/imc-prosperity-3
File: FrankfurtHedgehogs_polished.py

Key Strategy for RAINFOREST_RESIN (StaticTrader):
- "Wall Mid" calculation: average of bid_wall (lowest bid) and ask_wall (highest ask)
- Two-phase approach: (1) TAKING - buy below wall_mid-1, sell above wall_mid+1
- (2) MAKING - penny competing market makers, improve inside the spread
- Inventory flattening at wall_mid when position is non-zero
- Volume-aware logic: only penny orders with volume > 1
"""

from datamodel import OrderDepth, TradingState, Order
import json
import numpy as np
import math
from statistics import NormalDist

_N = NormalDist()

####### GENERAL #######

STATIC_SYMBOL = 'RAINFOREST_RESIN'
DYNAMIC_SYMBOL = 'KELP'
INK_SYMBOL = 'SQUID_INK'

POS_LIMITS = {
    STATIC_SYMBOL: 50,
    DYNAMIC_SYMBOL: 50,
    INK_SYMBOL: 50,
}

LONG, NEUTRAL, SHORT = 1, 0, -1

INFORMED_TRADER_ID = 'Olivia'


class ProductTrader:
    """Base class for all product traders. Handles order management,
    market depth analysis, and position tracking."""

    def __init__(self, name, state, prints, new_trader_data, product_group=None):

        self.orders = []

        self.name = name
        self.state = state
        self.prints = prints
        self.new_trader_data = new_trader_data
        self.product_group = name if product_group is None else product_group

        self.last_traderData = self.get_last_traderData()

        self.position_limit = POS_LIMITS.get(self.name, 0)
        self.initial_position = self.state.position.get(self.name, 0)

        self.expected_position = self.initial_position

        self.mkt_buy_orders, self.mkt_sell_orders = self.get_order_depth()
        self.bid_wall, self.wall_mid, self.ask_wall = self.get_walls()
        self.best_bid, self.best_ask = self.get_best_bid_ask()

        self.max_allowed_buy_volume, self.max_allowed_sell_volume = self.get_max_allowed_volume()
        self.total_mkt_buy_volume, self.total_mkt_sell_volume = self.get_total_market_buy_sell_volume()

    def get_last_traderData(self):

        last_traderData = {}
        try:
            if self.state.traderData != '':
                last_traderData = json.loads(self.state.traderData)
        except: self.log("ERROR", 'td')

        return last_traderData

    def get_best_bid_ask(self):

        best_bid = best_ask = None

        try:
            if len(self.mkt_buy_orders) > 0:
                best_bid = max(self.mkt_buy_orders.keys())
            if len(self.mkt_sell_orders) > 0:
                best_ask = min(self.mkt_sell_orders.keys())
        except: pass

        return best_bid, best_ask

    def get_walls(self):
        """Wall Mid calculation:
        bid_wall = LOWEST bid price (the wall on the bid side)
        ask_wall = HIGHEST ask price (the wall on the ask side)
        wall_mid = average of bid_wall and ask_wall

        This gives a more stable fair value estimate than simple mid-price
        because it uses the extremes of the order book rather than the
        best bid/ask which can be noisy."""

        bid_wall = wall_mid = ask_wall = None

        try: bid_wall = min([x for x,_ in self.mkt_buy_orders.items()])
        except: pass

        try: ask_wall = max([x for x,_ in self.mkt_sell_orders.items()])
        except: pass

        try: wall_mid = (bid_wall + ask_wall) / 2
        except: pass

        return bid_wall, wall_mid, ask_wall

    def get_total_market_buy_sell_volume(self):

        market_bid_volume = market_ask_volume = 0

        try:
            market_bid_volume = sum([v for p, v in self.mkt_buy_orders.items()])
            market_ask_volume = sum([v for p, v in self.mkt_sell_orders.items()])
        except: pass

        return market_bid_volume, market_ask_volume


    def get_max_allowed_volume(self):
        max_allowed_buy_volume = self.position_limit - self.initial_position
        max_allowed_sell_volume = self.position_limit + self.initial_position
        return max_allowed_buy_volume, max_allowed_sell_volume

    def get_order_depth(self):

        order_depth, buy_orders, sell_orders = {}, {}, {}

        try: order_depth: OrderDepth = self.state.order_depths[self.name]
        except: pass
        try: buy_orders = {bp: abs(bv) for bp, bv in sorted(order_depth.buy_orders.items(), key=lambda x: x[0], reverse=True)}
        except: pass
        try: sell_orders = {sp: abs(sv) for sp, sv in sorted(order_depth.sell_orders.items(), key=lambda x: x[0])}
        except: pass

        return buy_orders, sell_orders

    def bid(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_buy_volume)
        order = Order(self.name, int(price), abs_volume)
        if logging: self.log("BUYO", {"p":price, "s":self.name, "v":int(volume)}, product_group='ORDERS')
        self.max_allowed_buy_volume -= abs_volume
        self.orders.append(order)

    def ask(self, price, volume, logging=True):
        abs_volume = min(abs(int(volume)), self.max_allowed_sell_volume)
        order = Order(self.name, int(price), -abs_volume)
        if logging: self.log("SELLO", {"p":price, "s":self.name, "v":int(volume)}, product_group='ORDERS')
        self.max_allowed_sell_volume -= abs_volume
        self.orders.append(order)

    def log(self, kind, message, product_group=None):
        if product_group is None: product_group = self.product_group

        if product_group == 'ORDERS':
            group = self.prints.get(product_group, [])
            group.append({kind: message})
        else:
            group = self.prints.get(product_group, {})
            group[kind] = message

        self.prints[product_group] = group

    def get_orders(self):
        return {}


class StaticTrader(ProductTrader):
    """Market maker for RAINFOREST_RESIN (stable product with fair value ~10000).

    Strategy:
    1. TAKING: Aggressively buy any asks <= wall_mid - 1, sell any bids >= wall_mid + 1
       - Also flatten inventory at wall_mid when position is non-zero
    2. MAKING: Place passive quotes inside the spread
       - Penny competing orders (their_price +/- 1) if they have volume > 1
       - Otherwise join at competing price
       - Ensure our quotes stay outside wall_mid
    """
    def __init__(self, state, prints, new_trader_data):
        super().__init__(STATIC_SYMBOL, state, prints, new_trader_data)

    def get_orders(self):

        if self.wall_mid is not None:

            ##########################################################
            ####### 1. TAKING
            ##########################################################
            for sp, sv in self.mkt_sell_orders.items():
                if sp <= self.wall_mid - 1:
                    # Buy any ask that's more than 1 below wall_mid
                    self.bid(sp, sv, logging=False)
                elif sp <= self.wall_mid and self.initial_position < 0:
                    # If we're short, also buy at wall_mid to flatten
                    volume = min(sv,  abs(self.initial_position))
                    self.bid(sp, volume, logging=False)

            for bp, bv in self.mkt_buy_orders.items():
                if bp >= self.wall_mid + 1:
                    # Sell to any bid that's more than 1 above wall_mid
                    self.ask(bp, bv, logging=False)
                elif bp >= self.wall_mid and self.initial_position > 0:
                    # If we're long, also sell at wall_mid to flatten
                    volume = min(bv,  self.initial_position)
                    self.ask(bp, volume, logging=False)

            ###########################################################
            ####### 2. MAKING
            ###########################################################
            bid_price = int(self.bid_wall + 1)
            ask_price = int(self.ask_wall - 1)

            for bp, bv in self.mkt_buy_orders.items():
                overbidding_price = bp + 1
                # Only penny if order has meaningful volume (>1)
                if bv > 1 and overbidding_price < self.wall_mid:
                    bid_price = max(bid_price, overbidding_price)
                    break
                elif bp < self.wall_mid:
                    bid_price = max(bid_price, bp)
                    break

            for sp, sv in self.mkt_sell_orders.items():
                underbidding_price = sp - 1
                # Only penny if order has meaningful volume (>1)
                if sv > 1 and underbidding_price > self.wall_mid:
                    ask_price = min(ask_price, underbidding_price)
                    break
                elif sp > self.wall_mid:
                    ask_price = min(ask_price, sp)
                    break

            self.bid(bid_price, self.max_allowed_buy_volume)
            self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


class Trader:
    """Main Trader class that dispatches to product-specific traders."""

    def run(self, state: TradingState):
        result: dict[str,list[Order]] = {}
        new_trader_data = {}
        prints = {
            "GENERAL": {
                "TIMESTAMP": state.timestamp,
                "POSITIONS": state.position
            },
        }

        def export(prints):
            try: print(json.dumps(prints))
            except: pass

        product_traders = {
            STATIC_SYMBOL: StaticTrader,
            # DYNAMIC_SYMBOL: DynamicTrader,  # Kelp trader (not shown)
            # INK_SYMBOL: InkTrader,          # Squid ink trader (not shown)
        }

        result, conversions = {}, 0
        for symbol, product_trader in product_traders.items():
            if symbol in state.order_depths:

                try:
                    trader = product_trader(state, prints, new_trader_data)
                    result.update(trader.get_orders())
                except: pass

        try: final_trader_data = json.dumps(new_trader_data)
        except: final_trader_data = ''

        export(prints)
        return result, conversions, final_trader_data
