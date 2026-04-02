# IMC Prosperity 4 Wiki - Comprehensive Reference

https://imc-prosperity.notion.site/prosperity-4-wiki

## What is Prosperity 4?

Prosperity 4 is IMC's global online trading challenge, designed for university students who want to get familiar with algorithmic trading and financial markets. It is a unique simulation game developed by a team of IMC traders, quantitative researchers, and software engineers to provide an accessible, life-like experience of what it takes to be a trader.

This year, Prosperity 4 challenges you to explore new frontiers as you and your crew set course for outer space, earning as many **XIRECs** (Prosperity currency) as possible.

The challenge runs for **16 days** in total, divided into two active phases of six days each, with a four-day intermission in between.

Prove your worth on your first mission and you'll be granted access to the second, and final phase of the competition. At the end of the final round, the team that has generated the most profit of all teams will be victorious and be crowned **IMC Trading Talent of 2026**.

**Key facts:**
- Teams of 1-5 players
- Python-based algorithmic trading
- 5 rounds, each with 1 algorithmic challenge + 1 manual challenge

---

## Storyline / Lore

You are on your way to **Intara**, a distant planet that has reached out for help.

Before you arrive, you can use the trading simulator from within your spacecraft. Trading options might be limited, but it gives you the opportunity to experiment with some initial tradable goods, run your first lines of Python code, and become familiar with the GUI.

Intarian people need your expertise to establish a trading system capable of turning their planet's potential into a prosperous society.

Once you've landed on Intara, you'll have only two trading rounds to prove you're capable of building a successful trading post and show the Intarian people how to turn their resources into profitable trading strategies. Trade local goods to establish a viable trading framework, and guide Intara toward a prosperous future.

**If you manage to secure at least 200,000 XIRECs by the end of trading Round 2**, your mission will be considered a success. Only then will you proceed to the next phase.

---

## Round Schedule & Timeline

**All times are in CEST (UTC+2:00)**

| Phase | Dates | Duration |
|-------|-------|----------|
| Tutorial Round | March 16 - April 13, 2026 | ~4 weeks |
| Round 1 | April 14 - April 17 | 72 hours |
| Round 2 | April 17 - April 20 | 72 hours |
| Intermission | April 20 - April 24 | 4 days |
| Round 3 | April 24 - April 26 | 48 hours |
| Round 4 | April 26 - April 28 | 48 hours |
| Round 5 | April 28 - April 30 | 48 hours |

**Notes:**
- The competition commences at 12:00 CEST on April 14, 2026 and ends at 12:00 CEST on April 30, 2026.
- The hours required for round scoring are considered part of the following round's total time.
- It takes roughly 3 hours between rounds to calculate scores.
- The leading indicator of a new round opening is via email and a message sent in the Prosperity Discord Server.
- Schedule is subject to change based on unforeseen occurrences.

**Phase 1 (Rounds 1-2):** You need to earn at least 200,000 XIRECs to proceed to Phase 2.
**Phase 2 (Rounds 3-5):** The final competitive rounds.

---

## Game Mechanics Overview

### Rounds
The 16 days of simulation of Prosperity are divided into 5 rounds:
- **Rounds 1 and 2** last **72 hours** each
- **Rounds 3, 4, and 5** each last **48 hours**

At the end of every round, all teams must submit their algorithmic and manual trades to be processed. The algorithms then participate in a full day of trading against the Prosperity trading bots.

**Important:** All algorithms are trading separately; there is no interaction between the algorithms of different players.

When a new round starts, the results of the previous round will be disclosed and the leaderboard will be updated accordingly.


### The Core Challenge
For the algorithmic trading challenge, you will be writing and uploading a trading algorithm class in Python, which will then be set loose on Prosperity's exchange. On this exchange, the algorithm will trade against a number of bots, with the aim of earning as many XIRECs (the currency in Prosperity 4) as possible.

At the beginning of each round, it is disclosed which products will be available for trading on that day. Sample data for these products is provided that players can use to develop and test their algorithms.

### Simulation Details
- **Testing:** 1,000 iterations using data from a sample day (different than the actual challenge day)
- **Final simulation:** 10,000 iterations that determine your PnL for the round
- Each iteration calls the `run()` method with a `TradingState` object
- After the run, a log file is provided for debugging (includes print statement output)

### For Round 2 specifically
The Trader class should also define a `bid()` method. It is fine to have a `bid()` method in every submission for every round; it will be ignored for all rounds except Round 2.

---

## Trading Products

### Tutorial Round (Round 0): "Simulator Practice"
- **EMERALDS** - Position limit: 80
  - Precious gemstones with quite a stable value
  - Behaves like a classic stationary asset; mid-price stays centered around ~10,000 with a spread of roughly 16
  - Strong candidate for straightforward market-making strategy
- **TOMATOES** - Position limit: 80
  - Value tends to fluctuate over time (shows drift)
  - Cannot simply deploy a static market-making strategy

### Prosperity 3 Products (for reference, as P4 round products not yet publicly disclosed post-tutorial)

**Round 1 (Market Making):**
- RAINFOREST_RESIN - Fixed true price at 10,000, no intrinsic movement
- KELP - Slow random walk price movement
- SQUID_INK - Mean-reverting with tight spreads, occasional sharp jumps

**Round 2 (ETF Statistical Arbitrage):**
- CROISSANTS, JAMS, DJEMBES (individual constituents)
- PICNIC_BASKET1 (6x Croissants + 3x Jams + 1x Djembes)
- PICNIC_BASKET2 (4x Croissants + 2x Jams)

**Round 3 (Options):**
- VOLCANIC_ROCK (underlying, trading around 10,000)
- VOLCANIC_ROCK_VOUCHER_9500/9750/10000/10250/10500 (call options)

**Round 4:** Location arbitrage across multiple locations (15 products total)

**Round 5:** Trader IDs became explicitly available

*Note: Prosperity 4 round products (Rounds 1-5) are disclosed at the beginning of each round and may differ from Prosperity 3.*

---

## Technical Documentation: Writing an Algorithm in Python

### Overview of the Trader Class

The format for the trading algorithm is a predefined `Trader` class with a `run()` method containing all trading logic. For Round 2, the class should also define a `bid()` method.

```python
from datamodel import OrderDepth, UserId, TradingState, Order
from typing import List
import string

class Trader:

    def bid(self):
        return 15

    def run(self, state: TradingState):
        """Only method required. It takes all buy and sell orders for all
        symbols as an input, and outputs a list of orders to be sent."""

        print("traderData: " + state.traderData)
        print("Observations: " + str(state.observations))

        # Orders to be placed on exchange matching engine
        result = {}
        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []

            # Add trading logic here...

            result[product] = orders

        traderData = "SAMPLE"
        conversions = 1
        return result, conversions, traderData
```

### TradingState Class

The `TradingState` class holds all important market information:

```python
class TradingState(object):
    def __init__(self,
                 traderData: str,
                 timestamp: Time,
                 listings: Dict[Symbol, Listing],
                 order_depths: Dict[Symbol, OrderDepth],
                 own_trades: Dict[Symbol, List[Trade]],
                 market_trades: Dict[Symbol, List[Trade]],
                 position: Dict[Product, Position],
                 observations: Observation):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations
```

**Key properties:**
- **traderData**: string for persisting state between iterations (serialized via jsonpickle)
- **timestamp**: the current simulation timestamp
- **listings**: all available product listings (with symbol, product, denomination="XIRECS")
- **order_depths**: all buy/sell orders per product from other participants
- **own_trades**: trades the algorithm did since last TradingState
- **market_trades**: trades other participants did since last TradingState
- **position**: long/short position in every tradable product (dict: {product: signed_int})
- **observations**: additional data (simple values + ConversionObservation)

### Order Class

```python
class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
```

Each order has three properties:
1. **symbol**: the product for which the order is sent
2. **price**: max buy price (BUY) or min sell price (SELL)
3. **quantity**: positive = BUY order, negative = SELL order

### OrderDepth Class

```python
class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}
        self.sell_orders: Dict[int, int] = {}
```

- `buy_orders`: {price: quantity} - quantities are **positive**
- `sell_orders`: {price: quantity} - quantities are **negative**
- Example: `buy_orders = {9: 5, 10: 4}` means 5 units at price 9, 4 units at price 10
- Example: `sell_orders = {12: -3, 11: -2}` means 3 units for sale at 12, 2 at 11

### Trade Class

```python
class Trade:
    def __init__(self, symbol: Symbol, price: int, quantity: int,
                 buyer: UserId = None, seller: UserId = None,
                 timestamp: int = 0) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp
```

- `buyer` and `seller` are only non-empty if your algorithm is involved: `"SUBMISSION"` indicates your algo
- Counterparty information is not disclosed (same as real exchanges)

### Listing Class

```python
class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: Product):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination  # Always "XIRECS"
```

### ConversionObservation Class

```python
class ConversionObservation:
    def __init__(self, bidPrice: float, askPrice: float, transportFees: float,
                 exportTariff: float, importTariff: float,
                 sunlight: float, humidity: float):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sunlight = sunlight  # or sugarPrice/sunlightIndex depending on version
        self.humidity = humidity
```

### Observation Class

Contains two items:
1. Simple product-to-value dictionary inside `plainValueObservations`
2. Dictionary of complex `ConversionObservation` values for respective products (used to place conversion requests)

### Conversion Requests

If you decide to place a conversion request on a product, return the integer number as a "conversions" value from the `run()` method. Conditions:
- You need to obtain either long or short position earlier
- Conversion request cannot exceed possessed items count
- If you have 10 items short (-10), you can only request from 1 to 10; request for 11+ will be fully ignored
- Conversion request is not mandatory; you can send 0 or None
- While conversion happens, you will need to cover transportation and import/export tariff

### State Persistence

Technical implementation is based on AWS Lambda (stateless). Class/global variables are NOT guaranteed to persist. Use `traderData` string to serialize state via `jsonpickle` and deserialize on the next call via `TradingState.traderData`. Be aware of content size limitations. External calls (network, filesystem) are not supported.

### Sending Orders

Output from `run()` is a dictionary: `{product_name: [list of Order objects]}`

Example:
```python
result["PRODUCT1"] = [Order("PRODUCT1", 12, 7)]   # BUY 7 at price 12
result["PRODUCT2"] = [Order("PRODUCT2", 143, -5)]  # SELL 5 at price 143
```

---

## Data Model (datamodel.py)

Full file (from Prosperity 4):

```python
import json
from typing import Dict, List
from json import JSONEncoder
import jsonpickle

Time = int
Symbol = str
Product = str
Position = int
UserId = str
ObservationValue = int

class Listing:
    def __init__(self, symbol: Symbol, product: Product, denomination: Product):
        self.symbol = symbol
        self.product = product
        self.denomination = denomination

class ConversionObservation:
    def __init__(self, bidPrice: float, askPrice: float, transportFees: float,
                 exportTariff: float, importTariff: float,
                 sunlight: float, humidity: float):
        self.bidPrice = bidPrice
        self.askPrice = askPrice
        self.transportFees = transportFees
        self.exportTariff = exportTariff
        self.importTariff = importTariff
        self.sunlight = sunlight
        self.humidity = humidity

class Observation:
    def __init__(self, plainValueObservations: Dict[Product, ObservationValue],
                 conversionObservations: Dict[Product, ConversionObservation]) -> None:
        self.plainValueObservations = plainValueObservations
        self.conversionObservations = conversionObservations

class Order:
    def __init__(self, symbol: Symbol, price: int, quantity: int) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity

    def __str__(self) -> str:
        return "(" + self.symbol + ", " + str(self.price) + ", " + str(self.quantity) + ")"

    def __repr__(self) -> str:
        return "(" + self.symbol + ", " + str(self.price) + ", " + str(self.quantity) + ")"

class OrderDepth:
    def __init__(self):
        self.buy_orders: Dict[int, int] = {}
        self.sell_orders: Dict[int, int] = {}

class Trade:
    def __init__(self, symbol: Symbol, price: int, quantity: int,
                 buyer: UserId = None, seller: UserId = None,
                 timestamp: int = 0) -> None:
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.buyer = buyer
        self.seller = seller
        self.timestamp = timestamp

class TradingState(object):
    def __init__(self,
                 traderData: str,
                 timestamp: Time,
                 listings: Dict[Symbol, Listing],
                 order_depths: Dict[Symbol, OrderDepth],
                 own_trades: Dict[Symbol, List[Trade]],
                 market_trades: Dict[Symbol, List[Trade]],
                 position: Dict[Product, Position],
                 observations: Observation):
        self.traderData = traderData
        self.timestamp = timestamp
        self.listings = listings
        self.order_depths = order_depths
        self.own_trades = own_trades
        self.market_trades = market_trades
        self.position = position
        self.observations = observations

    def toJSON(self):
        return json.dumps(self, default=lambda o: o.__dict__, sort_keys=True)

class ProsperityEncoder(JSONEncoder):
    def default(self, o):
        return o.__dict__
```

---

## Position Limits

Like in the real world, algorithms are restricted by per-product position limits, which define the absolute position (long or short) that the algorithm is not allowed to exceed.

**How enforcement works:**
- If at any iteration, the player's algorithm sends buy (sell) orders for a product with an aggregated quantity that would, if all fully matched, result in the algorithm obtaining a long (short) position exceeding the position limit, **ALL the orders are cancelled by the exchange**.
- Position limits are enforced BEFORE orders are matched.

**Example:** If the position limit in product X is 30 and the current position is -5, then any aggregated buy order volume exceeding 30 - (-5) = 35 would result in an order rejection. However, an order with volume/quantity 35 itself is perfectly legal.

**Known position limits:**
- Tutorial Round: EMERALDS = 80, TOMATOES = 80
- Per-round position limits are listed in the 'Rounds' section of the Wiki (disclosed at round start)

---

## Order Execution & Matching

### How It Works

If there are active orders from counterparties against which the algorithm's orders can be matched, execution happens right away. If no immediate or partial execution is possible, the remaining order quantity will be visible for the bots, and one of them might trade against it. If none of the bots trades against the remaining order quantity, it is cancelled.

After cancellation of the algorithm's orders, but before the next TradingState comes in, bots may also place new orders.

### Order Processing Sequence (per timestep)
1. Deep-liquidity makers post orders
2. Occasional takers execute
3. Bot submits orders (passive or aggressive)
4. Other bots trade

### Priority Rules
Prosperity's exchange uses **price-time priority**:
- Incoming orders match first against existing orders with the most attractive price
- At the same price, earlier orders have priority

### BUY Order Execution
A BUY order executes immediately if there is an active SELL order with price <= BUY order price. The trade happens at the SELL order's price. If SELL order quantity < BUY order quantity, a resting order remains.

### SELL Order Execution
By symmetry, SELL orders execute against BUY orders with price >= SELL order price.

### Key Notes
- Speed and order cancellation are irrelevant: you have a full snapshot of the book and can submit any combination of passive or aggressive orders
- Every price level with buy orders should always be strictly lower than all levels with sell orders (otherwise a trade should have happened)

---

## Supported Libraries

All standard Python 3.12 libraries are fully supported. Additionally:
- **pandas**
- **NumPy**
- **jsonpickle** (for state serialization via traderData)

Importing other external libraries is NOT supported.

---

## Scoring & Leaderboard

- Performance tracked after each round in **XIRECs** (in-game currency)
- The team with the highest combined score (total PnL) after five rounds wins overall
- Participants are ranked according to their final simulated account balance
- **Tiebreaker:** If two or more teams have equal final balance, the team whose final trading algorithm was submitted earliest (by platform timestamp) ranks higher
- No element of chance or random selection is used

---

### Exchange
A central marketplace where buyers and sellers arrange trades in products (commodities, stocks, bonds, ETFs, derivatives, currencies, cryptocurrencies). Modern exchanges use digital infrastructure for automated matching.

### Order
A binding message to buy or sell a specified amount of a product on an exchange. Three types:
- **Limit order:** Buy or sell at a specified price or better
- **Market order:** Buy or sell immediately at best available prices
- **Stop order:** Becomes active when price reaches trigger level

**Properties:** Participant/Account, Product, Side (BUY/SELL), Quantity, Price (required for limit orders), Validity.

In Prosperity, the focus is on **limit orders**.

### Bid Order
A BUY order. "Best bid" = highest active buy order price.

### Ask Order / Offer
A SELL order. Similar to bid but for selling.

### Order Book
Collection of all buy and sell orders for a product. Bid side (left) shows BUY orders; ask side (right) shows SELL orders.

### Order Matching
Compatible BUY and SELL orders are matched, executing a trade.

### Priority
**Price-time priority** on Prosperity's exchange: best price first, then earliest order at same price.

### Market Making
A trading strategy of simultaneously buying and selling products to capture the bid-ask spread, without necessarily having a directional opinion. Example: currency exchange shop buying at 0.95 EUR and selling at 1.05 EUR.

---

## Programming Resources

### Tools Needed
- Install **Python 3.12**
---

## Community Tools & Resources

### Official
- **Wiki:** https://imc-prosperity.notion.site/prosperity-4-wiki
- **Discord:** https://discord.gg/SABeB8uKxd
- **Email:** prosperity@imc.com
- **Terms & Conditions:** prosperity.imc.com/docs/terms-and-conditions.pdf

### Community Backtesters
- **Prosperity 4 Backtester:** https://github.com/kevin-fu1/imc-prosperity-4-backtester
  - Usage: `python -m prosperity4bt <algorithm_file> <round>`
  - Example: `python -m prosperity4bt algo.py 0` (run all round 0 data)
  - Example: `python -m prosperity4bt algo.py 0--2` (specific day)
- **Prosperity 3 Backtester (reference):** https://github.com/jmerle/imc-prosperity-3-backtester
- **Prosperity Visualizer:** https://jmerle.github.io/imc-prosperity-visualizer/
- **prosperity4btx on PyPI:** pip install prosperity4btx

### Community Writeups & Repos
- Various GitHub repos with strategies from previous editions
- Medium writeups from past top-placing teams

---

## Tips & Strategy Insights (from previous editions)

### General Approach
- "If you can't explain why a strategy should work from first principles, then any 'outperformance' in historical data is probably noise."
- Choose parameter combinations showing consistent, flat regions of good performance rather than maximum backtested profit
- The winning teams invest hours each day during active rounds, iterating on algorithms and digging into manual challenges

### Market Making (Stable Products like Emeralds/Rainforest Resin)
- Identify "Wall Mid" (order book midpoint) as fair price estimate
- Take favorable trades immediately (buy below fair, sell above)
- Place passive quotes slightly improved versus existing liquidity
- Flatten inventory at fair value when position becomes skewed
- For very stable products (e.g., Emeralds at ~10,000), hardcode the fair value

### Trending Products (like Tomatoes/Kelp)
- Cannot use static market-making; need to estimate moving fair value
- Follow the mid-price trend; the fair value shifts over time

### Volatile Products (like Squid Ink)
- Tight bid-ask spread relative to average movement
- Occasional sharp price jumps require careful risk management
- Look for predictable bot behavior patterns

### ETF/Basket Arbitrage
- Look for spreads between baskets and their synthetic (constituent) prices
- Mean-reverting noise on basket prices creates opportunities
- Use threshold-based entry/exit
- Consider hedging basket exposure with constituents

### Options/Volatility
- Construct volatility smile from implied volatilities
- Fit curves to detect mispriced options
- Look for deviations from the fitted smile

### Technical Tips
- Each `run()` call must complete in **900ms** (average should be <=100ms)
- Use `traderData` for state persistence (serialize with jsonpickle)
- Log file output from print statements aids debugging
- Proper order book visualization tools are essential for building intuition
- Being active on Discord is valuable: tips, hints, and clarifications from moderators are shared early

### Data Resources
- For every new product introduced, several days of sample data are provided
- Two CSV files per day: one with all trades, one with market orders at every timestep
- Use the backtester to test strategies on historical data

---

## Technical Notes Summary

1. **run()** method timeout: 900ms per call (average <=100ms expected)
2. **Supported libraries:** Python 3.12 stdlib + pandas + NumPy + jsonpickle
3. **State persistence:** AWS Lambda (stateless) - use traderData string with jsonpickle
4. **No external calls:** Network and filesystem access not supported
5. **Testing:** 1,000 iterations on sample data; final scoring: 10,000 iterations
6. **Submission tracking:** Each upload gets a UUID + runID; include these when contacting support
7. **Position limits:** Enforced pre-match; exceeding causes ALL orders for that product to be cancelled
8. **Order lifetime:** Unmatched orders visible to bots; if no bot trades, cancelled before next TradingState
9. **Denomination:** All products denominated in XIRECS
