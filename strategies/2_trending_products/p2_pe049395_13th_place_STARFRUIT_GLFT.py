"""
SOURCE: Team (Byeongguk Kang, Minwoo Kim, Uihyung Lee) - 13th Place IMC Prosperity 2
REPO: https://github.com/pe049395/IMC-Prosperity-2024
FILE: submissions/round5.py (final submission containing all rounds)
PRODUCT: STARFRUIT (trending/drifting product in Prosperity 2)

KEY TECHNIQUES FOR TRENDING PRODUCTS:
- Uses "max amount mid price" (maxamt_midprc): identifies the price level with the
  largest volume on each side as the true MM quote, uses midpoint as fair value
- Implements Gueant-Lehalle-Fernandez-Tapia (GLFT) market making model
  with inventory-dependent optimal spread calculation
- Also implements Ornstein-Uhlenbeck (OU) mean-reversion market making
- Uses VWAP across all order book levels as an alternative fair value signal
- Sophisticated Status class tracks historical order depths for signal generation
"""

import json
import numpy as np
import math
from statistics import NormalDist
from datamodel import *
from typing import Any

INF = 1e9
normalDist = NormalDist(0,1)


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
            conversions,
            "",
            "",
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

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp, trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings):
        return [[l["symbol"], l["product"], l["denomination"]] for l in listings.values()]

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
                             obs.exportTariff, obs.importTariff, obs.sunlight, obs.humidity]
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


class Status:
    """Tracks real-time and historical order book state for a product."""

    _position_limit = {
        "AMETHYSTS": 20,
        "STARFRUIT": 20,
        "ORCHIDS": 100,
        "CHOCOLATE": 250,
        "STRAWBERRIES": 350,
        "ROSES": 60,
        "GIFT_BASKET": 60,
        "COCONUT": 300,
        "COCONUT_COUPON": 600,
    }
    _state = None
    _realtime_position = {key:0 for key in _position_limit.keys()}
    _hist_order_depths = {
        product:{
            'bidprc1': [], 'bidamt1': [], 'bidprc2': [], 'bidamt2': [],
            'bidprc3': [], 'bidamt3': [], 'askprc1': [], 'askamt1': [],
            'askprc2': [], 'askamt2': [], 'askprc3': [], 'askamt3': [],
        } for product in _position_limit.keys()
    }
    _num_data = 0

    def __init__(self, product: str) -> None:
        self.product = product

    @classmethod
    def cls_update(cls, state: TradingState) -> None:
        cls._state = state
        for product, posit in state.position.items():
            cls._realtime_position[product] = posit
        for product, orderdepth in state.order_depths.items():
            cnt = 1
            for prc, amt in sorted(orderdepth.sell_orders.items(), reverse=False):
                cls._hist_order_depths[product][f'askamt{cnt}'].append(amt)
                cls._hist_order_depths[product][f'askprc{cnt}'].append(prc)
                cnt += 1
                if cnt == 4: break
            while cnt < 4:
                cls._hist_order_depths[product][f'askprc{cnt}'].append(np.nan)
                cls._hist_order_depths[product][f'askamt{cnt}'].append(np.nan)
                cnt += 1
            cnt = 1
            for prc, amt in sorted(orderdepth.buy_orders.items(), reverse=True):
                cls._hist_order_depths[product][f'bidprc{cnt}'].append(prc)
                cls._hist_order_depths[product][f'bidamt{cnt}'].append(amt)
                cnt += 1
                if cnt == 4: break
            while cnt < 4:
                cls._hist_order_depths[product][f'bidprc{cnt}'].append(np.nan)
                cls._hist_order_depths[product][f'bidamt{cnt}'].append(np.nan)
                cnt += 1
        cls._num_data += 1

    @property
    def position_limit(self): return self._position_limit[self.product]

    @property
    def position(self):
        return int(self._state.position.get(self.product, 0))

    @property
    def rt_position(self): return self._realtime_position[self.product]

    def rt_position_update(self, new_position):
        if abs(new_position) <= self._position_limit[self.product]:
            self._realtime_position[self.product] = new_position

    @property
    def bids(self): return list(self._state.order_depths[self.product].buy_orders.items())

    @property
    def asks(self): return list(self._state.order_depths[self.product].sell_orders.items())

    @property
    def possible_buy_amt(self):
        return min(self._position_limit[self.product] - self.rt_position,
                   self._position_limit[self.product] - self.position)

    @property
    def possible_sell_amt(self):
        return min(self._position_limit[self.product] + self.rt_position,
                   self._position_limit[self.product] + self.position)

    @property
    def best_bid(self):
        buy_orders = self._state.order_depths[self.product].buy_orders
        return max(buy_orders.keys()) if buy_orders else self.best_ask - 1

    @property
    def best_ask(self):
        sell_orders = self._state.order_depths[self.product].sell_orders
        return min(sell_orders.keys()) if sell_orders else self.best_bid + 1

    @property
    def mid(self): return (self.best_bid + self.best_ask) / 2

    @property
    def maxamt_bidprc(self):
        """Price of bid order with maximum amount - identifies the MM's quote."""
        prc_max, max_amt = 0, 0
        for prc, amt in self._state.order_depths[self.product].buy_orders.items():
            if amt > max_amt:
                max_amt = amt
                prc_max = prc
        return prc_max

    @property
    def maxamt_askprc(self):
        """Price of ask order with maximum amount - identifies the MM's quote."""
        prc_max, max_amt = 0, 0
        for prc, amt in self._state.order_depths[self.product].sell_orders.items():
            if amt < max_amt:
                max_amt = amt
                prc_max = prc
        return prc_max

    @property
    def maxamt_midprc(self):
        """Fair value from market maker's mid price."""
        return (self.maxamt_bidprc + self.maxamt_askprc) / 2

    @property
    def vwap(self):
        vwap = 0
        total_amt = 0
        for prc, amt in self._state.order_depths[self.product].buy_orders.items():
            vwap += (prc * amt)
            total_amt += amt
        for prc, amt in self._state.order_depths[self.product].sell_orders.items():
            vwap += (prc * abs(amt))
            total_amt += abs(amt)
        return vwap / total_amt if total_amt > 0 else self.mid

    def update_bids(self, prc, new_amt):
        if new_amt >= 0:
            self._state.order_depths[self.product].buy_orders[prc] = new_amt

    def update_asks(self, prc, new_amt):
        if new_amt <= 0:
            self._state.order_depths[self.product].sell_orders[prc] = new_amt

    @property
    def total_bidamt(self):
        return sum(self._state.order_depths[self.product].buy_orders.values())

    @property
    def total_askamt(self):
        return -sum(self._state.order_depths[self.product].sell_orders.values())

    @property
    def market_trades(self):
        return self._state.market_trades.get(self.product, [])


class Strategy:

    @staticmethod
    def arb(state: Status, fair_price):
        """Take any orders that are mispriced relative to fair value."""
        orders = []
        for ask_price, ask_amount in state.asks:
            if ask_price < fair_price:
                buy_amount = min(-ask_amount, state.possible_buy_amt)
                if buy_amount > 0:
                    orders.append(Order(state.product, int(ask_price), int(buy_amount)))
                    state.rt_position_update(state.rt_position + buy_amount)
                    state.update_asks(ask_price, -(-ask_amount - buy_amount))
            elif ask_price == fair_price:
                if state.rt_position < 0:
                    buy_amount = min(-ask_amount, -state.rt_position)
                    orders.append(Order(state.product, int(ask_price), int(buy_amount)))
                    state.rt_position_update(state.rt_position + buy_amount)

        for bid_price, bid_amount in state.bids:
            if bid_price > fair_price:
                sell_amount = min(bid_amount, state.possible_sell_amt)
                if sell_amount > 0:
                    orders.append(Order(state.product, int(bid_price), -int(sell_amount)))
                    state.rt_position_update(state.rt_position - sell_amount)
                    state.update_bids(bid_price, bid_amount - sell_amount)
            elif bid_price == fair_price:
                if state.rt_position > 0:
                    sell_amount = min(bid_amount, state.rt_position)
                    orders.append(Order(state.product, int(bid_price), -int(sell_amount)))
                    state.rt_position_update(state.rt_position - sell_amount)
        return orders

    @staticmethod
    def mm_glft(
        state: Status,
        fair_price,
        mu=0,
        sigma=0.3959,
        gamma=1e-9,
        order_amount=20,
    ):
        """
        Gueant-Lehalle-Fernandez-Tapia optimal market making.
        Computes inventory-dependent optimal bid/ask spreads.
        """
        q = state.rt_position / order_amount

        kappa_b = 1 / max((fair_price - state.best_bid) - 1, 1)
        kappa_a = 1 / max((state.best_ask - fair_price) - 1, 1)

        A_b = 0.25
        A_a = 0.25

        delta_b = (1 / gamma * math.log(1 + gamma / kappa_b) +
                   (-mu / (gamma * sigma**2) + (2 * q + 1) / 2) *
                   math.sqrt((sigma**2 * gamma) / (2 * kappa_b * A_b) *
                            (1 + gamma / kappa_b)**(1 + kappa_b / gamma)))

        delta_a = (1 / gamma * math.log(1 + gamma / kappa_a) +
                   (mu / (gamma * sigma**2) - (2 * q - 1) / 2) *
                   math.sqrt((sigma**2 * gamma) / (2 * kappa_a * A_a) *
                            (1 + gamma / kappa_a)**(1 + kappa_a / gamma)))

        p_b = round(fair_price - delta_b)
        p_a = round(fair_price + delta_a)

        # Safety constraints
        p_b = min(p_b, fair_price)      # Don't buy above fair value
        p_b = min(p_b, state.best_bid + 1)  # Stay competitive
        p_b = max(p_b, state.maxamt_bidprc + 1)  # Don't go beyond MM wall

        p_a = max(p_a, fair_price)      # Don't sell below fair value
        p_a = max(p_a, state.best_ask - 1)  # Stay competitive
        p_a = min(p_a, state.maxamt_askprc - 1)  # Don't go beyond MM wall

        buy_amount = min(order_amount, state.possible_buy_amt)
        sell_amount = min(order_amount, state.possible_sell_amt)

        orders = []
        if buy_amount > 0:
            orders.append(Order(state.product, int(p_b), int(buy_amount)))
        if sell_amount > 0:
            orders.append(Order(state.product, int(p_a), -int(sell_amount)))
        return orders


class Trade:
    @staticmethod
    def starfruit(state: Status) -> list[Order]:
        """
        STARFRUIT strategy: uses maxamt_midprc as fair value,
        then applies arbitrage + GLFT market making.
        """
        current_price = state.maxamt_midprc
        orders = []
        orders.extend(Strategy.arb(state=state, fair_price=current_price))
        orders.extend(Strategy.mm_glft(state=state, fair_price=current_price,
                                        gamma=0.1, order_amount=20))
        return orders


class Trader:
    state_starfruit = Status('STARFRUIT')

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        Status.cls_update(state)
        result = {}
        result["STARFRUIT"] = Trade.starfruit(self.state_starfruit)
        conversions = 0
        traderData = "SAMPLE"
        logger.flush(state, result, conversions, traderData)
        return result, conversions, traderData
