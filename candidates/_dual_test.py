"""
Score any strategy file in BOTH backtesters.

Usage:
    python -m candidates._dual_test [--sim-mode average|aggregate] <path/to/strategy.py> [<path>...]

Strategy files don't need to live at repo root — this script copies them
to a tmp file at repo root (for `from datamodel import ...`), runs both
backtesters, then cleans up.

Reference baseline numbers (verified):
    sim_gui average over 17 logs: 2457.735294...
    sim_gui aggregated 17 logs:   2715.5
    CLI prosperity4bt round 0:   31116
"""

import argparse
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sim_gui.simulator import build_timeline, load_trader_from_file, simulate  # noqa: E402

LOG_DIR_NAMES = ['41408','41446','41499','41588','41641','42308','42752','42769',
                 '42797','42842','43070','43149','43770','43794','43848','44890','58160']
LOG_PATHS = [os.path.join(REPO, d, f'{d}.log') for d in LOG_DIR_NAMES]

_AGG_TL = None
_PER_LOG_TLS = None


def _agg_tl():
    global _AGG_TL
    if _AGG_TL is None:
        _AGG_TL = build_timeline(LOG_PATHS)
    return _AGG_TL


def _per_log_tls():
    global _PER_LOG_TLS
    if _PER_LOG_TLS is None:
        _PER_LOG_TLS = [build_timeline([path]) for path in LOG_PATHS]
    return _PER_LOG_TLS


def run_simgui(strategy_path, mode="average"):
    if mode == "aggregate":
        trader = load_trader_from_file(strategy_path)
        return simulate(trader, _agg_tl()).total_pnl
    if mode == "average":
        vals = []
        for tl in _per_log_tls():
            trader = load_trader_from_file(strategy_path)
            vals.append(simulate(trader, tl).total_pnl)
        return sum(vals) / len(vals)
    raise ValueError(f"unsupported sim mode: {mode}")


def run_cli(strategy_path):
    out = subprocess.check_output(
        ["prosperity4bt", strategy_path, "0", "--no-out", "--no-progress"],
        stderr=subprocess.STDOUT,
        text=True,
    )
    matches = re.findall(r"Total profit: ([\d,]+)", out)
    if not matches:
        raise RuntimeError(f"no total profit in CLI output:\n{out}")
    return int(matches[-1].replace(",", ""))


def score_file(path, sim_mode="average"):
    """Run a strategy file through both backtesters. Returns (sim, cli)."""
    abspath = os.path.abspath(path)
    if not os.path.isfile(abspath):
        raise FileNotFoundError(abspath)
    # Copy to repo root for datamodel imports
    tmp_path = os.path.join(REPO, "_dt_candidate.py")
    shutil.copyfile(abspath, tmp_path)
    try:
        sim = run_simgui(tmp_path, mode=sim_mode)
        cli = run_cli(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        pyc = os.path.join(REPO, "__pycache__")
        if os.path.exists(pyc):
            for f in os.listdir(pyc):
                if f.startswith("_dt_candidate."):
                    try:
                        os.remove(os.path.join(pyc, f))
                    except OSError:
                        pass
    return sim, cli


BASELINE_SIM_AVERAGE = 2457.735294117647
BASELINE_SIM_AGGREGATE = 2715.50
BASELINE_CLI = 31116


def main():
    ap = argparse.ArgumentParser(description="Score strategy files in the local dual backtest harness.")
    ap.add_argument(
        "--sim-mode",
        choices=["average", "aggregate"],
        default="average",
        help="Use the mean of per-log sim_gui runs, or the legacy merged-log aggregate run.",
    )
    ap.add_argument("paths", nargs="+", help="Strategy file(s) to score.")
    args = ap.parse_args()

    baseline_sim = BASELINE_SIM_AVERAGE if args.sim_mode == "average" else BASELINE_SIM_AGGREGATE
    print(f"{'name':<35s} {'sim':>8} {'sim_d':>8}  {'cli':>6} {'cli_d':>7}")
    print("-" * 75)
    for path in args.paths:
        try:
            sim, cli = score_file(path, sim_mode=args.sim_mode)
            ds = sim - baseline_sim
            dc = cli - BASELINE_CLI
            name = os.path.basename(path)
            sm = "+" if ds > 0 else ("=" if ds == 0 else "-")
            cm = "+" if dc > 0 else ("=" if dc == 0 else "-")
            print(f"{name:<35s} {sim:>8.1f} {sm}{abs(ds):>7.1f}  {cli:>6} {cm}{abs(dc):>6}")
        except Exception as e:
            print(f"{os.path.basename(path):<35s} ERROR: {e}")


if __name__ == "__main__":
    main()
