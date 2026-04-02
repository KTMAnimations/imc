"""
IMC Prosperity 3 - ShivUCSD1104 Team
Round 2: Picnic Basket VWAP-based Arbitrage with Full Hedging
Source: https://github.com/ShivUCSD1104/IMC-Prosperity-3/blob/main/Final%20Submissions/round2Final.py

Strategy:
- Computes synthetic fair value using VWAP of constituent bid orders
  - BASKET1 FV = 6*CROISSANTS_vwap + 3*JAMS_vwap + 1*DJEMBES_vwap
  - BASKET2 FV = 4*CROISSANTS_vwap + 2*JAMS_vwap
- When basket market ask < synthetic FV: buy basket, sell constituents (hedge)
- When basket market bid > synthetic FV: sell basket, buy constituents (hedge)
- Hedge volumes computed per-component and executed at best available prices
- Clean separation of basket strategy and hedge execution
"""

from typing import Dict, List, Tuple
from datamodel import Order, OrderDepth, TradingState
import json
import numpy as np

class Trader:

    ###########################
    ######## ROUND 2 ##########
    ###########################

    def picnic_basket1_strategy(self, state: TradingState, order_depth: OrderDepth) -> Tuple[List[Order], Dict[str, int]]:
        """
        KEY BASKET ARBITRAGE:
        - Compute synthetic FV from VWAP of constituent bid orders
        - Buy basket when market ask < synthetic FV
        - Sell basket when market bid > synthetic FV
        - Return hedge volumes to be executed on constituents
        """
        product = "PICNIC_BASKET1"
        LIMIT = 60
        CROISSANTS, JAMS, DJEMBES = 6, 3, 1

        orders: List[Order] = []
        hedge_volumes: Dict[str, int] = {"CROISSANTS": 0, "JAMS": 0, "DJEMBES": 0}
        position = state.position.get(product, 0)

        cro_depth = state.order_depths.get("CROISSANTS")
        jam_depth = state.order_depths.get("JAMS")
        djem_depth = state.order_depths.get("DJEMBES")
        basket_depth = order_depth

        if not cro_depth or not jam_depth or not djem_depth:
            return orders, hedge_volumes

        # VWAP from bid side of constituents
        cro_vwap = sum([p * abs(v) for p, v in cro_depth.buy_orders.items()]) / max(sum([abs(v) for v in cro_depth.buy_orders.values()]), 1)
        jam_vwap = sum([p * abs(v) for p, v in jam_depth.buy_orders.items()]) / max(sum([abs(v) for v in jam_depth.buy_orders.values()]), 1)
        djem_vwap = sum([p * abs(v) for p, v in djem_depth.buy_orders.items()]) / max(sum([abs(v) for v in djem_depth.buy_orders.values()]), 1)

        synthetic_fair_value = CROISSANTS * cro_vwap + JAMS * jam_vwap + DJEMBES * djem_vwap

        # Buy basket if ask < synthetic FV
        for ask in sorted(basket_depth.sell_orders):
            if ask < synthetic_fair_value and position < LIMIT:
                volume = basket_depth.sell_orders[ask]
                orders.append(Order(product, ask, volume))
                hedge_volumes["CROISSANTS"] += volume * CROISSANTS
                hedge_volumes["JAMS"] += volume * JAMS
                hedge_volumes["DJEMBES"] += volume * DJEMBES
                break

        # Sell basket if bid > synthetic FV
        for bid in sorted(basket_depth.buy_orders, reverse=True):
            if bid > synthetic_fair_value and position > -LIMIT:
                volume = -basket_depth.buy_orders[bid]
                orders.append(Order(product, bid, volume))
                hedge_volumes["CROISSANTS"] += volume * CROISSANTS
                hedge_volumes["JAMS"] += volume * JAMS
                hedge_volumes["DJEMBES"] += volume * DJEMBES
                break

        return orders, hedge_volumes

    def picnic_basket2_strategy(self, state: TradingState, order_depth: OrderDepth) -> Tuple[List[Order], Dict[str, int]]:
        product = "PICNIC_BASKET2"
        LIMIT = 100
        CROISSANTS, JAMS = 4, 2

        orders: List[Order] = []
        hedge_volumes: Dict[str, int] = {"CROISSANTS": 0, "JAMS": 0}
        position = state.position.get(product, 0)

        cro_depth = state.order_depths.get("CROISSANTS")
        jam_depth = state.order_depths.get("JAMS")
        basket_depth = order_depth

        if not cro_depth or not jam_depth:
            return orders, hedge_volumes

        cro_vwap = sum([p * abs(v) for p, v in cro_depth.buy_orders.items()]) / max(sum([abs(v) for v in cro_depth.buy_orders.values()]), 1)
        jam_vwap = sum([p * abs(v) for p, v in jam_depth.buy_orders.items()]) / max(sum([abs(v) for v in jam_depth.buy_orders.values()]), 1)

        synthetic_fair_value = CROISSANTS * cro_vwap + JAMS * jam_vwap

        for ask in sorted(basket_depth.sell_orders):
            if ask < synthetic_fair_value and position < LIMIT:
                volume = basket_depth.sell_orders[ask]
                orders.append(Order(product, ask, volume))
                hedge_volumes["CROISSANTS"] += volume * CROISSANTS
                hedge_volumes["JAMS"] += volume * JAMS

        for bid in sorted(basket_depth.buy_orders, reverse=True):
            if bid > synthetic_fair_value and position > -LIMIT:
                volume = -basket_depth.buy_orders[bid]
                orders.append(Order(product, bid, volume))
                hedge_volumes["CROISSANTS"] += volume * CROISSANTS
                hedge_volumes["JAMS"] += volume * JAMS

        return orders, hedge_volumes

    def croissants_strategy(self, state: TradingState, order_depth: OrderDepth, hedge_volume: int) -> List[Order]:
        """Execute hedge trades for CROISSANTS based on basket trades."""
        LIMIT = 250
        product = "CROISSANTS"
        position = state.position.get(product, 0)

        if hedge_volume == 0 or abs(position + hedge_volume) > LIMIT:
            return []

        orders = []
        if hedge_volume > 0:
            best_ask = min(order_depth.sell_orders)
            orders.append(Order(product, best_ask, hedge_volume))
        else:
            best_bid = max(order_depth.buy_orders)
            orders.append(Order(product, best_bid, hedge_volume))
        return orders

    def jams_strategy(self, state: TradingState, order_depth: OrderDepth, hedge_volume: int) -> List[Order]:
        """Execute hedge trades for JAMS based on basket trades."""
        LIMIT = 350
        product = "JAMS"
        position = state.position.get(product, 0)

        if hedge_volume == 0 or abs(position + hedge_volume) > LIMIT:
            return []

        orders = []
        if hedge_volume > 0:
            best_ask = min(order_depth.sell_orders)
            orders.append(Order(product, best_ask, hedge_volume))
        else:
            best_bid = max(order_depth.buy_orders)
            orders.append(Order(product, best_bid, hedge_volume))
        return orders

    def djembes_strategy(self, state: TradingState, order_depth: OrderDepth, hedge_volume: int) -> List[Order]:
        """Execute hedge trades for DJEMBES based on basket trades."""
        LIMIT = 60
        product = "DJEMBES"
        position = state.position.get(product, 0)

        if hedge_volume == 0 or abs(position + hedge_volume) > LIMIT:
            return []

        orders = []
        if hedge_volume > 0:
            best_ask = min(order_depth.sell_orders)
            orders.append(Order(product, best_ask, hedge_volume))
        else:
            best_bid = max(order_depth.buy_orders)
            orders.append(Order(product, best_bid, hedge_volume))
        return orders

    def run(self, state: TradingState):
        result = {}
        conversions = 0

        try:
            trader_data = json.loads(state.traderData) if state.traderData else {}
        except Exception:
            trader_data = {}

        hedge_volumes = {"CROISSANTS": 0, "JAMS": 0, "DJEMBES": 0}

        for product in state.order_depths:
            if product == "PICNIC_BASKET1":
                orders, hedges = self.picnic_basket1_strategy(state, state.order_depths[product])
                result[product] = orders
                for k, v in hedges.items():
                    hedge_volumes[k] += v
            elif product == "PICNIC_BASKET2":
                orders, hedges = self.picnic_basket2_strategy(state, state.order_depths[product])
                result[product] = orders
                for k, v in hedges.items():
                    hedge_volumes[k] += v

        # Execute hedge orders for constituents
        for product in state.order_depths:
            if product == "CROISSANTS":
                result[product] = self.croissants_strategy(state, state.order_depths[product], hedge_volumes["CROISSANTS"])
            elif product == "JAMS":
                result[product] = self.jams_strategy(state, state.order_depths[product], hedge_volumes["JAMS"])
            elif product == "DJEMBES":
                result[product] = self.djembes_strategy(state, state.order_depths[product], hedge_volumes["DJEMBES"])

        traderData = json.dumps({})
        return result, conversions, traderData
