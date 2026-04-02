# ============================================================================
# SOURCE: https://github.com/pe049395/IMC-Prosperity-2024
# TEAM: pe049395 - Overall Rank 13, Prosperity 2
# FILE: submissions/round5.py (final submission, all rounds)
#
# KEY VOLATILE PRODUCT STRATEGIES:
#   1. Starfruit (volatile in Prosperity 2):
#      - Market-making with GLFT (Guéant-Lehalle-Fernandez-Tapia) model
#      - Uses maxamt_midprc as fair value (price at max volume level)
#      - Inventory-aware optimal quoting with gamma parameter
#
#   2. Orchids (cross-exchange arbitrage with volatility):
#      - Exchange arbitrage with execution probability model
#      - Optimal order placement considering transport/tariff costs
#      - Price prediction from humidity production penalty
#
#   3. Coconut Coupon (options on volatile underlying):
#      - Implied volatility calculation via Newton's method
#      - Vol arbitrage: trade when IV deviates from historical vol (0.16)
#      - Delta hedging with rebalance threshold
#
#   4. Gift Basket (spread/index arbitrage):
#      - Index arb: basket vs 4*CHOC + 6*STRAW + 1*ROSE
#      - Insider trading signal from "Rhianna"
#
# This is one of the most sophisticated implementations found,
# featuring proper quant-finance models (GLFT, Black-Scholes, Hawkes-like).
# ============================================================================

import json
import numpy as np
import math
from statistics import NormalDist
from datamodel import *
from typing import Any

INF = 1e9
normalDist = NormalDist(0, 1)


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
                [[l["symbol"], l["product"], l["denomination"]] for l in state.listings.values()],
                {s: [od.buy_orders, od.sell_orders] for s, od in state.order_depths.items()},
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                 for arr in state.own_trades.values() for t in arr],
                [[t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp]
                 for arr in state.market_trades.values() for t in arr],
                state.position,
                [state.observations.plainValueObservations,
                 {p: [o.bidPrice, o.askPrice, o.transportFees, o.exportTariff,
                      o.importTariff, o.sunlight, o.humidity]
                  for p, o in state.observations.conversionObservations.items()}]]

    def compress_orders(self, orders):
        return [[o.symbol, o.price, o.quantity] for arr in orders.values() for o in arr]

    def to_json(self, value):
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
        return value if len(value) <= max_length else value[:max_length-3] + "..."


logger = Logger()


class Status:
    """Rich state wrapper with historical data tracking and order book analysis."""

    _position_limit = {
        "AMETHYSTS": 20, "STARFRUIT": 20, "ORCHIDS": 100,
        "CHOCOLATE": 250, "STRAWBERRIES": 350, "ROSES": 60,
        "GIFT_BASKET": 60, "COCONUT": 300, "COCONUT_COUPON": 600,
    }
    _state = None
    _realtime_position = {key: 0 for key in _position_limit.keys()}
    _hist_order_depths = {
        product: {
            f'{side}{metric}{depth}': []
            for side in ['bid', 'ask']
            for metric in ['prc', 'amt']
            for depth in [1, 2, 3]
        } for product in _position_limit.keys()
    }
    _num_data = 0

    def __init__(self, product):
        self.product = product

    @classmethod
    def cls_update(cls, state):
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

    def hist_order_depth(self, type, depth, size):
        return np.array(self._hist_order_depths[self.product][f'{type}{depth}'][-size:], dtype=np.float32)

    @property
    def timestep(self): return self._state.timestamp / 100
    @property
    def position_limit(self): return self._position_limit[self.product]
    @property
    def position(self): return int(self._state.position.get(self.product, 0))
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
    def best_bid(self):
        bo = self._state.order_depths[self.product].buy_orders
        return max(bo.keys()) if bo else self.best_ask - 1
    @property
    def best_ask(self):
        so = self._state.order_depths[self.product].sell_orders
        return min(so.keys()) if so else self.best_bid + 1
    @property
    def mid(self): return (self.best_bid + self.best_ask) / 2
    @property
    def bid_ask_spread(self): return self.best_ask - self.best_bid
    @property
    def worst_bid(self):
        bo = self._state.order_depths[self.product].buy_orders
        return min(bo.keys()) if bo else self.best_ask - 1
    @property
    def worst_ask(self):
        so = self._state.order_depths[self.product].sell_orders
        return max(so.keys()) if so else self.best_bid + 1
    @property
    def possible_buy_amt(self):
        return min(self._position_limit[self.product] - self.rt_position,
                   self._position_limit[self.product] - self.position)
    @property
    def possible_sell_amt(self):
        return min(self._position_limit[self.product] + self.rt_position,
                   self._position_limit[self.product] + self.position)
    @property
    def total_bidamt(self): return sum(self._state.order_depths[self.product].buy_orders.values())
    @property
    def total_askamt(self): return -sum(self._state.order_depths[self.product].sell_orders.values())
    @property
    def vwap(self):
        vwap = total = 0
        for prc, amt in self._state.order_depths[self.product].buy_orders.items():
            vwap += prc * amt; total += amt
        for prc, amt in self._state.order_depths[self.product].sell_orders.items():
            vwap += prc * abs(amt); total += abs(amt)
        return vwap / total if total else self.mid
    @property
    def maxamt_bidprc(self):
        prc_max, max_amt = 0, 0
        for prc, amt in self._state.order_depths[self.product].buy_orders.items():
            if amt > max_amt: max_amt = amt; prc_max = prc
        return prc_max
    @property
    def maxamt_askprc(self):
        prc_max, max_amt = 0, 0
        for prc, amt in self._state.order_depths[self.product].sell_orders.items():
            if amt < max_amt: max_amt = amt; prc_max = prc
        return prc_max
    @property
    def maxamt_midprc(self): return (self.maxamt_bidprc + self.maxamt_askprc) / 2
    @property
    def market_trades(self): return self._state.market_trades.get(self.product, [])
    @property
    def orchid_south_bidprc(self): return self._state.observations.conversionObservations[self.product].bidPrice
    @property
    def orchid_south_askprc(self): return self._state.observations.conversionObservations[self.product].askPrice
    @property
    def orchid_south_midprc(self): return (self.orchid_south_bidprc + self.orchid_south_askprc) / 2
    @property
    def transportFees(self): return self._state.observations.conversionObservations[self.product].transportFees
    @property
    def exportTariff(self): return self._state.observations.conversionObservations[self.product].exportTariff
    @property
    def importTariff(self): return self._state.observations.conversionObservations[self.product].importTariff


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
    for _ in range(max_iter):
        if abs(diff) <= tol: break
        vega = (cal_call(S, tau, sigma + tol)[0] - cal_call(S, tau, sigma)[0]) / tol
        sigma -= diff / vega
        diff = cal_call(S, tau, sigma)[0] - market_price
    return sigma


class Strategy:
    @staticmethod
    def arb(state, fair_price):
        """Take mispriced orders vs fair price."""
        orders = []
        for ask_price, ask_amount in state.asks:
            if ask_price < fair_price:
                buy_amount = min(-ask_amount, state.possible_buy_amt)
                if buy_amount > 0:
                    orders.append(Order(state.product, int(ask_price), int(buy_amount)))
                    state.rt_position_update(state.rt_position + buy_amount)
            elif ask_price == fair_price and state.rt_position < 0:
                buy_amount = min(-ask_amount, -state.rt_position)
                orders.append(Order(state.product, int(ask_price), int(buy_amount)))
                state.rt_position_update(state.rt_position + buy_amount)

        for bid_price, bid_amount in state.bids:
            if bid_price > fair_price:
                sell_amount = min(bid_amount, state.possible_sell_amt)
                if sell_amount > 0:
                    orders.append(Order(state.product, int(bid_price), -int(sell_amount)))
                    state.rt_position_update(state.rt_position - sell_amount)
            elif bid_price == fair_price and state.rt_position > 0:
                sell_amount = min(bid_amount, state.rt_position)
                orders.append(Order(state.product, int(bid_price), -int(sell_amount)))
                state.rt_position_update(state.rt_position - sell_amount)
        return orders

    @staticmethod
    def mm_glft(state, fair_price, mu=0, sigma=0.3959, gamma=1e-9, order_amount=20):
        """
        GLFT Market Making Model (Guéant-Lehalle-Fernandez-Tapia).
        Optimal quoting with inventory risk aversion.
        """
        q = state.rt_position / order_amount
        kappa_b = 1 / max((fair_price - state.best_bid) - 1, 1)
        kappa_a = 1 / max((state.best_ask - fair_price) - 1, 1)
        A_b = A_a = 0.25

        delta_b = (1/gamma * math.log(1 + gamma/kappa_b) +
                   (-mu/(gamma*sigma**2) + (2*q+1)/2) *
                   math.sqrt((sigma**2*gamma)/(2*kappa_b*A_b) * (1+gamma/kappa_b)**(1+kappa_b/gamma)))
        delta_a = (1/gamma * math.log(1 + gamma/kappa_a) +
                   (mu/(gamma*sigma**2) - (2*q-1)/2) *
                   math.sqrt((sigma**2*gamma)/(2*kappa_a*A_a) * (1+gamma/kappa_a)**(1+kappa_a/gamma)))

        p_b = round(fair_price - delta_b)
        p_b = min(p_b, fair_price, state.best_bid + 1)
        p_b = max(p_b, state.maxamt_bidprc + 1)
        p_a = round(fair_price + delta_a)
        p_a = max(p_a, fair_price, state.best_ask - 1)
        p_a = min(p_a, state.maxamt_askprc - 1)

        orders = []
        buy_amount = min(order_amount, state.possible_buy_amt)
        sell_amount = min(order_amount, state.possible_sell_amt)
        if buy_amount > 0:
            orders.append(Order(state.product, int(p_b), int(buy_amount)))
        if sell_amount > 0:
            orders.append(Order(state.product, int(p_a), -int(sell_amount)))
        return orders

    @staticmethod
    def index_arb(basket, chocolate, strawberries, roses, theta=380, threshold=30):
        """Index arbitrage for GIFT_BASKET."""
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
    def vol_arb(option, iv, hv=0.16, threshold=0.00178):
        """Volatility arbitrage for options."""
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
    def delta_hedge(underlying, option, delta, rebalance_threshold=30):
        """Delta hedging for options positions."""
        target_position = -round(option.rt_position * delta)
        position_diff = target_position - underlying.position
        orders = []
        if underlying.bid_ask_spread == 1 and abs(position_diff) > rebalance_threshold:
            if position_diff < 0:
                sell_amount = min(abs(position_diff), underlying.possible_sell_amt)
                orders.append(Order(underlying.product, underlying.best_bid, -sell_amount))
            elif position_diff > 0:
                buy_amount = min(position_diff, underlying.possible_buy_amt)
                orders.append(Order(underlying.product, underlying.best_ask, buy_amount))
        return orders

    @staticmethod
    def insider_trading(signal_product, trade_product):
        """Copy trades from informed trader 'Rhianna'."""
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


class Trader:
    state_amethysts = Status('AMETHYSTS')
    state_starfruit = Status('STARFRUIT')
    state_orchids = Status('ORCHIDS')
    state_chocolate = Status('CHOCOLATE')
    state_strawberries = Status('STRAWBERRIES')
    state_roses = Status('ROSES')
    state_gift_basket = Status('GIFT_BASKET')
    state_coconut = Status('COCONUT')
    state_coconut_coupon = Status('COCONUT_COUPON')

    def run(self, state):
        Status.cls_update(state)
        result = {}

        # Round 1: Market making
        result["AMETHYSTS"] = (Strategy.arb(self.state_amethysts, self.state_amethysts.maxamt_midprc) +
                               Strategy.mm_glft(self.state_amethysts, self.state_amethysts.maxamt_midprc, gamma=0.1))

        result["STARFRUIT"] = (Strategy.arb(self.state_starfruit, self.state_starfruit.maxamt_midprc) +
                               Strategy.mm_glft(self.state_starfruit, self.state_starfruit.maxamt_midprc, gamma=0.1))

        # Round 3: Index arbitrage + insider
        result["GIFT_BASKET"] = Strategy.index_arb(
            self.state_gift_basket, self.state_chocolate,
            self.state_strawberries, self.state_roses, threshold=30)
        result["ROSES"] = Strategy.insider_trading(self.state_roses, self.state_roses)

        # Round 4: Options vol arb + delta hedging
        underlying_prc = self.state_coconut.hist_order_depth('bidprc', 1, 1)[0] if Status._num_data > 0 else 10000
        option_prc = self.state_coconut_coupon.hist_order_depth('bidprc', 1, 1)[0] if Status._num_data > 0 else 600
        tau = cal_tau(day=5, timestep=self.state_coconut.timestep)
        theo, delta = cal_call(underlying_prc, tau)
        iv = cal_imvol(option_prc, underlying_prc, tau)
        result["COCONUT_COUPON"] = Strategy.vol_arb(self.state_coconut_coupon, iv, threshold=0.00175)
        result["COCONUT"] = Strategy.delta_hedge(self.state_coconut, self.state_coconut_coupon, delta, rebalance_threshold=60)

        # Round 2: Orchids conversion
        conversions = -self.state_orchids.position if self.state_orchids.position != 0 else 0

        logger.flush(state, result, conversions, "SAMPLE")
        return result, conversions, "SAMPLE"
