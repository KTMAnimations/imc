from datamodel import OrderDepth, TradingState, Order
import json

PRODUCT = "TOMATOES"
LIMIT = 80

TAKE_WIDTH = 1
CLEAR_WIDTH = 0
REVERSION_BETA = 0

SOFT_LIMIT = 35
HARD_LIMIT = 60


class Trader:

    def get_fair_value(self, od: OrderDepth, trader_data: dict):
        if not od.sell_orders or not od.buy_orders:
            return None, trader_data

        worst_bid = min(od.buy_orders.keys())
        worst_ask = max(od.sell_orders.keys())
        wall_mid = (worst_bid + worst_ask) / 2

        last_price = trader_data.get("last_price")
        if last_price is not None:
            returns = (wall_mid - last_price) / last_price
            pred_returns = returns * REVERSION_BETA
            fair = wall_mid + wall_mid * pred_returns
        else:
            fair = wall_mid

        trader_data["last_price"] = wall_mid
        return fair, trader_data

    def take_orders(self, od: OrderDepth, fair: float, pos: int, bv: int, sv: int):
        orders = []

        for ask in sorted(od.sell_orders.keys()):
            if ask > fair - TAKE_WIDTH:
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
            if bid < fair + TAKE_WIDTH:
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

    def clear_orders(self, od: OrderDepth, fair: float, pos: int, bv: int, sv: int):
        orders = []
        net = pos + bv - sv

        if net > 0:
            price = round(fair + CLEAR_WIDTH)
            avail = sum(v for p, v in od.buy_orders.items() if p >= price)
            qty = min(avail, net, LIMIT + pos - sv)
            if qty > 0:
                orders.append(Order(PRODUCT, price, -qty))
                sv += qty

        elif net < 0:
            price = round(fair - CLEAR_WIDTH)
            avail = sum(-v for p, v in od.sell_orders.items() if p <= price)
            qty = min(avail, -net, LIMIT - pos - bv)
            if qty > 0:
                orders.append(Order(PRODUCT, price, qty))
                bv += qty

        return orders, bv, sv

    def make_orders(self, od: OrderDepth, fair: float, pos: int, bv: int, sv: int):
        orders = []

        asks_above = [p for p in od.sell_orders if p > fair + 1]
        bids_below = [p for p in od.buy_orders if p < fair - 1]

        best_ask = min(asks_above) if asks_above else None
        best_bid = max(bids_below) if bids_below else None

        ask = round(fair + 1)
        bid = round(fair - 1)

        if best_ask is not None:
            ask = best_ask - 1
        if best_bid is not None:
            bid = best_bid + 1

        ask = max(ask, round(fair + 1))
        bid = min(bid, round(fair - 1))

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

            trader_data = {}
            if state.traderData:
                try:
                    trader_data = json.loads(state.traderData)
                except:
                    trader_data = {}

            fair, trader_data = self.get_fair_value(od, trader_data)

            if fair is not None:
                bv = sv = 0
                take, bv, sv = self.take_orders(od, fair, pos, bv, sv)
                clear, bv, sv = self.clear_orders(od, fair, pos, bv, sv)
                make = self.make_orders(od, fair, pos, bv, sv)
                result[PRODUCT] = take + clear + make

            return result, 0, json.dumps(trader_data)

        return result, 0, ""