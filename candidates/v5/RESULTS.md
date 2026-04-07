# V5 Search Results

Target: sim_gui ≥ 3000, CLI > 31116 (baseline). Both must beat baseline.

## Reference

| name | sim_gui | CLI | notes |
|---|---|---|---|
| baseline | 2715.5 | 31,116 | tradestrategy.py |
| v4 | 2723.0 | 31,216 | cap=25, w=0.20 |
| v3 | 1583.5 | 33,667 | edge=8, w=0.10, alpha=0.4 — sim_gui regression |

## Findings about sim_gui ceiling

- Every TOMATOES menu threshold = exactly best_bid+1 / best_ask-1 (verified across all 17 logs)
- Baseline already captures 122/124 BUY + 109/109 SELL = 99% of TOMATOES menu qty
- Baseline already captures 67/67 BUY + 83/83 SELL = 100% of EMERALDS menu qty
- EMERALDS pnl is mathematically locked at 1050 in sim_gui (150 menu qty × 7 ticks edge)
- Aggressive take captures 100% of asks below fair / bids above fair
- Therefore sim_gui ≈ 2715 is very close to the true theoretical ceiling unless we
  change which TAKE/CLEAR decisions are made (different fair model)

## Candidates

| candidate | sim_gui | CLI | sim_d | cli_d | notes |
|---|---|---|---|---|---|
| v5a microprice | 2499.5 | 30720 | -216 | -396 | bb*ask_vol+ask*bid_vol; bad both |
| v5b no take sells | 2562.0 | 31125 | -154 | +9 | cascade kills it |
| v5c trend filter (lag5 thr0.5) | 2645.0 | 31355 | -71 | +239 | helps cli, hurts sim |
| v5d inv-cond take | 2493.5 | 30861 | -222 | -255 | bad both |
| v5e asym edge | -- | -- | -- | -- | all worse |
| v5f bb_quote | 2715.5 | 31084 | 0 | -32 | quote w/ bb_mid: neutral sim, slight cli loss |
| v5g no take sell + soft=70 | 2562.0 | 31125 | -154 | +9 | same as v5b, soft change irrelevant |
| v5h momentum filter | 2497-2710 | -- | mostly negative | mostly | drift detection too noisy |
| v5i pos target | 2574-2715 | 30697-31116 | <=0 | <=0 | nothing positive |
| v5j fair offset off=0.75 | **2760.5** | **31198** | **+45** | **+82** | best dual so far! |
| v5j off=0.74 | 2760.5 | 31174 | +45 | +58 | tied sim, less cli |
| v5j off=0.86 | 2788.5 | 31050 | +73 | -66 | best sim alone, neg cli |
| v5j off=0.71 | 2718.5 | 31254 | +3 | +138 | best cli, less sim |
| v5k take-only off | 2627-2645 | -- | negative | mixed | offset's gain isn't only from take |
| v5l make-only off | 2715.5 | 31146 | 0 | +30 | sim neutral, small cli win |
