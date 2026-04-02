"""
IMC Prosperity 1 (2023) - Trading Algorithm
Team: Stanford Cardinal (2nd Place Overall)
Source: https://github.com/ShubhamAnandJain/IMC-Prosperity-2023-Stanford-Cardinal
File: trader.py

Products: PEARLS (stable, fair value = 10000), BANANAS (dynamic, regression-based)
Key Strategy for PEARLS:
- Hardcoded fair value: acc_bid = 10000, acc_ask = 10000
- Aggressively takes orders below/above fair value
- Position-aware: buys at bid when short, sells at ask when long
- Undercutting: places orders 1 tick inside best bid/ask
- Multiple order layers with position-dependent pricing
- Additional aggressive pricing when position > 15 or < -15
"""

from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order
import collections
from collections import defaultdict
import random
import math
import copy
import numpy as np

empty_dict = {'PEARLS' : 0, 'BANANAS' : 0, 'COCONUTS' : 0, 'PINA_COLADAS' : 0, 'BERRIES' : 250, 'DIVING_GEAR' : 0, 'DIP' : 0, 'BAGUETTE': 0, 'UKULELE' : 0, 'PICNIC_BASKET' : 0}


def def_value():
    return copy.deepcopy(empty_dict)

INF = int(1e9)

class Trader:

    position = copy.deepcopy(empty_dict)
    POSITION_LIMIT = {
        'PEARLS' : 20,
        'BANANAS' : 20,
        'COCONUTS' : 600,
        'PINA_COLADAS' : 300,
        'BERRIES' : 250,
        'DIVING_GEAR' : 50,
        'DIP' : 300,
        'BAGUETTE': 150,
        'UKULELE' : 70,
        'PICNIC_BASKET' : 70
    }
    volume_traded = copy.deepcopy(empty_dict)

    person_position = defaultdict(def_value)
    person_actvalof_position = defaultdict(def_value)

    cpnl = defaultdict(lambda : 0)
    bananas_cache = []
    coconuts_cache = []
    bananas_dim = 4
    coconuts_dim = 3
    steps = 0
    last_dolphins = -1
    buy_gear = False
    sell_gear = False
    buy_berries = False
    sell_berries = False
    close_berries = False
    last_dg_price = 0
    start_berries = 0
    first_berries = 0
    cont_buy_basket_unfill = 0
    cont_sell_basket_unfill = 0

    halflife_diff = 5
    alpha_diff = 1 - np.exp(-np.log(2)/halflife_diff)

    halflife_price = 5
    alpha_price = 1 - np.exp(-np.log(2)/halflife_price)

    halflife_price_dip = 20
    alpha_price_dip = 1 - np.exp(-np.log(2)/halflife_price_dip)

    begin_diff_dip = -INF
    begin_diff_bag = -INF
    begin_bag_price = -INF
    begin_dip_price = -INF

    std = 25
    basket_std = 117

    def calc_next_price_bananas(self):
        """AR(4) regression model for BANANAS price prediction.
        Uses cached mid prices from last 4 ticks."""
        coef = [-0.01869561,  0.0455032 ,  0.16316049,  0.8090892]
        intercept = 4.481696494462085
        nxt_price = intercept
        for i, val in enumerate(self.bananas_cache):
            nxt_price += val * coef[i]

        return int(round(nxt_price))

    def values_extract(self, order_dict, buy=0):
        """Extract total volume and best price from order dictionary.
        For sell orders (buy=0), volumes are negated.
        Returns (total_volume, best_price_by_volume)."""
        tot_vol = 0
        best_val = -1
        mxvol = -1

        for ask, vol in order_dict.items():
            if(buy==0):
                vol *= -1
            tot_vol += vol
            if tot_vol > mxvol:
                mxvol = vol
                best_val = ask

        return tot_vol, best_val

    def compute_orders_pearls(self, product, order_depth, acc_bid, acc_ask):
        """Market making for PEARLS (stable product).

        Phase 1 - Taking: Buy all asks < acc_bid (10000). If we're short,
        also buy at acc_bid to flatten.

        Phase 2 - Making: Place passive bid/ask orders.
        - Undercut: place 1 tick inside best bid/ask
        - Position-aware: more aggressive when inventory is skewed
          - When short (pos < 0): bid more aggressively (undercut_buy + 1)
          - When long (pos > 15): bid less aggressively (undercut_buy - 1)
          - Symmetric logic for asks
        """
        orders: list[Order] = []

        osell = collections.OrderedDict(sorted(order_depth.sell_orders.items()))
        obuy = collections.OrderedDict(sorted(order_depth.buy_orders.items(), reverse=True))

        sell_vol, best_sell_pr = self.values_extract(osell)
        buy_vol, best_buy_pr = self.values_extract(obuy, 1)

        cpos = self.position[product]

        mx_with_buy = -1

        # PHASE 1: TAKING - Buy anything below fair value
        for ask, vol in osell.items():
            if ((ask < acc_bid) or ((self.position[product]<0) and (ask == acc_bid))) and cpos < self.POSITION_LIMIT['PEARLS']:
                mx_with_buy = max(mx_with_buy, ask)
                order_for = min(-vol, self.POSITION_LIMIT['PEARLS'] - cpos)
                cpos += order_for
                assert(order_for >= 0)
                orders.append(Order(product, ask, order_for))

        mprice_actual = (best_sell_pr + best_buy_pr)/2
        mprice_ours = (acc_bid+acc_ask)/2

        undercut_buy = best_buy_pr + 1
        undercut_sell = best_sell_pr - 1

        bid_pr = min(undercut_buy, acc_bid-1) # we will shift this by 1 to beat this price
        sell_pr = max(undercut_sell, acc_ask+1)

        # PHASE 2: MAKING - Passive quotes with position-dependent pricing
        # When short: bid more aggressively to flatten
        if (cpos < self.POSITION_LIMIT['PEARLS']) and (self.position[product] < 0):
            num = min(40, self.POSITION_LIMIT['PEARLS'] - cpos)
            orders.append(Order(product, min(undercut_buy + 1, acc_bid-1), num))
            cpos += num

        # When very long: bid less aggressively (don't want more inventory)
        if (cpos < self.POSITION_LIMIT['PEARLS']) and (self.position[product] > 15):
            num = min(40, self.POSITION_LIMIT['PEARLS'] - cpos)
            orders.append(Order(product, min(undercut_buy - 1, acc_bid-1), num))
            cpos += num

        # Default passive bid
        if cpos < self.POSITION_LIMIT['PEARLS']:
            num = min(40, self.POSITION_LIMIT['PEARLS'] - cpos)
            orders.append(Order(product, bid_pr, num))
            cpos += num

        cpos = self.position[product]

        # PHASE 1: TAKING - Sell anything above fair value
        for bid, vol in obuy.items():
            if ((bid > acc_ask) or ((self.position[product]>0) and (bid == acc_ask))) and cpos > -self.POSITION_LIMIT['PEARLS']:
                order_for = max(-vol, -self.POSITION_LIMIT['PEARLS']-cpos)
                # order_for is a negative number denoting how much we will sell
                cpos += order_for
                assert(order_for <= 0)
                orders.append(Order(product, bid, order_for))

        # When long: ask more aggressively to flatten
        if (cpos > -self.POSITION_LIMIT['PEARLS']) and (self.position[product] > 0):
            num = max(-40, -self.POSITION_LIMIT['PEARLS']-cpos)
            orders.append(Order(product, max(undercut_sell-1, acc_ask+1), num))
            cpos += num

        # When very short: ask less aggressively (don't want more short)
        if (cpos > -self.POSITION_LIMIT['PEARLS']) and (self.position[product] < -15):
            num = max(-40, -self.POSITION_LIMIT['PEARLS']-cpos)
            orders.append(Order(product, max(undercut_sell+1, acc_ask+1), num))
            cpos += num

        # Default passive ask
        if cpos > -self.POSITION_LIMIT['PEARLS']:
            num = max(-40, -self.POSITION_LIMIT['PEARLS']-cpos)
            orders.append(Order(product, sell_pr, num))
            cpos += num

        return orders

    def compute_orders_regression(self, product, order_depth, acc_bid, acc_ask, LIMIT):
        """Market making for BANANAS using regression-predicted fair value.
        Similar structure to PEARLS but uses predicted price from AR model."""
        orders: list[Order] = []

        osell = collections.OrderedDict(sorted(order_depth.sell_orders.items()))
        obuy = collections.OrderedDict(sorted(order_depth.buy_orders.items(), reverse=True))

        sell_vol, best_sell_pr = self.values_extract(osell)
        buy_vol, best_buy_pr = self.values_extract(obuy, 1)

        cpos = self.position[product]

        for ask, vol in osell.items():
            if ((ask <= acc_bid) or ((self.position[product]<0) and (ask == acc_bid+1))) and cpos < LIMIT:
                order_for = min(-vol, LIMIT - cpos)
                cpos += order_for
                assert(order_for >= 0)
                orders.append(Order(product, ask, order_for))

        undercut_buy = best_buy_pr + 1
        undercut_sell = best_sell_pr - 1

        bid_pr = min(undercut_buy, acc_bid) # we will shift this by 1 to beat this price
        sell_pr = max(undercut_sell, acc_ask)

        if cpos < LIMIT:
            num = LIMIT - cpos
            orders.append(Order(product, bid_pr, num))
            cpos += num

        cpos = self.position[product]

        for bid, vol in obuy.items():
            if ((bid >= acc_ask) or ((self.position[product]>0) and (bid+1 == acc_ask))) and cpos > -LIMIT:
                order_for = max(-vol, -LIMIT-cpos)
                cpos += order_for
                assert(order_for <= 0)
                orders.append(Order(product, bid, order_for))

        if cpos > -LIMIT:
            num = -LIMIT-cpos
            orders.append(Order(product, sell_pr, num))
            cpos += num

        return orders

    def run(self, state: TradingState) -> Dict[str, List[Order]]:
        """Main entry point called each tick.

        For PEARLS: Uses hardcoded fair value of 10000
        For BANANAS: Uses AR(4) regression model to predict next price
        """
        result = {'PEARLS' : [], 'BANANAS' : []}

        # Update positions from state
        for key, val in state.position.items():
            self.position[key] = val

        # Track counterparty positions (for other strategies)
        for key, val in state.own_trades.items():
            for trade in val:
                if trade.timestamp != state.timestamp - 100:
                    continue
                if trade.buyer == "SUBMISSION":
                    self.volume_traded[key] += abs(trade.quantity)
                if trade.seller == "SUBMISSION":
                    self.volume_traded[key] += abs(trade.quantity)

        # PEARLS: Hardcoded fair value market making
        # acc_bid = acc_ask = 10000 (acceptable bid and ask prices)
        try:
            result['PEARLS'] = self.compute_orders_pearls(
                'PEARLS',
                state.order_depths['PEARLS'],
                10000,  # acc_bid: buy anything at or below this
                10000   # acc_ask: sell anything at or above this
            )
        except Exception as e:
            print("Error in PEARLS: ", e)

        # BANANAS: Regression-predicted fair value market making
        try:
            order_depth = state.order_depths['BANANAS']
            osell = collections.OrderedDict(sorted(order_depth.sell_orders.items()))
            obuy = collections.OrderedDict(sorted(order_depth.buy_orders.items(), reverse=True))

            best_sell_pr = next(iter(osell))
            best_buy_pr = next(iter(obuy))

            mid_price = (best_sell_pr + best_buy_pr) / 2

            self.bananas_cache.append(mid_price)
            if len(self.bananas_cache) > self.bananas_dim:
                self.bananas_cache.pop(0)

            if len(self.bananas_cache) == self.bananas_dim:
                INF = 1e9
                banana_lb = -INF
                banana_ub = INF

                next_price = self.calc_next_price_bananas()
                banana_lb = next_price - 1
                banana_ub = next_price + 1

                result['BANANAS'] = self.compute_orders_regression(
                    'BANANAS',
                    order_depth,
                    banana_lb,
                    banana_ub,
                    self.POSITION_LIMIT['BANANAS']
                )
        except Exception as e:
            print("Error in BANANAS: ", e)

        self.steps += 1
        return result
