# ============================================================================
# SOURCE: https://github.com/CarterT27/imc-prosperity-3
# TEAM: Alpha Animals (CarterT27) - 9th Global, 2nd USA, Peak 2nd Global
# FILE: trader.py (final submission, all rounds combined)
# SCORE: 1,190,077 SeaShells
#
# KEY SQUID INK STRATEGY (squid_ink_strategy method):
#   - Volatility spike mean-reversion: detect price movements >3 std devs
#     from a 10-timestamp moving window
#   - Take positions opposite to extreme moves, betting on mean reversion
#   - Insider signal integration: track Olivia's buy/sell regime
#   - Position time management: close positions after max_position_time
#   - copy_olivia_trades: aggressive Olivia copy-trading as second approach
#
# Strategy parameters:
#   squid_ink_volatility_threshold = 3.0 (std devs)
#   squid_ink_momentum_period = 10
#   squid_ink_mean_window = 30
#   squid_ink_deviation_threshold = 0.05 (5% from mean)
#   squid_ink_max_position_time = 5 (timestamps)
# ============================================================================

import json
import math
import statistics
import typing
from typing import Tuple, Any, List, Dict

import jsonpickle
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.max_log_length = 2000
        self.logs: str = ""

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state, orders, conversions, trader_data):
        base_payload = [
            self._partial_state(state, ""),
            self.compress_orders(orders),
            conversions, "", "",
        ]
        base_len = len(self.to_json(base_payload))
        max_item = max((self.max_log_length - base_len) // 3, 0)
        payload = [
            self._partial_state(state, self.truncate(state.traderData, max_item)),
            self.compress_orders(orders),
            conversions,
            self.truncate(trader_data, max_item),
            self.truncate(self.logs, max_item),
        ]
        print(self.to_json(payload))
        self.logs = ""

    def _partial_state(self, state, trader_data):
        return [
            state.timestamp, trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            [], [], state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings):
        return [[l.symbol, l.product, l.denomination] for l in listings.values()]

    def compress_order_depths(self, order_depths):
        return {sym: [od.buy_orders, od.sell_orders] for sym, od in order_depths.items()}

    def compress_trades(self, trades):
        compressed = []
        for arr in trades.values():
            for t in arr:
                compressed.append([t.symbol, t.price, t.quantity, t.buyer, t.seller, t.timestamp])
        return compressed

    def compress_observations(self, obs):
        conv = {}
        for p, v in obs.conversionObservations.items():
            conv[p] = [v.bidPrice, v.askPrice, v.transportFees, v.exportTariff,
                       v.importTariff, v.sugarPrice, v.sunlightIndex]
        return [obs.plainValueObservations, conv]

    def compress_orders(self, orders):
        compressed = []
        for arr in orders.values():
            for o in arr:
                compressed.append([o.symbol, o.price, o.quantity])
        return compressed

    def to_json(self, v):
        return json.dumps(v, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value, max_length):
        lo, hi = 0, min(len(value), max_length)
        best = ""
        while lo <= hi:
            mid = (lo + hi) // 2
            cand = value[:mid] + ("..." if mid < len(value) else "")
            enc = json.dumps(cand)
            if len(enc) <= max_length:
                best = cand
                lo = mid + 1
            else:
                hi = mid - 1
        return best


logger = Logger()


class Trader:
    def __init__(self):
        self.kelp_prices = []
        self.resin_prices = []
        self.squid_ink_prices = []
        self.croissants_prices = []
        self.jams_prices = []
        self.djembes_prices = []
        self.kelp_vwap = []
        self.resin_vwap = []
        self.squid_ink_vwap = []
        self.croissants_vwap = []
        self.jams_vwap = []
        self.djembes_vwap = []
        self.insider_id = "Olivia"
        self.insider_tracked_products = ["SQUID_INK", "CROISSANTS"]

        self.insider_regimes = {
            "SQUID_INK": None,   # "bullish", "bearish", or None
            "CROISSANTS": None
        }
        self.insider_last_trades = {
            "SQUID_INK": [],
            "CROISSANTS": []
        }

        self.active_products = {
            "KELP": True,
            "RAINFOREST_RESIN": True,
            "SQUID_INK": True,
            "CROISSANTS": True,
            "JAMS": True,
            "DJEMBES": True,
            "PICNIC_BASKET1": True,
            "PICNIC_BASKET2": False,
        }

        self.position_limits = {
            "KELP": 50, "RAINFOREST_RESIN": 50, "SQUID_INK": 50,
            "CROISSANTS": 250, "JAMS": 350, "DJEMBES": 60,
            "PICNIC_BASKET1": 60, "PICNIC_BASKET2": 100,
        }
        self.timespan = 20
        self.make_width = {
            "KELP": 8.0, "RAINFOREST_RESIN": 3.0, "SQUID_INK": 5.0,
            "CROISSANTS": 1.0, "JAMS": 2.0, "DJEMBES": 2.0,
        }
        self.take_width = {
            "KELP": 1.0, "RAINFOREST_RESIN": 0.3, "SQUID_INK": 0.7,
            "CROISSANTS": 0.5, "JAMS": 0.5, "DJEMBES": 0.5,
        }

        # =============================================
        # SQUID INK VOLATILITY/MEAN-REVERSION PARAMS
        # =============================================
        self.squid_ink_volatility_threshold = 3.0      # std devs to trigger
        self.squid_ink_momentum_period = 10             # window for vol calc
        self.squid_ink_mean_window = 30                 # lookback for mean
        self.squid_ink_deviation_threshold = 0.05       # 5% deviation from mean
        self.squid_ink_max_position_time = 5            # max timestamps to hold
        self.squid_ink_position_start_time = 0
        self.squid_ink_last_position = 0

    def calculate_fair_value(self, order_depth: OrderDepth) -> float:
        try:
            if not order_depth.buy_orders or not order_depth.sell_orders:
                return None
            best_bid = max(order_depth.buy_orders.keys())
            best_ask = min(order_depth.sell_orders.keys())
            return (best_bid + best_ask) / 2
        except Exception as e:
            logger.print(f"Error calculating fair value: {e}")
            return None

    def clear_position_order(self, orders, order_depth, position, position_limit,
                              product, buy_order_volume, sell_order_volume,
                              fair_value, width):
        position_after_take = position + buy_order_volume - sell_order_volume
        fair_for_bid = int(math.floor(fair_value))
        fair_for_ask = int(math.ceil(fair_value))
        buy_quantity = position_limit - (position + buy_order_volume)
        sell_quantity = position_limit + (position - sell_order_volume)
        if position_after_take > 0:
            if fair_for_ask in order_depth.buy_orders.keys():
                clear_quantity = min(order_depth.buy_orders[fair_for_ask], position_after_take)
                sent_quantity = min(sell_quantity, clear_quantity)
                if sent_quantity > 0:
                    orders.append(Order(product, fair_for_ask, -abs(sent_quantity)))
                    sell_order_volume += abs(sent_quantity)
        if position_after_take < 0:
            if fair_for_bid in order_depth.sell_orders.keys():
                clear_quantity = min(abs(order_depth.sell_orders[fair_for_bid]), abs(position_after_take))
                sent_quantity = min(buy_quantity, clear_quantity)
                if sent_quantity > 0:
                    orders.append(Order(product, fair_for_bid, abs(sent_quantity)))
                    buy_order_volume += abs(sent_quantity)
        return buy_order_volume, sell_order_volume

    def product_orders(self, product: str, order_depth: OrderDepth, position: int) -> list:
        """Generic market-making for KELP and RAINFOREST_RESIN."""
        orders = []
        position_limit = self.position_limits[product]
        buy_order_volume = 0
        sell_order_volume = 0
        if len(order_depth.sell_orders) == 0 or len(order_depth.buy_orders) == 0:
            return orders
        best_ask = min(order_depth.sell_orders.keys())
        best_bid = max(order_depth.buy_orders.keys())
        filtered_asks = [p for p in order_depth.sell_orders.keys() if abs(order_depth.sell_orders[p]) >= 10]
        filtered_bids = [p for p in order_depth.buy_orders.keys() if abs(order_depth.buy_orders[p]) >= 10]
        mm_ask = min(filtered_asks) if filtered_asks else best_ask
        mm_bid = max(filtered_bids) if filtered_bids else best_bid
        mm_mid_price = (mm_ask + mm_bid) / 2

        if product == "KELP":
            self.kelp_prices.append(mm_mid_price)
            if len(self.kelp_prices) > self.timespan:
                self.kelp_prices.pop(0)
            volume = -1 * order_depth.sell_orders[best_ask] + order_depth.buy_orders[best_bid]
            vwap = (best_bid * (-1) * order_depth.sell_orders[best_ask] +
                    best_ask * order_depth.buy_orders[best_bid]) / volume
            self.kelp_vwap.append({"vol": volume, "vwap": vwap})
            if len(self.kelp_vwap) > self.timespan:
                self.kelp_vwap.pop(0)
            if len(self.kelp_vwap) > 0:
                total_vol = sum(x["vol"] for x in self.kelp_vwap)
                fair_value = ((sum(x["vwap"] * x["vol"] for x in self.kelp_vwap) / total_vol)
                              if total_vol > 0 else mm_mid_price)
            else:
                fair_value = mm_mid_price
        elif product == "RAINFOREST_RESIN":
            self.resin_prices.append(mm_mid_price)
            if len(self.resin_prices) > self.timespan:
                self.resin_prices.pop(0)
            volume = -1 * order_depth.sell_orders[best_ask] + order_depth.buy_orders[best_bid]
            vwap = (best_bid * (-1) * order_depth.sell_orders[best_ask] +
                    best_ask * order_depth.buy_orders[best_bid]) / volume
            self.resin_vwap.append({"vol": volume, "vwap": vwap})
            if len(self.resin_vwap) > self.timespan:
                self.resin_vwap.pop(0)
            if len(self.resin_vwap) > 0:
                total_vol = sum(x["vol"] for x in self.resin_vwap)
                fair_value = ((sum(x["vwap"] * x["vol"] for x in self.resin_vwap) / total_vol)
                              if total_vol > 0 else mm_mid_price)
            else:
                fair_value = mm_mid_price
        else:
            fair_value = mm_mid_price

        # TAKING
        if best_ask <= fair_value - self.take_width.get(product, 0):
            ask_amount = -1 * order_depth.sell_orders[best_ask]
            if ask_amount <= 20:
                quantity = min(ask_amount, position_limit - position)
                if quantity > 0:
                    orders.append(Order(product, best_ask, quantity))
                    buy_order_volume += quantity
        if best_bid >= fair_value + self.take_width.get(product, 0):
            bid_amount = order_depth.buy_orders[best_bid]
            if bid_amount <= 20:
                quantity = min(bid_amount, position_limit + position)
                if quantity > 0:
                    orders.append(Order(product, best_bid, -quantity))
                    sell_order_volume += quantity

        # CLEARING
        buy_order_volume, sell_order_volume = self.clear_position_order(
            orders, order_depth, position, position_limit, product,
            buy_order_volume, sell_order_volume, fair_value, 2,
        )

        # MAKING
        asks_above_fair = [p for p in order_depth.sell_orders.keys() if p > fair_value + 1]
        bids_below_fair = [p for p in order_depth.buy_orders.keys() if p < fair_value - 1]
        best_ask_above_fair = min(asks_above_fair) if asks_above_fair else int(fair_value) + 2
        best_bid_below_fair = max(bids_below_fair) if bids_below_fair else int(fair_value) - 2
        buy_quantity = position_limit - (position + buy_order_volume)
        if buy_quantity > 0:
            buy_price = int(best_bid_below_fair + 1)
            orders.append(Order(product, buy_price, buy_quantity))
        sell_quantity = position_limit + (position - sell_order_volume)
        if sell_quantity > 0:
            sell_price = int(best_ask_above_fair - 1)
            orders.append(Order(product, sell_price, -sell_quantity))
        return orders

    def close_position(self, product, order_depth, position):
        """Urgently close a position."""
        orders = []
        if position == 0:
            return orders
        if position > 0:
            if order_depth.buy_orders:
                best_bid = max(order_depth.buy_orders.keys())
                sell_quantity = min(position, order_depth.buy_orders[best_bid])
                if sell_quantity > 0:
                    orders.append(Order(product, best_bid, -sell_quantity))
        else:
            if order_depth.sell_orders:
                best_ask = min(order_depth.sell_orders.keys())
                buy_quantity = min(-position, -order_depth.sell_orders[best_ask])
                if buy_quantity > 0:
                    orders.append(Order(product, best_ask, buy_quantity))
        return orders

    def squid_ink_strategy(self, order_depth: OrderDepth, position: int, state_timestamp: int) -> list:
        """
        VOLATILE PRODUCT STRATEGY: Squid Ink Mean-Reversion with Volatility Detection

        Logic:
        1. Track rolling mid prices (window=30 for mean, window=10 for volatility)
        2. Calculate short-term volatility (stdev of last 10 prices)
        3. Calculate deviation from mean as percentage
        4. ENTRY: When volatility > 3.0 AND deviation > 5%, enter opposite direction
        5. EXIT: When price reverts to mean OR regime changes OR time limit hit
        6. REGIME FILTER: Don't go long if Olivia is bearish, don't go short if bullish
        """
        orders = []
        position_limit = self.position_limits["SQUID_INK"]
        if not order_depth.sell_orders or not order_depth.buy_orders:
            return orders

        best_ask = min(order_depth.sell_orders.keys())
        best_bid = max(order_depth.buy_orders.keys())
        mid_price = (best_ask + best_bid) / 2

        self.squid_ink_prices.append(mid_price)
        if len(self.squid_ink_prices) > max(self.timespan, self.squid_ink_mean_window):
            self.squid_ink_prices.pop(0)

        if len(self.squid_ink_prices) < 10:
            return orders

        # Calculate mean over longer window
        recent_window = min(len(self.squid_ink_prices), self.squid_ink_mean_window)
        mean_price = sum(self.squid_ink_prices[-recent_window:]) / recent_window

        # Calculate short-term volatility
        if len(self.squid_ink_prices) >= 2:
            volatility = statistics.stdev(
                self.squid_ink_prices[-min(10, len(self.squid_ink_prices)):]
            )
        else:
            volatility = 0

        # Percentage deviation from mean
        deviation_pct = abs(mid_price - mean_price) / mean_price if mean_price > 0 else 0

        # Get Olivia's regime signal
        current_regime = self.insider_regimes["SQUID_INK"]

        # Position time management - close if held too long
        if position != 0 and self.squid_ink_position_start_time > 0:
            time_in_position = state_timestamp - self.squid_ink_position_start_time
            if time_in_position >= self.squid_ink_max_position_time:
                return self.close_position("SQUID_INK", order_depth, position)

        if position == 0:
            # ENTRY LOGIC: volatility spike + deviation from mean
            if volatility > self.squid_ink_volatility_threshold and deviation_pct > self.squid_ink_deviation_threshold:
                # SHORT: price above mean and not in bullish regime
                if mid_price > mean_price and (current_regime != "bullish"):
                    quantity = min(order_depth.buy_orders[best_bid], position_limit)
                    if quantity > 0:
                        orders.append(Order("SQUID_INK", best_bid, -quantity))
                        self.squid_ink_position_start_time = state_timestamp
                        self.squid_ink_last_position = -quantity

                # LONG: price below mean and not in bearish regime
                elif mid_price < mean_price and (current_regime != "bearish"):
                    quantity = min(-order_depth.sell_orders[best_ask], position_limit)
                    if quantity > 0:
                        orders.append(Order("SQUID_INK", best_ask, quantity))
                        self.squid_ink_position_start_time = state_timestamp
                        self.squid_ink_last_position = quantity
        else:
            # EXIT LOGIC: price reverted to mean or regime flipped
            if position > 0:
                if mid_price >= mean_price or current_regime == "bearish":
                    quantity = min(position, order_depth.buy_orders[best_bid])
                    if quantity > 0:
                        orders.append(Order("SQUID_INK", best_bid, -quantity))
                        if quantity == position:
                            self.squid_ink_position_start_time = 0
                            self.squid_ink_last_position = 0
            elif position < 0:
                if mid_price <= mean_price or current_regime == "bullish":
                    quantity = min(-position, -order_depth.sell_orders[best_ask])
                    if quantity > 0:
                        orders.append(Order("SQUID_INK", best_ask, quantity))
                        if quantity == -position:
                            self.squid_ink_position_start_time = 0
                            self.squid_ink_last_position = 0

        return orders

    def copy_olivia_trades(self, state: TradingState, product: str) -> list:
        """
        Copy Olivia's trades for SQUID_INK or CROISSANTS.
        If Olivia buys -> we go max long.
        If Olivia sells -> we go max short.
        """
        orders = []
        position_limit = self.position_limits[product]
        current_position = state.position.get(product, 0)

        if product not in state.market_trades:
            return orders

        olivia_buy_qty = 0
        olivia_sell_qty = 0

        for trade in state.market_trades[product]:
            if trade.buyer == self.insider_id:
                olivia_buy_qty += trade.quantity
            elif trade.seller == self.insider_id:
                olivia_sell_qty += trade.quantity

        if olivia_buy_qty > 0:
            buy_quantity = min(position_limit - current_position, position_limit)
            if buy_quantity > 0 and product in state.order_depths and state.order_depths[product].sell_orders:
                best_ask = min(state.order_depths[product].sell_orders.keys())
                orders.append(Order(product, best_ask, buy_quantity))

        if olivia_sell_qty > 0:
            sell_quantity = min(position_limit + current_position, position_limit)
            if sell_quantity > 0 and product in state.order_depths and state.order_depths[product].buy_orders:
                best_bid = max(state.order_depths[product].buy_orders.keys())
                orders.append(Order(product, best_bid, -sell_quantity))

        return orders

    def process_insider_trades(self, state: TradingState) -> None:
        """Track Olivia's trades and update regime signals."""
        for product in self.insider_tracked_products:
            if product in state.market_trades:
                for trade in state.market_trades[product]:
                    if trade.buyer == self.insider_id or trade.seller == self.insider_id:
                        is_buying = trade.buyer == self.insider_id
                        if is_buying:
                            self.insider_regimes[product] = "bullish"
                        else:
                            self.insider_regimes[product] = "bearish"

                        self.insider_last_trades[product].append({
                            "timestamp": trade.timestamp,
                            "price": trade.price,
                            "quantity": trade.quantity,
                            "is_buying": is_buying
                        })
                        if len(self.insider_last_trades[product]) > 10:
                            self.insider_last_trades[product].pop(0)

    def run(self, state: TradingState):
        try:
            result = {}
            conversions = 0
            trader_data = {}

            self.process_insider_trades(state)

            if state.traderData and state.traderData != "SAMPLE":
                try:
                    trader_data = jsonpickle.decode(state.traderData)
                    for prod in ["kelp", "resin", "squid_ink", "croissants", "jams", "djembes"]:
                        if f"{prod}_prices" in trader_data:
                            setattr(self, f"{prod}_prices", trader_data[f"{prod}_prices"])
                        if f"{prod}_vwap" in trader_data:
                            setattr(self, f"{prod}_vwap", trader_data[f"{prod}_vwap"])
                    if "insider_regimes" in trader_data:
                        self.insider_regimes = trader_data["insider_regimes"]
                    if "insider_last_trades" in trader_data:
                        self.insider_last_trades = trader_data["insider_last_trades"]
                except Exception as e:
                    logger.print(f"Could not parse trader data: {e}")

            handled = set()

            # SQUID_INK and CROISSANTS: copy Olivia's trades
            for product in ["CROISSANTS", "SQUID_INK"]:
                if product in state.order_depths and self.active_products.get(product, False):
                    product_orders = self.copy_olivia_trades(state, product)
                    if product_orders:
                        result[product] = product_orders
                    handled.add(product)

            # Generic market making for other products
            for product in state.order_depths:
                if product in handled:
                    continue
                if not self.active_products.get(product, False):
                    continue
                position = state.position.get(product, 0)
                order_depth = state.order_depths[product]

                if product in ["KELP", "RAINFOREST_RESIN"]:
                    result[product] = self.product_orders(product, order_depth, position)

            # Save state
            trader_data = {
                "kelp_prices": self.kelp_prices,
                "resin_prices": self.resin_prices,
                "squid_ink_prices": self.squid_ink_prices,
                "kelp_vwap": self.kelp_vwap,
                "resin_vwap": self.resin_vwap,
                "squid_ink_vwap": self.squid_ink_vwap,
                "insider_regimes": self.insider_regimes,
                "insider_last_trades": self.insider_last_trades,
            }
            trader_data_str = jsonpickle.encode(trader_data)

            logger.flush(state, result, conversions, trader_data_str)
            return result, conversions, trader_data_str

        except Exception as e:
            logger.print(f"Error in run: {e}")
            return {}, 0, ""
