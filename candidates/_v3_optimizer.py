"""
V3 optimizer: parametric version of tradestrategy.py, plus a harness that
runs it against the fixed sim_gui simulator.

- Parametric trader class reads params from a dict
- Scoring: runs against each (day=-1) log individually, then aggregated
- Rejects overfit candidates (wins on aggregate, loses on min/mean single-log)
"""

import json
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from datamodel import Order  # noqa: E402
from sim_gui.simulator import build_timeline, simulate  # noqa: E402


BASELINE_PARAMS = {
    # emeralds
    "E_TAKE_WIDTH": 1,
    "E_CLEAR_WIDTH": 0,
    "E_MAKE_EDGE": 7,
    "E_SOFT": 35,
    "E_HARD": 60,
    # tomatoes
    "T_EMA_ALPHA": 0.5,
    "T_INV_SKEW": 0.05,
    "T_SOFT": 40,
    "T_HARD": 60,
    "T_PASSIVE_CAP": 20,
    "T_CLEAR_AT_SOFT": 0,   # offset from round(fair) at SOFT inventory
    "T_CLEAR_AT_HARD": 1,   # offset from round(fair) at HARD inventory (more aggressive)
    "T_FAIR_R_MODE": "ceil_floor",  # "ceil_floor" (baseline) or "round"
}

EMERALDS_LIMIT = 80
EMERALDS_FAIR = 10000
TOMATOES_LIMIT = 80


def make_trader(params):
    p = dict(BASELINE_PARAMS)
    p.update(params)

    class Trader:
        def __init__(self):
            self.p = p

        def tomatoes_clear_price(self, fair, net):
            p = self.p
            if net >= p["T_HARD"]:
                return math.floor(fair) - p["T_CLEAR_AT_HARD"]
            if net >= p["T_SOFT"]:
                return math.floor(fair) - p["T_CLEAR_AT_SOFT"]
            if net <= -p["T_HARD"]:
                return math.ceil(fair) + p["T_CLEAR_AT_HARD"]
            if net <= -p["T_SOFT"]:
                return math.ceil(fair) + p["T_CLEAR_AT_SOFT"]
            return round(fair)

        def tomatoes_quote_prices(self, od, fair, eff_pos):
            p = self.p
            best_bid = max(od.buy_orders.keys()) if od.buy_orders else None
            best_ask = min(od.sell_orders.keys()) if od.sell_orders else None
            if best_bid is None or best_ask is None:
                return None, None

            if p["T_FAIR_R_MODE"] == "round":
                fair_r = round(fair)
                max_bid = fair_r - 1
                min_ask = fair_r + 1
            else:
                max_bid = math.ceil(fair) - 1
                min_ask = math.floor(fair) + 1

            if eff_pos <= -p["T_SOFT"]:
                max_bid += 1
            if eff_pos <= -p["T_HARD"]:
                max_bid += 1
            if eff_pos >= p["T_SOFT"]:
                min_ask -= 1
            if eff_pos >= p["T_HARD"]:
                min_ask -= 1

            bid_ceiling = min(max_bid, best_ask - 1)
            ask_floor = max(min_ask, best_bid + 1)

            if bid_ceiling <= best_bid or ask_floor >= best_ask:
                return None, None

            normal_bid = min(best_bid + 1, bid_ceiling)
            normal_ask = max(best_ask - 1, ask_floor)

            if eff_pos <= -p["T_HARD"]:
                bid = bid_ceiling
            elif eff_pos <= -p["T_SOFT"]:
                bid = min(bid_ceiling, normal_bid + 1)
            else:
                bid = normal_bid

            if eff_pos >= p["T_HARD"]:
                ask = ask_floor
            elif eff_pos >= p["T_SOFT"]:
                ask = max(ask_floor, normal_ask - 1)
            else:
                ask = normal_ask

            return bid, ask

        def emeralds_take(self, od, pos, bv, sv):
            p = self.p
            orders = []
            for ask in sorted(od.sell_orders.keys()):
                if ask > EMERALDS_FAIR - p["E_TAKE_WIDTH"]:
                    break
                vol = -od.sell_orders[ask]
                qty = min(vol, EMERALDS_LIMIT - pos - bv)
                if qty > 0:
                    orders.append(Order("EMERALDS", ask, qty))
                    bv += qty
                    od.sell_orders[ask] += qty
                    if od.sell_orders[ask] == 0:
                        del od.sell_orders[ask]
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                if bid < EMERALDS_FAIR + p["E_TAKE_WIDTH"]:
                    break
                vol = od.buy_orders[bid]
                qty = min(vol, EMERALDS_LIMIT + pos - sv)
                if qty > 0:
                    orders.append(Order("EMERALDS", bid, -qty))
                    sv += qty
                    od.buy_orders[bid] -= qty
                    if od.buy_orders[bid] == 0:
                        del od.buy_orders[bid]
            return orders, bv, sv

        def emeralds_clear(self, od, pos, bv, sv):
            p = self.p
            orders = []
            net = pos + bv - sv
            if net > 0:
                price = EMERALDS_FAIR + p["E_CLEAR_WIDTH"]
                avail = sum(v for pr, v in od.buy_orders.items() if pr >= price)
                qty = min(avail, net, EMERALDS_LIMIT + pos - sv)
                if qty > 0:
                    orders.append(Order("EMERALDS", price, -qty))
                    sv += qty
            elif net < 0:
                price = EMERALDS_FAIR - p["E_CLEAR_WIDTH"]
                avail = sum(-v for pr, v in od.sell_orders.items() if pr <= price)
                qty = min(avail, -net, EMERALDS_LIMIT - pos - bv)
                if qty > 0:
                    orders.append(Order("EMERALDS", price, qty))
                    bv += qty
            return orders, bv, sv

        def emeralds_make(self, pos, bv, sv):
            p = self.p
            orders = []
            bid = EMERALDS_FAIR - p["E_MAKE_EDGE"]
            ask = EMERALDS_FAIR + p["E_MAKE_EDGE"]
            if pos > p["E_SOFT"]:
                ask -= 1
            if pos > p["E_HARD"]:
                ask -= 2
            if pos < -p["E_SOFT"]:
                bid += 1
            if pos < -p["E_HARD"]:
                bid += 2
            buy_qty = EMERALDS_LIMIT - pos - bv
            if buy_qty > 0:
                orders.append(Order("EMERALDS", bid, buy_qty))
            sell_qty = EMERALDS_LIMIT + pos - sv
            if sell_qty > 0:
                orders.append(Order("EMERALDS", ask, -sell_qty))
            return orders

        def trade_emeralds(self, state):
            pos = state.position.get("EMERALDS", 0)
            od = state.order_depths["EMERALDS"]
            bv = sv = 0
            take, bv, sv = self.emeralds_take(od, pos, bv, sv)
            clear, bv, sv = self.emeralds_clear(od, pos, bv, sv)
            make = self.emeralds_make(pos, bv, sv)
            return take + clear + make

        def tomatoes_fair(self, od, pos, trader_data):
            p = self.p
            if not od.sell_orders or not od.buy_orders:
                return None, trader_data
            bid_wall = max(od.buy_orders.keys(), key=lambda pr: od.buy_orders[pr])
            ask_wall = min(od.sell_orders.keys(), key=lambda pr: -od.sell_orders[pr])
            wall_mid = (bid_wall + ask_wall) / 2
            alpha = p["T_EMA_ALPHA"]
            prev = trader_data.get("tomatoes_ema")
            if prev is not None:
                ema = prev * (1 - alpha) + wall_mid * alpha
            else:
                ema = wall_mid
            trader_data["tomatoes_ema"] = ema
            fair = ema - p["T_INV_SKEW"] * pos
            return fair, trader_data

        def tomatoes_take(self, od, fair, pos, bv, sv):
            orders = []
            for ask in sorted(od.sell_orders.keys()):
                if ask >= fair:
                    break
                vol = -od.sell_orders[ask]
                qty = min(vol, TOMATOES_LIMIT - pos - bv)
                if qty > 0:
                    orders.append(Order("TOMATOES", ask, qty))
                    bv += qty
                    od.sell_orders[ask] += qty
                    if od.sell_orders[ask] == 0:
                        del od.sell_orders[ask]
            for bid in sorted(od.buy_orders.keys(), reverse=True):
                if bid <= fair:
                    break
                vol = od.buy_orders[bid]
                qty = min(vol, TOMATOES_LIMIT + pos - sv)
                if qty > 0:
                    orders.append(Order("TOMATOES", bid, -qty))
                    sv += qty
                    od.buy_orders[bid] -= qty
                    if od.buy_orders[bid] == 0:
                        del od.buy_orders[bid]
            return orders, bv, sv

        def tomatoes_clear(self, od, fair, pos, bv, sv):
            orders = []
            net = pos + bv - sv
            if net > 0:
                price = self.tomatoes_clear_price(fair, net)
                avail = sum(v for pr, v in od.buy_orders.items() if pr >= price)
                qty = min(avail, net, TOMATOES_LIMIT + pos - sv)
                if qty > 0:
                    orders.append(Order("TOMATOES", price, -qty))
                    sv += qty
            elif net < 0:
                price = self.tomatoes_clear_price(fair, net)
                avail = sum(-v for pr, v in od.sell_orders.items() if pr <= price)
                qty = min(avail, -net, TOMATOES_LIMIT - pos - bv)
                if qty > 0:
                    orders.append(Order("TOMATOES", price, qty))
                    bv += qty
            return orders, bv, sv

        def tomatoes_make(self, od, fair, pos, bv, sv):
            p = self.p
            orders = []
            eff_pos = pos + bv - sv
            bid, ask = self.tomatoes_quote_prices(od, fair, eff_pos)
            if bid is None or ask is None:
                return orders
            half = TOMATOES_LIMIT // 2
            base = p["T_PASSIVE_CAP"]
            if eff_pos >= half:
                bid_cap = 0
            elif eff_pos > 0:
                bid_cap = max(1, int(base * (1 - eff_pos / half)))
            else:
                bid_cap = base
            if eff_pos <= -half:
                ask_cap = 0
            elif eff_pos < 0:
                ask_cap = max(1, int(base * (1 + eff_pos / half)))
            else:
                ask_cap = base
            buy_qty = min(bid_cap, TOMATOES_LIMIT - pos - bv)
            sell_qty = min(ask_cap, TOMATOES_LIMIT + pos - sv)
            if buy_qty > 0:
                orders.append(Order("TOMATOES", bid, buy_qty))
            if sell_qty > 0:
                orders.append(Order("TOMATOES", ask, -sell_qty))
            return orders

        def trade_tomatoes(self, state, trader_data):
            pos = state.position.get("TOMATOES", 0)
            od = state.order_depths["TOMATOES"]
            fair, trader_data = self.tomatoes_fair(od, pos, trader_data)
            if fair is None:
                return [], trader_data
            bv = sv = 0
            take, bv, sv = self.tomatoes_take(od, fair, pos, bv, sv)
            clear, bv, sv = self.tomatoes_clear(od, fair, pos, bv, sv)
            make = self.tomatoes_make(od, fair, pos, bv, sv)
            return take + clear + make, trader_data

        def run(self, state):
            result = {}
            trader_data = {}
            if state.traderData:
                try:
                    trader_data = json.loads(state.traderData)
                except Exception:
                    trader_data = {}
            if "EMERALDS" in state.order_depths:
                result["EMERALDS"] = self.trade_emeralds(state)
            if "TOMATOES" in state.order_depths:
                tom, trader_data = self.trade_tomatoes(state, trader_data)
                result["TOMATOES"] = tom
            return result, 0, json.dumps(trader_data)

    return Trader()


# --- timelines cache ---
LOG_DIR_NAMES = ['41408','41446','41499','41588','41641','42308','42752','42769',
                 '42797','42842','43070','43149','43770','43794','43848','44890','58160']
LOG_PATHS = [os.path.join(REPO, d, f'{d}.log') for d in LOG_DIR_NAMES]


_timelines = {}
def get_tl(key):
    if key in _timelines:
        return _timelines[key]
    if key == "agg":
        tl = build_timeline(LOG_PATHS)
    else:
        tl = build_timeline([LOG_PATHS[key]])
    _timelines[key] = tl
    return tl


def score(params, verbose=False):
    """Return (agg_pnl, [per_log_pnl], mean, min_, max_)."""
    per_log = []
    for i in range(len(LOG_PATHS)):
        tl = get_tl(i)
        trader = make_trader(params)
        res = simulate(trader, tl)
        per_log.append(res.total_pnl)
    tl = get_tl("agg")
    trader = make_trader(params)
    res = simulate(trader, tl)
    agg = res.total_pnl
    mean = sum(per_log) / len(per_log)
    mn = min(per_log)
    mx = max(per_log)
    if verbose:
        print(f'  agg={agg:.1f}  mean={mean:.1f}  min={mn:.1f}  max={mx:.1f}')
    return agg, per_log, mean, mn, mx


if __name__ == "__main__":
    print("Baseline:")
    score(BASELINE_PARAMS, verbose=True)
