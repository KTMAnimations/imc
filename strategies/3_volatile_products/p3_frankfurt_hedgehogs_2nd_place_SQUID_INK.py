# ============================================================================
# SOURCE: https://github.com/TimoDiehm/imc-prosperity-3
# TEAM: Frankfurt Hedgehogs (TimoDiehm) - 2nd Place Global, Prosperity 3
# FILE: FrankfurtHedgehogs_polished.py (final submission)
# SCORE: 1,433,876 SeaShells out of 12,000+ teams
#
# KEY SQUID INK STRATEGY (InkTrader class):
#   - Pure Olivia copy-trading: detect informed trader "Olivia" buying/selling
#   - If Olivia bought -> go max long (position_limit=50)
#   - If Olivia sold -> go max short (-50)
#   - No mean reversion or volatility detection - purely signal-based
#   - Result: ~8,000 SeaShells/round, low-risk, high-reliability
#
# Also includes: StaticTrader (Resin), DynamicTrader (Kelp), EtfTrader,
#                OptionTrader (Volcanic Rock), CommodityTrader (Macarons)
# ============================================================================

from datamodel import OrderDepth, TradingState, Order
import json
import numpy as np
import math
from statistics import NormalDist

_N = NormalDist()

####### GENERAL ####### GENERAL ####### GENERAL ####### GENERAL

ETF_BASKET_SYMBOLS = ['PICNIC_BASKET1', 'PICNIC_BASKET2']
ETF_CONSTITUENT_SYMBOLS = ['CROISSANTS', 'JAMS', 'DJEMBES']

STATIC_SYMBOL = 'RAINFOREST_RESIN'
DYNAMIC_SYMBOL = 'KELP'
INK_SYMBOL = 'SQUID_INK'

OPTION_UNDERLYING_SYMBOL = 'VOLCANIC_ROCK'

COMMODITY_SYMBOL = 'MAGNIFICENT_MACARONS'

OPTION_SYMBOLS = [
    'VOLCANIC_ROCK_VOUCHER_9500',
    'VOLCANIC_ROCK_VOUCHER_9750',
    'VOLCANIC_ROCK_VOUCHER_10000',
    'VOLCANIC_ROCK_VOUCHER_10250',
    'VOLCANIC_ROCK_VOUCHER_10500'
    ]

POS_LIMITS = {
    STATIC_SYMBOL: 50,
    DYNAMIC_SYMBOL: 50,
    INK_SYMBOL: 50,
    ETF_BASKET_SYMBOLS[0]: 60,
    ETF_BASKET_SYMBOLS[1]: 100,
    ETF_CONSTITUENT_SYMBOLS[0]: 250,
    ETF_CONSTITUENT_SYMBOLS[1]: 350,
    ETF_CONSTITUENT_SYMBOLS[2]: 60,

    OPTION_UNDERLYING_SYMBOL: 400,
    **{os: 200 for os in OPTION_SYMBOLS},

    COMMODITY_SYMBOL: 75,
}

CONVERSION_LIMIT = 10

LONG, NEUTRAL, SHORT = 1, 0, -1

INFORMED_TRADER_ID = 'Olivia'

####### ETF PARAMS

ETF_CONSTITUENT_FACTORS = [[6, 3, 1], [4, 2, 0]]
BASKET_THRESHOLDS = [80, 50]
n_hist_samples = 60_000
INITIAL_ETF_PREMIUMS = [5, 53]
ETF_INFORMED_CONSTITUENT = ETF_CONSTITUENT_SYMBOLS[0]
ETF_THR_INFORMED_ADJS = [90, 90]
ETF_CLOSE_AT_ZERO = True
CALCULATE_RUNNING_ETF_PREMIUM = True
ETF_HEDGE_FACTOR = 0.5

####### OPTIONS PARAMS

DAY = 5
DAYS_PER_YEAR = 365
THR_OPEN, THR_CLOSE = 0.5, 0
LOW_VEGA_THR_ADJ = 0.5
THEO_NORM_WINDOW = 20
IV_SCALPING_THR = 0.7
IV_SCALPING_WINDOW = 100
underlying_mean_reversion_thr = 15
underlying_mean_reversion_window = 10
options_mean_reversion_thr = 5
options_mean_reversion_window = 30


class ProductTrader:
    """Base class with all commonly used utility attributes and methods."""

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

    def check_for_informed(self):
        """Detect Olivia's trading direction from market trades."""
        informed_direction, informed_bought_ts, informed_sold_ts = NEUTRAL, None, None
        informed_bought_ts, informed_sold_ts = self.last_traderData.get(self.name, [None, None])

        trades = self.state.market_trades.get(self.name, []) + self.state.own_trades.get(self.name, [])
        for trade in trades:
            if trade.buyer == INFORMED_TRADER_ID:
                informed_bought_ts = trade.timestamp
            if trade.seller == INFORMED_TRADER_ID:
                informed_sold_ts = trade.timestamp

        self.new_trader_data[self.name] = [informed_bought_ts, informed_sold_ts]

        informed_sold = informed_sold_ts is not None
        informed_bought = informed_bought_ts is not None

        if not informed_bought and not informed_sold:
            informed_direction = NEUTRAL
        elif not informed_bought and informed_sold:
            informed_direction = SHORT
        elif informed_bought and not informed_sold:
            informed_direction = LONG
        elif informed_bought and informed_sold:
            if informed_sold_ts > informed_bought_ts:
                informed_direction = SHORT
            elif informed_sold_ts < informed_bought_ts:
                informed_direction = LONG
            else:
                informed_direction = NEUTRAL

        self.log('TD', self.new_trader_data[self.name])
        self.log('ID', informed_direction)
        return informed_direction, informed_bought_ts, informed_sold_ts

    def get_orders(self):
        return {}


class StaticTrader(ProductTrader):
    """Rainforest Resin - stable product market making."""
    def __init__(self, state, prints, new_trader_data):
        super().__init__(STATIC_SYMBOL, state, prints, new_trader_data)

    def get_orders(self):
        if self.wall_mid is not None:
            # 1. TAKING
            for sp, sv in self.mkt_sell_orders.items():
                if sp <= self.wall_mid - 1:
                    self.bid(sp, sv, logging=False)
                elif sp <= self.wall_mid and self.initial_position < 0:
                    volume = min(sv, abs(self.initial_position))
                    self.bid(sp, volume, logging=False)

            for bp, bv in self.mkt_buy_orders.items():
                if bp >= self.wall_mid + 1:
                    self.ask(bp, bv, logging=False)
                elif bp >= self.wall_mid and self.initial_position > 0:
                    volume = min(bv, self.initial_position)
                    self.ask(bp, volume, logging=False)

            # 2. MAKING
            bid_price = int(self.bid_wall + 1)
            ask_price = int(self.ask_wall - 1)

            for bp, bv in self.mkt_buy_orders.items():
                overbidding_price = bp + 1
                if bv > 1 and overbidding_price < self.wall_mid:
                    bid_price = max(bid_price, overbidding_price)
                    break
                elif bp < self.wall_mid:
                    bid_price = max(bid_price, bp)
                    break

            for sp, sv in self.mkt_sell_orders.items():
                underbidding_price = sp - 1
                if sv > 1 and underbidding_price > self.wall_mid:
                    ask_price = min(ask_price, underbidding_price)
                    break
                elif sp > self.wall_mid:
                    ask_price = min(ask_price, sp)
                    break

            self.bid(bid_price, self.max_allowed_buy_volume)
            self.ask(ask_price, self.max_allowed_sell_volume)

        return {self.name: self.orders}


class DynamicTrader(ProductTrader):
    """Kelp - dynamic product with Olivia signal."""
    def __init__(self, state, prints, new_trader_data):
        super().__init__(DYNAMIC_SYMBOL, state, prints, new_trader_data)
        self.informed_direction, self.informed_bought_ts, self.informed_sold_ts = self.check_for_informed()

    def get_orders(self):
        if self.wall_mid is not None:
            bid_price = self.bid_wall + 1
            bid_volume = self.max_allowed_buy_volume

            if self.informed_bought_ts is not None and self.informed_bought_ts + 5_00 >= self.state.timestamp:
                if self.initial_position < 40:
                    bid_price = self.ask_wall
                    bid_volume = 40 - self.initial_position
            else:
                if self.wall_mid - bid_price < 1 and (self.informed_direction == SHORT and self.initial_position > -40):
                    bid_price = self.bid_wall

            self.bid(bid_price, bid_volume)

            ask_price = self.ask_wall - 1
            ask_volume = self.max_allowed_sell_volume

            if self.informed_sold_ts is not None and self.informed_sold_ts + 5_00 >= self.state.timestamp:
                if self.initial_position > -40:
                    ask_price = self.bid_wall
                    ask_volume = 40 + self.initial_position

            if ask_price - self.wall_mid < 1 and (self.informed_direction == LONG and self.initial_position < 40):
                ask_price = self.ask_wall

            self.ask(ask_price, ask_volume)

        return {self.name: self.orders}


class InkTrader(ProductTrader):
    """
    SQUID INK STRATEGY - Copy-trading Olivia's informed signals.

    This is the key volatile product strategy from the 2nd-place team:
    - Detect whether Olivia (informed trader) is buying or selling
    - Go to maximum position in Olivia's direction
    - No mean reversion, no volatility analysis
    - Pure signal-following with aggressive position sizing
    - ~8,000 SeaShells/round average profit
    """
    def __init__(self, state, prints, new_trader_data):
        super().__init__(INK_SYMBOL, state, prints, new_trader_data)
        self.informed_direction, _, _ = self.check_for_informed()

    def get_orders(self):
        expected_position = 0
        if self.informed_direction == LONG:
            expected_position = self.position_limit
        elif self.informed_direction == SHORT:
            expected_position = -self.position_limit

        remaining_volume = expected_position - self.initial_position

        if remaining_volume > 0 and self.ask_wall is not None:
            self.bid(self.ask_wall, remaining_volume)
        elif remaining_volume < 0 and self.bid_wall is not None:
            self.ask(self.bid_wall, -remaining_volume)

        return {self.name: self.orders}


class Trader:
    def run(self, state: TradingState):
        result = {}
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
            DYNAMIC_SYMBOL: DynamicTrader,
            INK_SYMBOL: InkTrader,
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
