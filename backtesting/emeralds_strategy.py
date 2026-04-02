from datamodel import OrderDepth, TradingState, Order

PRODUCT = "EMERALDS"
LIMIT = 80
FAIR = 10000

TAKE_WIDTH = 1
CLEAR_WIDTH = 0
MAKE_EDGE = 7

SOFT_LIMIT = 35
HARD_LIMIT = 60


class Trader:

    def take_orders(self, od: OrderDepth, pos: int, bv: int, sv: int):
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
        orders = []

        bid = FAIR - MAKE_EDGE
        ask = FAIR + MAKE_EDGE

        if pos > SOFT_LIMIT:
            ask -= 1
        if pos > HARD_LIMIT:
            ask -= 2
        if pos < -SOFT_LIMIT:
            bid += 1
        if pos < -HARD_LIMIT:
            bid += 2

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
