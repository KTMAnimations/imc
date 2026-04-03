# IMC Prosperity 4 — Tutorial Round Strategy Candidates

## Backtest Results (prosperity4bt, Round 0, Days -2 and -1)

| # | Script | INV_SKEW | CAP | L1 | Day -2 | Day -1 | Total | vs Base |
|---|--------|----------|-----|-----|--------|--------|-------|---------|
| 1 | candidate_aggressive.py | 0.07 | 30 | No | 15,929 | 15,367 | **31,296** | **+412** |
| 2 | candidate_balanced.py | 0.06 | 20 | No | 15,929 | 15,367 | **31,296** | **+412** |
| 3 | candidate_balanced_l1.py | 0.06 | 20 | Yes | 15,394 | 15,846 | **31,240** | **+356** |
| 4 | candidate_conservative.py | 0.05 | 25 | No | 15,265 | 15,959 | **31,224** | **+340** |
| 5 | original_43794.py | N/A | 80 | No | 15,400 | 15,704 | 31,104 | +220 |
| 6 | baseline_42769.py | 0.05 | 20 | No | 15,168 | 15,717 | 30,884 | 0 |

### Per-Product Breakdown

| Script | EM Day-2 | TOM Day-2 | EM Day-1 | TOM Day-1 |
|--------|----------|-----------|----------|-----------|
| candidate_aggressive | 7,182 | 8,747 | 7,763 | 7,604 |
| candidate_balanced | 7,182 | 8,747 | 7,763 | 7,604 |
| candidate_balanced_l1 | 7,182 | 8,212 | 7,763 | 8,083 |
| candidate_conservative | 7,182 | 8,083 | 7,763 | 8,196 |
| original_43794 | 7,182 | 8,218 | 7,763 | 7,941 |
| baseline_42769 | 7,182 | 7,986 | 7,763 | 7,954 |

EMERALDS PnL is identical (7,182 / 7,763) across all versions. All differences come from TOMATOES.

---

## Script Descriptions

### baseline_42769.py — Current Best on Platform (profit=2723.1)
- **TOMATOES_INV_SKEW = 0.05**, PASSIVE_CAP = 20
- Wall mid fair value (deepest liquidity levels) + EMA alpha=0.5
- Inv-adjusted fair for all phases (take/clear/make)
- Inv-aware passive sizing, price priority check, ceil/floor bounds
- EMERALDS: take/clear/make with soft/hard limit price skewing
- Best platform score: 2723.1 (submission 42769)
- Most consistent ending positions: TOM always near -5

### candidate_conservative.py — Minimal Change (+340 backtest)
- **TOMATOES_PASSIVE_CAP = 25** (was 20), skew unchanged at 0.05
- Only change: 5 more passive volume per side
- Most balanced across days (Day-2: +97, Day-1: +242 vs base)
- Lowest risk of the candidates — one parameter change

### candidate_balanced.py — Tighter Inventory (+412 backtest)
- **TOMATOES_INV_SKEW = 0.06** (was 0.05), cap unchanged at 20
- More aggressive inventory unwinding via fair value shift
- At pos=20: fair shifts 1.2 ticks (was 1.0) against position
- Produces identical backtest results to aggressive on this data

### candidate_aggressive.py — Maximum Local Score (+412 backtest)
- **TOMATOES_INV_SKEW = 0.07, PASSIVE_CAP = 30**
- Most aggressive inventory management + highest passive volume
- Same backtest score as balanced on this data (fills don't differ)
- May diverge on different market conditions (platform scoring day)

### candidate_balanced_l1.py — With L1 Imbalance Signal (+356 backtest)
- **TOMATOES_INV_SKEW = 0.06** + L1 order book imbalance adjustment
- Shifts wall mid by up to ~0.7 ticks based on bid/ask volume ratio
- More buy pressure → fair shifts up; more sell pressure → fair shifts down
- Most balanced across days of any candidate (Day-2: +226, Day-1: +129)
- L1 imbalance is HARMFUL at lower skew values but HELPS at 0.06+
  because the tighter skew manages the extra positions it creates

### original_43794.py — Original Code Before Improvements (+220 backtest)
- Book-extreme mid (min bids / max asks), NO EMA, NO inv skew
- Full capacity (80) passive orders, no inv-aware sizing
- TAKE_WIDTH=1, MIN_EDGE=2 with penny-jumping
- High variance: platform scores ranged 2609–2756 (same code, different runs)
- Positions swing wildly (TOM: +6 to +48 between submissions)

---

## Platform Submission History

All submissions face the SAME scoring day. Scoring fair values: EM=10000, TOM=4996.572.

| Submission | Profit | EM pos | TOM pos | Strategy |
|-----------|--------|--------|---------|----------|
| 43794 | 2756.5 | -9 | +48 | original (lucky run) |
| 42769 | 2723.1 | -9 | -5 | baseline_42769 |
| 43770 | 2723.1 | -9 | -5 | baseline_42769 + logging |
| 41588 | 2719.2 | -16 | +37 | simple strategy.py v2 |
| 43149 | 2684.1 | -9 | -5 | + TOM price skewing |
| 42797 | 2655.9 | -9 | -9 | + L1 imbalance + EMA clearing |
| 42308 | 2632.7 | -9 | +24 | strategy.py v5 (VWAP mid) |
| 43070 | 2612.1 | -9 | -5 | + raw EMA for takes |
| 42752 | 2609.4 | -9 | +6 | original (normal run) |
| 42842 | 2307.3 | -38 | -31 | + TAKE_WIDTH=0 + raw EMA |

---

## Key Findings

### What Works
- **Wall mid** fair value (deepest liquidity levels) outperforms VWAP mid
- **Inv-adjusted fair** for taking provides implicit trend-following
- **Inv-aware passive sizing** keeps ending positions small
- **3-phase architecture** (take/clear/make) is the correct framework
- **INV_SKEW 0.06–0.07** outperforms 0.05 on backtester (+350–412)

### What Doesn't Work
- **Raw EMA for clearing**: -518 on backtester. Clearing at inv-adjusted fair is better.
- **TAKE_WIDTH=0** for EMERALDS: generates huge cash but massive positions (-416 platform)
- **Raw EMA for takes**: loses ~0.4 avg sell price (sells later at worse prices in downtrend)
- **L1 imbalance at low skew**: adds noise without enough position management to handle it

### Variance vs Consistency
- Original code: high variance (platform 2609–2756), avg ~2683
- Baseline 42769: low variance (platform ~2723 consistently)
- Candidates 1–4: expected to improve avg while maintaining moderate variance

### Scoring Mechanics
- Profit = trading cash + EMERALDS_pos × 10000 + TOMATOES_pos × TOM_scoring_fair
- EMERALDS PnL is fixed at 1050 across ALL strategy variants (same fills)
- ALL profit differences come from TOMATOES
- Ending position × scoring fair is the main source of variance

---

## Exhaustive Parameter Sweep (62 configurations tested)

### Top 15 Results

| # | Config | Day -2 | Day -1 | Total | vs Base |
|---|--------|--------|--------|-------|---------|
| 1 | **skew=0.07 + round bounds** | 15,870 | 15,487 | **31,357** | **+473** |
| 2 | skew=0.07 / cap=30 | 15,929 | 15,367 | 31,296 | +412 |
| 3 | skew=0.07 | 15,916 | 15,367 | 31,283 | +399 |
| 4 | skew=0.08 | 15,916 | 15,367 | 31,283 | +399 |
| 5 | round bounds only | 15,487 | 15,755 | 31,242 | +358 |
| 6 | skew=0.06 + L1 imbalance | 15,394 | 15,846 | 31,240 | +356 |
| 7 | skew=0.06 | 15,485 | 15,749 | 31,234 | +350 |
| 8 | cap=25 | 15,265 | 15,959 | 31,224 | +340 |
| 9 | skew=0.06 + round bounds | 15,451 | 15,761 | 31,212 | +328 |
| 10 | skew=0.03 | 15,380 | 15,786 | 31,166 | +282 |
| 11 | no price priority check | 15,375 | 15,736 | 31,111 | +227 |
| 12 | skew=0.06 + VWAP mid | 15,266 | 15,840 | 31,106 | +222 |
| 13 | original 43794 | 15,400 | 15,704 | 31,104 | +220 |
| 14 | VWAP mid only | 15,238 | 15,798 | 31,036 | +152 |
| 15 | skew=0.06 / alpha=0.4 | 15,584 | 15,453 | 31,036 | +152 |

### Parameter Sensitivity

**INV_SKEW** (most impactful, cap=20):
- 0.00: 30,652 | 0.03: 31,166 | 0.05: 30,884 | 0.06: 31,234 | **0.07: 31,283** | 0.08: 31,283 | 0.10: 29,859
- Sweet spot: 0.06–0.08. Falls off sharply at 0.10+.

**PASSIVE_CAP** (moderate impact, skew=0.05):
- 10: 30,450 | 15: 30,533 | 20: 30,884 | **25: 31,224** | 30: 30,950 | 80: 30,758
- Sweet spot: 20–25. Diminishing returns above 30.

**EMA_ALPHA** (low impact at skew=0.05):
- 0.2: 30,758 | 0.3: 30,505 | 0.4: 30,505 | **0.5: 30,884** | 0.6: 30,573 | 0.8: 30,296
- 0.5 is optimal. Deviations hurt.

**Bounds method**:
- ceil/floor: 30,884 | **round: 31,242** (+358)
- round bounds ensure minimum ~0.5 tick edge. ceil/floor allows near-zero edge fills.

### Features That Help
- **round bounds (+358)**: Prevents thin-edge adverse passive fills
- **INV_SKEW 0.07 (+399)**: More aggressive unwinding
- **Combined (+473)**: Best of both

### Features That Hurt
- **EMA clearing (-518)**: Clearing at raw EMA is worse than inv-adjusted
- **No clearing (crash)**: Clearing is structurally required
- **INV_SKEW > 0.08**: Over-rotation, kills PnL
- **High PASSIVE_CAP (60-80)**: More exposure without more fills

### New Top Candidate: candidate_top.py
- INV_SKEW = 0.07, round bounds (round(fair) ± 1 instead of ceil/floor)
- Backtest total: 31,357 (+473 vs baseline)
- Most improved Day-2 TOMATOES: 8,688 (vs 7,986 baseline)
