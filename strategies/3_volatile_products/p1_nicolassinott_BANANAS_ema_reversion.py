# ============================================================================
# SOURCE: https://github.com/nicolassinott/IMC_Prosperity
# TEAM: nicolassinott - Prosperity 1 (2023)
# FILE: trader.py
#
# KEY VOLATILE PRODUCT STRATEGY (BANANAS):
#   - EMA (Exponential Moving Average) mean-reversion market making
#   - ema_param = 0.5 (fast-responding EMA)
#   - Position-aware spread adjustment:
#     * Neutral: bid at EMA-1, ask at EMA+1
#     * Long: widen buy edge to EMA-2, tighten sell to EMA
#     * Short: tighten buy to EMA, widen sell edge to EMA+2
#   - This naturally liquidates positions while continuing to trade
#
# This is one of the simplest but most elegant volatile product strategies.
# The position-dependent spread asymmetry creates natural mean-reversion
# of both price AND inventory.
# ============================================================================

from typing import Dict, List
from datamodel import OrderDepth, TradingState, Order
import math

SUBMISSION = "SUBMISSION"
PEARLS = "PEARLS"
BANANAS = "BANANAS"

PRODUCTS = [PEARLS, BANANAS]

DEFAULT_PRICES = {
    PEARLS: 10_000,
    BANANAS: 5_000,
}


class Trader:
    def __init__(self) -> None:
        print("Initializing Trader...")

        self.position_limit = {
            PEARLS: 20,
            BANANAS: 20,
        }

        self.round = 0
        self.cash = 0

        # Historical price tracking
        self.past_prices = {product: [] for product in PRODUCTS}

        # EMA price tracking
        self.ema_prices = {product: None for product in PRODUCTS}
        self.ema_param = 0.5  # Fast EMA response

    def get_position(self, product, state):
        return state.position.get(product, 0)

    def get_mid_price(self, product, state):
        default_price = self.ema_prices[product]
        if default_price is None:
            default_price = DEFAULT_PRICES[product]

        if product not in state.order_depths:
            return default_price

        market_bids = state.order_depths[product].buy_orders
        if len(market_bids) == 0:
            return default_price

        market_asks = state.order_depths[product].sell_orders
        if len(market_asks) == 0:
            return default_price

        best_bid = max(market_bids)
        best_ask = min(market_asks)
        return (best_bid + best_ask) / 2

    def get_value_on_product(self, product, state):
        return self.get_position(product, state) * self.get_mid_price(product, state)

    def update_pnl(self, state):
        for product in state.own_trades:
            for trade in state.own_trades[product]:
                if trade.timestamp != state.timestamp - 100:
                    continue
                if trade.buyer == SUBMISSION:
                    self.cash -= trade.quantity * trade.price
                if trade.seller == SUBMISSION:
                    self.cash += trade.quantity * trade.price

        value = 0
        for product in state.position:
            value += self.get_value_on_product(product, state)
        return self.cash + value

    def update_ema_prices(self, state):
        """Update exponential moving average prices."""
        for product in PRODUCTS:
            mid_price = self.get_mid_price(product, state)
            if mid_price is None:
                continue
            if self.ema_prices[product] is None:
                self.ema_prices[product] = mid_price
            else:
                self.ema_prices[product] = (self.ema_param * mid_price +
                                            (1 - self.ema_param) * self.ema_prices[product])

    def pearls_strategy(self, state):
        """PEARLS: stable product, simple market-making at 10000."""
        position = self.get_position(PEARLS, state)
        bid_volume = self.position_limit[PEARLS] - position
        ask_volume = -self.position_limit[PEARLS] - position
        orders = []
        orders.append(Order(PEARLS, DEFAULT_PRICES[PEARLS] - 1, bid_volume))
        orders.append(Order(PEARLS, DEFAULT_PRICES[PEARLS] + 1, ask_volume))
        return orders

    def bananas_strategy(self, state):
        """
        BANANAS: Volatile Product EMA Mean-Reversion Strategy.

        The key insight is position-dependent spread asymmetry:
        - When FLAT: symmetric spread around EMA (EMA-1 / EMA+1)
        - When LONG: widen buy spread (EMA-2) to discourage buying more,
                     tighten sell spread (EMA+0) to encourage liquidation
        - When SHORT: tighten buy spread (EMA+0) to encourage covering,
                      widen sell spread (EMA+2) to discourage selling more

        This creates natural inventory mean-reversion while maintaining
        market presence on both sides.
        """
        position = self.get_position(BANANAS, state)
        bid_volume = self.position_limit[BANANAS] - position
        ask_volume = -self.position_limit[BANANAS] - position

        orders = []

        if position == 0:
            # Neutral: symmetric spread around EMA
            orders.append(Order(BANANAS, math.floor(self.ema_prices[BANANAS] - 1), bid_volume))
            orders.append(Order(BANANAS, math.ceil(self.ema_prices[BANANAS] + 1), ask_volume))

        if position > 0:
            # Long: widen buy edge, tighten sell to liquidate
            orders.append(Order(BANANAS, math.floor(self.ema_prices[BANANAS] - 2), bid_volume))
            orders.append(Order(BANANAS, math.ceil(self.ema_prices[BANANAS]), ask_volume))

        if position < 0:
            # Short: tighten buy to cover, widen sell edge
            orders.append(Order(BANANAS, math.floor(self.ema_prices[BANANAS]), bid_volume))
            orders.append(Order(BANANAS, math.ceil(self.ema_prices[BANANAS] + 2), ask_volume))

        return orders

    def run(self, state: TradingState) -> Dict[str, List[Order]]:
        self.round += 1
        pnl = self.update_pnl(state)
        self.update_ema_prices(state)

        print(f"Log round {self.round}")
        for product in PRODUCTS:
            print(f"\tProduct {product}, Position {self.get_position(product, state)}, "
                  f"Midprice {self.get_mid_price(product, state)}, EMA {self.ema_prices[product]}")
        print(f"\tPnL {pnl}")

        result = {}

        try:
            result[PEARLS] = self.pearls_strategy(state)
        except Exception as e:
            print(f"Error in pearls strategy: {e}")

        try:
            result[BANANAS] = self.bananas_strategy(state)
        except Exception as e:
            print(f"Error in bananas strategy: {e}")

        return result
