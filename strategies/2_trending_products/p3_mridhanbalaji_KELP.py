"""
SOURCE: mridhanbalaji - IMC Prosperity 3
REPO: https://github.com/mridhanbalaji/IMC_Prosperity_3
FILE: round1/round1_FINAL.py
PRODUCT: KELP (trending/drifting product in Prosperity 3)

KEY TECHNIQUES FOR KELP:
- Uses the SAME take->clear->make framework as Linear Utility (2nd place Prosp 2)
- Fair value set as a static constant (2026) -- this is notably a DIFFERENT approach
  from other teams, treating Kelp as quasi-static over each trading session
- adverse_volume filtering disabled (prevent_adverse=False)
- Tight default_edge of 1 tick for market making
- This demonstrates that even a static fair value approach can work for a mildly
  drifting product when combined with good market making mechanics

COMPARISON: This team merged their partner's RESIN/KELP code with their own
SQUID_INK RSI-based strategy.
"""

from datamodel import OrderDepth, TradingState, Order
from typing import List
import jsonpickle
import math


class Product:
    RAINFOREST_RESIN = "RAINFOREST_RESIN"
    KELP = "KELP"
    SQUID_INK = "SQUID_INK"


PARAMS = {
    Product.RAINFOREST_RESIN: {
        "fair_value": 10000,
        "take_width": 1,
        "clear_width": 0,
        "disregard_edge": 1,
        "join_edge": 2,
        "default_edge": 4,
        "soft_position_limit": 50,
    },
    Product.KELP: {
        "fair_value": 2026,           # Static fair value for Kelp!
        "take_width": 1,
        "clear_width": 0,
        "prevent_adverse": False,      # No adverse selection filtering
        "adverse_volume": 10,
        "reversion_beta": 0.0,         # No reversion signal
        "disregard_edge": 1,
        "join_edge": 0,
        "default_edge": 1,            # Tight 1-tick default edge
    },
    Product.SQUID_INK: {
        "take_width": 1,
        "clear_width": 0,
        "prevent_adverse": True,
        "adverse_volume": 25,
        "reversion_beta": -0.3,
        "disregard_edge": 1,
        "join_edge": 0,
        "default_edge": 1,
    },
}


class Trader:
    def __init__(self, params=None):
        if params is None:
            params = PARAMS
        self.params = params
        self.LIMIT = {
            Product.RAINFOREST_RESIN: 50,
            Product.KELP: 50,
            Product.SQUID_INK: 50,
        }

    def take_best_orders(self, product, fair_value, take_width, orders,
                         order_depth, position, buy_order_volume,
                         sell_order_volume, prevent_adverse=False,
                         adverse_volume=0):
        position_limit = self.LIMIT[product]

        if len(order_depth.sell_orders) != 0:
            best_ask = min(order_depth.sell_orders.keys())
            best_ask_amount = -1 * order_depth.sell_orders[best_ask]
            if (not prevent_adverse) or (abs(best_ask_amount) <= adverse_volume):
                if best_ask <= fair_value - take_width:
                    quantity = min(best_ask_amount, position_limit - position)
                    if quantity > 0:
                        orders.append(Order(product, best_ask, quantity))
                        buy_order_volume += quantity
                        order_depth.sell_orders[best_ask] += quantity
                        if order_depth.sell_orders[best_ask] == 0:
                            del order_depth.sell_orders[best_ask]

        if len(order_depth.buy_orders) != 0:
            best_bid = max(order_depth.buy_orders.keys())
            best_bid_amount = order_depth.buy_orders[best_bid]
            if (not prevent_adverse) or (abs(best_bid_amount) <= adverse_volume):
                if best_bid >= fair_value + take_width:
                    quantity = min(best_bid_amount, position_limit + position)
                    if quantity > 0:
                        orders.append(Order(product, best_bid, -1 * quantity))
                        sell_order_volume += quantity
                        order_depth.buy_orders[best_bid] -= quantity
                        if order_depth.buy_orders[best_bid] == 0:
                            del order_depth.buy_orders[best_bid]

        return buy_order_volume, sell_order_volume

    def market_make(self, product, orders, bid, ask, position,
                    buy_order_volume, sell_order_volume):
        buy_quantity = self.LIMIT[product] - (position + buy_order_volume)
        if buy_quantity > 0:
            orders.append(Order(product, round(bid), buy_quantity))
        sell_quantity = self.LIMIT[product] + (position - sell_order_volume)
        if sell_quantity > 0:
            orders.append(Order(product, round(ask), -sell_quantity))
        return buy_order_volume, sell_order_volume

    def clear_position_order(self, product, fair_value, width, orders,
                             order_depth, position, buy_order_volume,
                             sell_order_volume):
        position_after_take = position + buy_order_volume - sell_order_volume
        fair_for_bid = round(fair_value - width)
        fair_for_ask = round(fair_value + width)
        buy_quantity = self.LIMIT[product] - (position + buy_order_volume)
        sell_quantity = self.LIMIT[product] + (position - sell_order_volume)

        if position_after_take > 0:
            clear_quantity = sum(
                volume for price, volume in order_depth.buy_orders.items()
                if price >= fair_for_ask
            )
            clear_quantity = min(clear_quantity, position_after_take)
            sent_quantity = min(sell_quantity, clear_quantity)
            if sent_quantity > 0:
                orders.append(Order(product, fair_for_ask, -abs(sent_quantity)))
                sell_order_volume += abs(sent_quantity)

        if position_after_take < 0:
            clear_quantity = sum(
                abs(volume) for price, volume in order_depth.sell_orders.items()
                if price <= fair_for_bid
            )
            clear_quantity = min(clear_quantity, abs(position_after_take))
            sent_quantity = min(buy_quantity, clear_quantity)
            if sent_quantity > 0:
                orders.append(Order(product, fair_for_bid, abs(sent_quantity)))
                buy_order_volume += abs(sent_quantity)

        return buy_order_volume, sell_order_volume

    def take_orders(self, product, order_depth, fair_value, take_width,
                    position, prevent_adverse=False, adverse_volume=0):
        orders = []
        buy_order_volume = 0
        sell_order_volume = 0
        buy_order_volume, sell_order_volume = self.take_best_orders(
            product, fair_value, take_width, orders, order_depth,
            position, buy_order_volume, sell_order_volume,
            prevent_adverse, adverse_volume
        )
        return orders, buy_order_volume, sell_order_volume

    def clear_orders(self, product, order_depth, fair_value, clear_width,
                     position, buy_order_volume, sell_order_volume):
        orders = []
        buy_order_volume, sell_order_volume = self.clear_position_order(
            product, fair_value, clear_width, orders, order_depth,
            position, buy_order_volume, sell_order_volume
        )
        return orders, buy_order_volume, sell_order_volume

    def make_orders(self, product, order_depth, fair_value, position,
                    buy_order_volume, sell_order_volume, disregard_edge,
                    join_edge, default_edge, manage_position=False,
                    soft_position_limit=0):
        orders = []
        asks_above_fair = [
            price for price in order_depth.sell_orders.keys()
            if price > fair_value + disregard_edge
        ]
        bids_below_fair = [
            price for price in order_depth.buy_orders.keys()
            if price < fair_value - disregard_edge
        ]

        best_ask_above_fair = min(asks_above_fair) if asks_above_fair else None
        best_bid_below_fair = max(bids_below_fair) if bids_below_fair else None

        ask = round(fair_value + default_edge)
        if best_ask_above_fair is not None:
            if abs(best_ask_above_fair - fair_value) <= join_edge:
                ask = best_ask_above_fair
            else:
                ask = best_ask_above_fair - 1

        bid = round(fair_value - default_edge)
        if best_bid_below_fair is not None:
            if abs(fair_value - best_bid_below_fair) <= join_edge:
                bid = best_bid_below_fair
            else:
                bid = best_bid_below_fair + 1

        if manage_position:
            if position > soft_position_limit:
                ask -= 1
            elif position < -soft_position_limit:
                bid += 1

        buy_order_volume, sell_order_volume = self.market_make(
            product, orders, bid, ask, position,
            buy_order_volume, sell_order_volume
        )
        return orders, buy_order_volume, sell_order_volume

    def rsi_squid_ink_logic(self, state, trader_state):
        """RSI-based strategy for SQUID_INK."""
        orders = []
        product = Product.SQUID_INK
        order_depth = state.order_depths[product]
        position = state.position.get(product, 0)
        limit = self.LIMIT[product]

        mid_price = None
        if order_depth.buy_orders and order_depth.sell_orders:
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            mid_price = (best_bid + best_ask) / 2.0

        if mid_price is not None:
            if "prices" not in trader_state:
                trader_state["prices"] = []
            trader_state["prices"].append(mid_price)
            if len(trader_state["prices"]) > 20:
                trader_state["prices"] = trader_state["prices"][-20:]

            prices = trader_state["prices"]
            period = min(14, len(prices))
            if period >= 2:
                deltas = [prices[i] - prices[i-1] for i in range(-period+1, 0)]
                gains = [d for d in deltas if d > 0]
                losses = [-d for d in deltas if d < 0]
                avg_gain = sum(gains)/period if gains else 0
                avg_loss = sum(losses)/period if losses else 0
                if avg_loss == 0:
                    rsi = 100
                else:
                    rs = avg_gain / avg_loss
                    rsi = 100 - (100/(1 + rs))
            else:
                rsi = 50

            # RSI-based entry signals
            if order_depth.sell_orders:
                best_ask = min(order_depth.sell_orders.keys())
                ask_qty = order_depth.sell_orders[best_ask]
                can_buy = limit - position
                if best_ask < 1900 and rsi < 30 and can_buy > 0:
                    quantity = min(5, can_buy, -ask_qty)
                    if quantity > 0:
                        orders.append(Order(product, best_ask, quantity))

            if order_depth.buy_orders:
                best_bid = max(order_depth.buy_orders.keys())
                bid_qty = order_depth.buy_orders[best_bid]
                can_sell = limit + position
                if best_bid > 2100 and rsi > 70 and can_sell > 0:
                    quantity = min(5, can_sell, bid_qty)
                    if quantity > 0:
                        orders.append(Order(product, best_bid, -quantity))

        return orders

    def run(self, state):
        try:
            trader_dict = jsonpickle.decode(state.traderData)
            if not isinstance(trader_dict, dict):
                trader_dict = {}
        except:
            trader_dict = {}

        result = {}

        # RAINFOREST_RESIN: exact partner take->clear->make logic
        if Product.RAINFOREST_RESIN in self.params and Product.RAINFOREST_RESIN in state.order_depths:
            product = Product.RAINFOREST_RESIN
            od = state.order_depths[product]
            position = state.position.get(product, 0)
            fv = self.params[product]["fair_value"]

            resin_orders, bv, sv = self.take_orders(product, od, fv,
                self.params[product]["take_width"], position)
            resin_clear, bv, sv = self.clear_orders(product, od, fv,
                self.params[product]["clear_width"], position, bv, sv)
            resin_make, _, _ = self.make_orders(product, od, fv, position,
                bv, sv, self.params[product]["disregard_edge"],
                self.params[product]["join_edge"],
                self.params[product]["default_edge"],
                True, self.params[product]["soft_position_limit"])
            result[product] = resin_orders + resin_clear + resin_make

        # KELP: same take->clear->make with static fair value
        if Product.KELP in self.params and Product.KELP in state.order_depths:
            product = Product.KELP
            od = state.order_depths[product]
            position = state.position.get(product, 0)
            fv = self.params[product]["fair_value"]

            kelp_orders, bv, sv = self.take_orders(product, od, fv,
                self.params[product]["take_width"], position,
                self.params[product].get("prevent_adverse", False),
                self.params[product].get("adverse_volume", 0))
            kelp_clear, bv, sv = self.clear_orders(product, od, fv,
                self.params[product]["clear_width"], position, bv, sv)
            kelp_make, _, _ = self.make_orders(product, od, fv, position,
                bv, sv, self.params[product]["disregard_edge"],
                self.params[product]["join_edge"],
                self.params[product]["default_edge"])
            result[product] = kelp_orders + kelp_clear + kelp_make

        # SQUID_INK: RSI-based approach
        if Product.SQUID_INK in self.params and Product.SQUID_INK in state.order_depths:
            result[Product.SQUID_INK] = self.rsi_squid_ink_logic(state, trader_dict)

        conversions = 1
        traderData = jsonpickle.encode(trader_dict)
        return result, conversions, traderData
