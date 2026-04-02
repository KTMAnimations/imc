"""
IMC Prosperity 2 - pe049395 (13th Place Global)
Round 5 (includes Round 3 Gift Basket): Index Arbitrage + Vol Arb + Delta Hedging
Source: https://github.com/pe049395/IMC-Prosperity-2024/blob/main/submissions/round5.py

Strategy for GIFT_BASKET (index_arb):
- synthetic = 4*CHOCOLATE_vwap + 6*STRAWBERRIES_vwap + 1*ROSES_vwap
- spread = basket_mid - synthetic
- norm_spread = spread - theta (mean premium ~380)
- If norm_spread > threshold (30): sell basket at worst bid
- If norm_spread < -threshold: buy basket at worst ask
- Basket-only trading (no constituent hedging) to reduce transaction costs
- Also includes insider_trading signal from "Rhianna" for ROSES

Also includes:
- Vol arb on COCONUT_COUPON via implied vol vs historical vol
- Delta hedging underlying COCONUT position
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

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing["symbol"], listing["product"], listing["denomination"]])
        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]
        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append([
                    trade.symbol, trade.price, trade.quantity,
                    trade.buyer, trade.seller, trade.timestamp,
                ])
        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice, observation.askPrice,
                observation.transportFees, observation.exportTariff,
                observation.importTariff, observation.sunlight,
                observation.humidity,
            ]
        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])
        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value
        return value[:max_length - 3] + "..."

logger = Logger()


class Status:

    _position_limit = {
        "AMETHYSTS": 20, "STARFRUIT": 20, "ORCHIDS": 100,
        "CHOCOLATE": 250, "STRAWBERRIES": 350, "ROSES": 60,
        "GIFT_BASKET": 60, "COCONUT": 300, "COCONUT_COUPON": 600,
    }

    _state = None
    _realtime_position = {key:0 for key in _position_limit.keys()}
    _num_data = 0

    def __init__(self, product: str) -> None:
        self.product = product

    @classmethod
    def cls_update(cls, state: TradingState) -> None:
        cls._state = state
        for product, posit in state.position.items():
            cls._realtime_position[product] = posit
        cls._num_data += 1

    @property
    def position_limit(self) -> int:
        return self._position_limit[self.product]

    @property
    def position(self) -> int:
        if self.product in self._state.position:
            return int(self._state.position[self.product])
        else:
            return 0

    @property
    def rt_position(self) -> int:
        return self._realtime_position[self.product]

    def rt_position_update(self, new_position: int) -> None:
        if abs(new_position) <= self._position_limit[self.product]:
            self._realtime_position[self.product] = new_position

    @property
    def possible_buy_amt(self) -> int:
        return min(
            self._position_limit[self.product] - self.rt_position,
            self._position_limit[self.product] - self.position
        )

    @property
    def possible_sell_amt(self) -> int:
        return min(
            self._position_limit[self.product] + self.rt_position,
            self._position_limit[self.product] + self.position
        )

    @property
    def best_bid(self) -> int:
        buy_orders = self._state.order_depths[self.product].buy_orders
        if len(buy_orders) > 0:
            return max(buy_orders.keys())
        else:
            return self.best_ask - 1

    @property
    def best_ask(self) -> int:
        sell_orders = self._state.order_depths[self.product].sell_orders
        if len(sell_orders) > 0:
            return min(sell_orders.keys())
        else:
            return self.best_bid + 1

    @property
    def mid(self) -> float:
        return (self.best_bid + self.best_ask) / 2

    @property
    def worst_bid(self) -> int:
        buy_orders = self._state.order_depths[self.product].buy_orders
        if len(buy_orders) > 0:
            return min(buy_orders.keys())
        else:
            return self.best_ask - 1

    @property
    def worst_ask(self) -> int:
        sell_orders = self._state.order_depths[self.product].sell_orders
        if len(sell_orders) > 0:
            return max(sell_orders.keys())
        else:
            return self.best_bid + 1

    @property
    def vwap(self) -> float:
        vwap = 0
        total_amt = 0
        for prc, amt in self._state.order_depths[self.product].buy_orders.items():
            vwap += (prc * amt)
            total_amt += amt
        for prc, amt in self._state.order_depths[self.product].sell_orders.items():
            vwap += (prc * abs(amt))
            total_amt += abs(amt)
        vwap /= total_amt
        return vwap

    @property
    def total_bidamt(self) -> int:
        return sum(self._state.order_depths[self.product].buy_orders.values())

    @property
    def total_askamt(self) -> int:
        return -sum(self._state.order_depths[self.product].sell_orders.values())

    @property
    def market_trades(self) -> list:
        return self._state.market_trades.get(self.product, [])

    @property
    def bid_ask_spread(self) -> int:
        return self.best_ask - self.best_bid


def cal_tau(day, timestep, T=1):
    return T - ((day - 1) * 20000 + timestep) * 2e-7

def cal_call(S, tau, sigma=0.16, r=0, K=10000):
    d1 = (np.log(S / K) + (r + 0.5 * sigma**2) * tau) / (sigma * math.sqrt(tau))
    delta = normalDist.cdf(d1)
    d2 = d1 - sigma * np.sqrt(tau)
    call_price = S * delta - K * math.exp(-r * tau) * normalDist.cdf(d2)
    return call_price, delta

def cal_imvol(market_price, S, tau, r=0, K=10000, tol=1e-6, max_iter=100):
    sigma = 0.16
    diff = cal_call(S, tau, sigma)[0] - market_price
    iter_count = 0
    while np.any(np.abs(diff) > tol) and iter_count < max_iter:
        vega = (cal_call(S, tau, sigma+tol)[0] - cal_call(S, tau, sigma)[0]) / tol
        sigma -= diff / vega
        diff = cal_call(S, tau, sigma)[0] - market_price
        iter_count += 1
    return sigma


class Strategy:

    @staticmethod
    def index_arb(
        basket: Status,
        chocolate: Status,
        strawberries: Status,
        roses: Status,
        theta=380,
        threshold=30,
    ):
        """
        KEY BASKET ARBITRAGE STRATEGY:
        - basket_prc = mid price of GIFT_BASKET
        - underlying_prc = 4*CHOCOLATE_vwap + 6*STRAWBERRIES_vwap + 1*ROSES_vwap
        - spread = basket_prc - underlying_prc
        - norm_spread = spread - theta (mean premium)
        - If norm_spread > threshold: sell basket
        - If norm_spread < -threshold: buy basket
        """
        basket_prc = basket.mid
        underlying_prc = 4 * chocolate.vwap + 6 * strawberries.vwap + 1 * roses.vwap
        spread = basket_prc - underlying_prc
        norm_spread = spread - theta

        orders = []
        if norm_spread > threshold:
            orders.append(Order(basket.product, int(basket.worst_bid), -int(basket.possible_sell_amt)))
        elif norm_spread < -threshold:
            orders.append(Order(basket.product, int(basket.worst_ask), int(basket.possible_buy_amt)))

        return orders

    @staticmethod
    def insider_trading(signal_product: Status, trade_product: Status):
        buy_timestamp, sell_timestamp = 0, 0
        for trade in signal_product.market_trades:
            if trade.buyer == "Rhianna":
                buy_timestamp = trade.timestamp
            elif trade.seller == "Rhianna":
                sell_timestamp = trade.timestamp

        orders = []
        if buy_timestamp > sell_timestamp:
            orders.append(Order(trade_product.product, trade_product.worst_ask, trade_product.possible_buy_amt))
        elif buy_timestamp < sell_timestamp:
            orders.append(Order(trade_product.product, trade_product.worst_bid, -trade_product.possible_sell_amt))

        return orders

    @staticmethod
    def vol_arb(option: Status, iv, hv=0.16, threshold=0.00178):
        vol_spread = iv - hv
        orders = []
        if vol_spread > threshold:
            sell_amount = option.possible_sell_amt
            orders.append(Order(option.product, option.worst_bid, -sell_amount))
            executed_amount = min(sell_amount, option.total_bidamt)
            option.rt_position_update(option.rt_position - executed_amount)
        elif vol_spread < -threshold:
            buy_amount = option.possible_buy_amt
            orders.append(Order(option.product, option.worst_ask, buy_amount))
            executed_amount = min(buy_amount, option.total_askamt)
            option.rt_position_update(option.rt_position + executed_amount)
        return orders

    @staticmethod
    def delta_hedge(underlying: Status, option: Status, delta, rebalance_threshold=30):
        target_position = -round(option.rt_position * delta)
        current_position = underlying.position
        position_diff = target_position - current_position

        orders = []
        if underlying.bid_ask_spread == 1 and abs(position_diff) > rebalance_threshold:
            if position_diff < 0:
                sell_amount = min(abs(position_diff), underlying.possible_sell_amt)
                orders.append(Order(underlying.product, underlying.best_bid, -sell_amount))
            elif position_diff > 0:
                buy_amount = min(position_diff, underlying.possible_buy_amt)
                orders.append(Order(underlying.product, underlying.best_ask, buy_amount))
        return orders


class Trade:

    @staticmethod
    def gift_basket(basket: Status, chocolate: Status, strawberries: Status, roses: Status) -> list[Order]:
        orders = []
        orders.extend(Strategy.index_arb(basket, chocolate, strawberries, roses, threshold=30))
        return orders

    @staticmethod
    def roses(state: Status) -> list[Order]:
        orders = []
        orders.extend(Strategy.insider_trading(state, state))
        return orders

    @staticmethod
    def coconut(underlying: Status, option: Status, day) -> dict:
        result = {option.product: [], underlying.product: []}
        underlying_prc = (underlying.best_bid + underlying.best_ask) / 2
        option_prc = (option.best_bid + option.best_ask) / 2
        tau = cal_tau(day=day, timestep=underlying._state.timestamp / 100)
        theo, delta = cal_call(underlying_prc, tau)
        iv = cal_imvol(option_prc, underlying_prc, tau)
        result[option.product].extend(Strategy.vol_arb(option, iv, threshold=0.00175))
        result[underlying.product].extend(Strategy.delta_hedge(underlying, option, delta, rebalance_threshold=60))
        return result


class Trader:

    state_chocolate = Status('CHOCOLATE')
    state_strawberries = Status('STRAWBERRIES')
    state_roses = Status('ROSES')
    state_gift_basket = Status('GIFT_BASKET')
    state_coconut = Status('COCONUT')
    state_coconut_coupon = Status('COCONUT_COUPON')

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        Status.cls_update(state)
        result = {}
        conversions = 0

        # Round 3: Gift Basket index arbitrage
        result["GIFT_BASKET"] = Trade.gift_basket(
            self.state_gift_basket, self.state_chocolate,
            self.state_strawberries, self.state_roses
        )
        result["ROSES"] = Trade.roses(self.state_roses)

        # Round 4: Coconut vol arb + delta hedge
        coconut_result = Trade.coconut(self.state_coconut, self.state_coconut_coupon, day=5)
        result["COCONUT_COUPON"] = coconut_result["COCONUT_COUPON"]

        traderData = "SAMPLE"
        logger.flush(state, result, conversions, traderData)
        return result, conversions, traderData
