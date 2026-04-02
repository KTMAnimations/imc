from datamodel import OrderDepth, TradingState, Order

# =============================================================================
# EMERALDS Hyper-Optimized Market Maker
#
# Market structure (from data analysis of 20,000 ticks):
#   Fair value: exactly 10,000 (96.7% of ticks, never below 9996 or above 10004)
#   Bot L1: 9992 bid / 10008 ask (spread=16), volume 5-15 per side
#   Bot L2: 9990 bid / 10010 ask, volume 20-30 per side
#   Trade flow: ~200/day, size 3-8, perfectly balanced 50/50
#   Anomalous ticks (~3.3%): a bot briefly posts at 10000 (size 5-10)
#   Position limit: 80
#
# Architecture: Take -> Clear -> Make (adapted from Linear Utility, 2nd place P2)
#
#   1. TAKE:  Sweep all asks <= 9999, sell to all bids >= 10001
#   2. CLEAR: Flatten inventory at 10,000 (fires during anomalous ticks)
#   3. MAKE:  Quote 9993/10007 — just 1 tick inside bot L1
#             This is the widest spread that still gives us best bid/ask priority.
#             Maximizes profit per fill (7 per side) while capturing 100% of flow.
#
# Inventory management: graduated skewing at 35/60 thresholds
#
# Expected profit per round trip: 14 per unit (7 buy side + 7 sell side)
# Estimated daily PnL: ~7,700 (550 units/side x 7 per unit x 2 sides)
# =============================================================================

PRODUCT = "EMERALDS"
LIMIT = 80
FAIR = 10000

TAKE_WIDTH = 1    # take asks <= 9999, sell to bids >= 10001
CLEAR_WIDTH = 0   # flatten inventory at exactly 10000
MAKE_EDGE = 7     # quote 9993 / 10007 — max edge while staying inside bot L1 (9992/10008)

SOFT_LIMIT = 35   # ~44% of limit: tighten reducing side by 1
HARD_LIMIT = 60   # 75% of limit: tighten reducing side by 3 total


class Trader:

    def take_orders(self, od: OrderDepth, pos: int, bv: int, sv: int):
        """Phase 1: Sweep all mispriced levels.
        In normal regime (96.7%) nothing to take. Fires when rare orders appear
        below 9999 or above 10001."""
        orders = []

        for ask in sorted(od.sell_orders.keys()):
            if ask > FAIR - TAKE_WIDTH:
                break
            vol = -od.sell_orders[ask]
            qty = min(vol, LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order(PRODUCT, ask, qty))
                bv += qty
                od.sell_orders[ask] += qty
                if od.sell_orders[ask] == 0:
                    del od.sell_orders[ask]

        for bid in sorted(od.buy_orders.keys(), reverse=True):
            if bid < FAIR + TAKE_WIDTH:
                break
            vol = od.buy_orders[bid]
            qty = min(vol, LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order(PRODUCT, bid, -qty))
                sv += qty
                od.buy_orders[bid] -= qty
                if od.buy_orders[bid] == 0:
                    del od.buy_orders[bid]

        return orders, bv, sv

    def clear_orders(self, od: OrderDepth, pos: int, bv: int, sv: int):
        """Phase 2: Flatten inventory at fair value.
        Fires during anomalous ticks (~3.3%) when a bot posts at 10000."""
        orders = []
        net = pos + bv - sv

        if net > 0:
            price = FAIR + CLEAR_WIDTH
            avail = sum(v for p, v in od.buy_orders.items() if p >= price)
            qty = min(avail, net, LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order(PRODUCT, price, -qty))
                sv += qty

        elif net < 0:
            price = FAIR - CLEAR_WIDTH
            avail = sum(-v for p, v in od.sell_orders.items() if p <= price)
            qty = min(avail, -net, LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order(PRODUCT, price, qty))
                bv += qty

        return orders, bv, sv

    def make_orders(self, pos: int, bv: int, sv: int):
        """Phase 3: Passive quotes at 9993/10007.
        Just 1 tick inside bot L1 (9992/10008) = best bid/ask with max edge.
        Graduated skewing when inventory builds up."""
        orders = []

        bid = FAIR - MAKE_EDGE   # 9993
        ask = FAIR + MAKE_EDGE   # 10007

        # Graduated skew: tighten the side that reduces position
        if pos > SOFT_LIMIT:
            ask -= 1               # 10006
        if pos > HARD_LIMIT:
            ask -= 2               # 10004
        if pos < -SOFT_LIMIT:
            bid += 1               # 9994
        if pos < -HARD_LIMIT:
            bid += 2               # 9996

        buy_qty = LIMIT - pos - bv
        if buy_qty > 0:
            orders.append(Order(PRODUCT, bid, buy_qty))

        sell_qty = LIMIT + pos - sv
        if sell_qty > 0:
            orders.append(Order(PRODUCT, ask, -sell_qty))

        return orders

    def run(self, state: TradingState):
        result = {}

        if PRODUCT in state.order_depths:
            pos = state.position.get(PRODUCT, 0)
            od = state.order_depths[PRODUCT]
            bv = sv = 0

            take, bv, sv = self.take_orders(od, pos, bv, sv)
            clear, bv, sv = self.clear_orders(od, pos, bv, sv)
            make = self.make_orders(pos, bv, sv)

            result[PRODUCT] = take + clear + make

        return result, 0, ""
