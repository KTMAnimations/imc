# IMC Prosperity 4

My code from IMC Prosperity 4, a fifteen-day algorithmic trading competition. Each round you get a couple of days of order book data for some fictional products, write a Python bot that quotes them, and submit once. It trades live against everyone else's bots, and that result is your score.

What kept nagging me was how little data you submit against. A strategy that looked clean on the two sample days would still lose when it ran live, and one backtest number told me nothing about whether it was good or just lucky.

Most of what's here is market making: quote both sides around an estimate of fair value and lean the quotes against your inventory so you aren't caught long or short when the price moves. That follows Avellaneda and Stoikov, [High-frequency trading in a limit order book](https://www.math.nyu.edu/~avellane/HighFrequencyTrading.pdf) (2008). To get past the single-number problem I used a Monte Carlo backtester (embedded under `imc-prosperity-4/`) that rebuilds a round from the order book statistics and replays the trader across thousands of simulated days, so you get a distribution instead of one PnL.

## Figures

These runs use the stock starter trader as a baseline, so the numbers are a losing template rather than a finished strategy. What I care about here is the shape.

![Monte Carlo dashboard overview](imc-prosperity-4/docs/screenshots/monte-carlo-dashboard-overview.png)

Summary view over 1000 simulated days: mean PnL, the 5th and 95th percentiles, and a per-product split.

![PnL distributions](imc-prosperity-4/docs/screenshots/monte-carlo-dashboard-distributions.png)

The same trader's PnL across days. A mean near zero hides outcomes from roughly minus 9k to plus 6k, which is the spread I was trying to see in the first place.

![Path bands](imc-prosperity-4/docs/screenshots/monte-carlo-dashboard-path-boards.png)

Fair value and mark-to-market PnL drawn as fan charts: the mean path with one and three sigma bands across every session.
