# Top-Team Strategy Implementations - IMC Prosperity 1/2/3

Code collected from publicly available GitHub repos of top-placing teams.
Organized by product/strategy type for Prosperity 4 reference.

## Source Repos

| Team | Placement | Repo |
|------|-----------|------|
| Stanford Cardinal | 2nd P1 | github.com/ShubhamAnandJain/IMC-Prosperity-2023-Stanford-Cardinal |
| Linear Utility | 2nd P2 | github.com/ericcccsliu/imc-prosperity-2 |
| jmerle | 9th P2 | github.com/jmerle/imc-prosperity-2 |
| pe049395 | 13th P2 | github.com/pe049395/IMC-Prosperity-2024 |
| Frankfurt Hedgehogs | 2nd P3 | github.com/TimoDiehm/imc-prosperity-3 |
| Alpha Animals | 9th P3 | github.com/CarterT27/imc-prosperity-3 |
| chrispyroberts | 7th P3 | github.com/chrispyroberts/imc-prosperity-3 |
| ShivUCSD | P3 | github.com/ShivUCSD1104/IMC-Prosperity-3 |
| nicolassinott | P1 | github.com/nicolassinott/IMC_Prosperity |
| mridhanbalaji | P3 | github.com/mridhanbalaji/IMC_Prosperity_3 |

---

## 1. Market Making - Stable Products (`1_market_making_stable/`)

**Target products:** PEARLS (P1), AMETHYSTS (P2), RAINFOREST_RESIN (P3), EMERALDS (P4 tutorial)

All have a known fair value ~10,000. Every top team hardcodes this.

| File | Team | Key Technique |
|------|------|---------------|
| `p1_stanford_cardinal_2nd_place_PEARLS.py` | Stanford Cardinal (2nd P1) | Hardcoded 10000, 3-phase take/clear/make |
| `p2_linear_utility_2nd_place_AMETHYSTS.py` | Linear Utility (2nd P2) | **Gold standard** - take/clear/make with soft position limit=10, adverse selection filter (vol>=15) |
| `p2_jmerle_9th_place_AMETHYSTS.py` | jmerle (9th P2) | OOP Strategy pattern, soft/hard liquidation windows |
| `p3_frankfurt_hedgehogs_2nd_place_RESIN.py` | Frankfurt Hedgehogs (2nd P3) | **"Wall Mid"** = (min_bid + max_ask)/2 for robust fair value |
| `p3_chrispyroberts_7th_place_RESIN.py` | chrispyroberts (7th P3) | Hardcoded 10000, penny-the-competition logic |
| `p3_shiv_ucsd_RESIN.py` | ShivUCSD | Lockout window + adaptive liquidation pricing |

**Key patterns:**
- Fair value = 10,000 (hardcoded)
- 3-phase: (1) Take favorable orders, (2) Flatten inventory, (3) Quote passively inside spread
- Penny competitors: `best_bid + 1` / `best_ask - 1`
- Inventory mgmt: skew prices when position is large

---

## 2. Trending Products (`2_trending_products/`)

**Target products:** STARFRUIT (P2), KELP (P3), TOMATOES (P4 tutorial)

Fair value drifts over time - need dynamic estimation.

| File | Team | Key Technique |
|------|------|---------------|
| `p2_linear_utility_2nd_place_STARFRUIT.py` | Linear Utility (2nd P2) | Volume-filtered mid (ignore orders vol>=15) + reversion beta (-0.229) |
| `p2_jmerle_9th_place_STARFRUIT.py` | jmerle (9th P2) | "Popular price mid" (max volume level on each side) |
| `p2_pe049395_13th_place_STARFRUIT_GLFT.py` | pe049395 (13th P2) | GLFT optimal market making model |
| `p3_frankfurt_hedgehogs_2nd_place_KELP.py` | Frankfurt Hedgehogs (2nd P3) | Wall mid + Olivia insider tracking |
| `p3_chrispyroberts_7th_place_KELP.py` | chrispyroberts (7th P3) | Wall mid + MA crossover for trend |
| `p3_shiv_ucsd_KELP_ARX.py` | ShivUCSD | Autoregressive model: 5 lags + spread + imbalance |
| `p3_mridhanbalaji_KELP.py` | mridhanbalaji | Static fair value + take/clear/make |

**Key patterns:**
- "Wall mid" = (worst_bid + worst_ask) / 2 - more stable than best bid/ask mid
- Filter out large orders (vol>=15) from informed market makers
- Penny-the-competition with dynamic fair value
- Some teams track informed traders (Olivia) for directional signal

---

## 3. Volatile Products (`3_volatile_products/`)

**Target products:** SQUID_INK (P3), BANANAS (P1)

Mean-reverting with sharp jumps. Tight spreads relative to movement.

| File | Team | Key Technique |
|------|------|---------------|
| `p3_frankfurt_hedgehogs_2nd_place_SQUID_INK.py` | Frankfurt Hedgehogs (2nd P3) | **Olivia copy-trading** - follow informed trader's direction |
| `p3_alpha_animals_9th_place_SQUID_INK.py` | Alpha Animals (9th P3) | Olivia copy-trading + volatility spike mean-reversion (>3 std devs) |
| `p3_chrispyroberts_SQUID_INK_spike_detection.py` | chrispyroberts (7th P3) | Dual MA crossover (50/250) + flash crash detection (delta_vol > 2) |
| `p3_shiv_pandera_SQUID_INK_hawkes.py` | Pandera | Hawkes process intensity model on bid depletion events |
| `p1_nicolassinott_BANANAS_ema_reversion.py` | nicolassinott (P1) | EMA(0.5) mean-reversion with position-dependent spread |
| `p2_pe049395_13th_place_GLFT_volatility.py` | pe049395 (13th P2) | GLFT model with inventory risk aversion |

**Key insight:** Top 2 P3 teams both used **Olivia copy-trading** (follow informed trader) rather than technical volatility models. The "volatile" product was predictable through bot behavior detection.

---

## 4. ETF/Basket Arbitrage (`4_etf_basket_arbitrage/`)

**Target products:** GIFT_BASKET (P2), PICNIC_BASKET1/2 (P3)

Trade spreads between baskets and synthetic constituent prices.

| File | Team | Key Technique |
|------|------|---------------|
| `p2_linear_utility_2nd_place_GIFT_BASKET.py` | Linear Utility (2nd P2) | Synthetic order depth construction, SWMID spread, z-score>7 entry, full hedge |
| `p2_jmerle_9th_place_GIFT_BASKET.py` | jmerle (9th P2) | Static thresholds (long diff<290, short diff>355), no rolling stats |
| `p2_pe049395_13th_place_GIFT_BASKET.py` | pe049395 (13th P2) | VWAP-based spread, norm_spread - 380, basket-only (no hedge) |
| `p3_frankfurt_hedgehogs_2nd_place_PICNIC_BASKET.py` | Frankfurt Hedgehogs (2nd P3) | Running mean premium (60k+ samples), Olivia-adjusted thresholds, 0.5x hedge |
| `p3_chrispyroberts_PICNIC_BASKET_zscore.py` | chrispyroberts | Dual z-score: inter-basket spread + basket2 vs synthetic |
| `p3_shiv_ucsd_PICNIC_BASKET_vwap.py` | ShivUCSD | Clean VWAP-based arb with immediate constituent hedging |

**Key patterns:**
- Compute synthetic price from constituents (sum of weighted mids/VWAPs)
- Track spread = basket_price - synthetic_price over time
- Enter when spread deviates beyond threshold (z-score or absolute)
- Exit on mean reversion back toward center
- Hedge by trading opposite direction in constituents

---

## 5. Options/Volatility (`5_options_volatility/`)

**Target products:** COCONUT_COUPON (P2), VOLCANIC_ROCK_VOUCHER (P3)

Implied volatility surface + mispricing detection.

| File | Team | Key Technique |
|------|------|---------------|
| `p2_linear_utility_2nd_place_COCONUT_COUPON_v4.py` | Linear Utility (2nd P2) | Full Black-Scholes class, IV z-score mean reversion, delta hedging |
| `p2_linear_utility_2nd_place_COCONUT_COUPON_v3.py` | Linear Utility (2nd P2) | Same BS, different z-score threshold (5.1 vs 21) |
| `p2_linear_utility_2nd_place_round5_combined.py` | Linear Utility (2nd P2) | Final combined all-round strategy |
| `p2_jmerle_9th_place_COCONUT_COUPON_r4.py` | jmerle (9th P2) | Fixed sigma=0.194962, trade around BS fair value +/-2 |
| `p2_jmerle_9th_place_COCONUT_COUPON_r5.py` | jmerle (9th P2) | Refined sigma=0.193785 |
| `p2_pe049395_13th_place_COCONUT_COUPON.py` | pe049395 (13th P2) | Newton-Raphson IV solver, IV vs HV spread, GLFT MM |
| `p3_frankfurt_hedgehogs_2nd_place_VOLCANIC_ROCK.py` | Frankfurt Hedgehogs (2nd P3) | **Vol smile** via quadratic on moneyness, IV scalping, vega-aware thresholds |
| `p3_alpha_animals_9th_place_VOLCANIC_ROCK.py` | Alpha Animals (9th P3) | Full BS class, rolling 30-period IV history, position-aware MM |
| `p3_chrispyroberts_VOLCANIC_ROCK.py` | chrispyroberts | **Separate bid/ask vol smile fits**, take-and-replace MM, per-trade delta hedge |
| `p3_shiv_ucsd_23rd_place_VOLCANIC_ROCK.py` | ShivUCSD (23rd P3) | Simplified BS-inspired model, linear delta, multi-strike hedging |

**Key patterns:**
- Black-Scholes for fair value + implied volatility (bisection or Newton-Raphson)
- Volatility smile: fit quadratic `IV = a*m^2 + b*m + c` on moneyness
- Trade deviations from fitted smile (IV scalping)
- Delta hedge underlying against options portfolio
- Vega-aware position sizing
