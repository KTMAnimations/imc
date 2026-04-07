"""
Dual-backtester harness: for each candidate parameter set, runs both
sim_gui and prosperity4bt and reports both totals plus deltas vs baseline.

Hard requirement for v4: BOTH must improve over baseline.

Baseline reference (verified):
  sim_gui average over 17 logs: 2457.735294...
  sim_gui aggregated 17 logs: 2715.50
  CLI prosperity4bt round 0:  31,116
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
TEMPLATE = os.path.join(HERE, "_v4_template.py")

if REPO not in sys.path:
    sys.path.insert(0, REPO)

from sim_gui.simulator import build_timeline, load_trader_from_file, simulate  # noqa: E402

LOG_DIR_NAMES = ['41408','41446','41499','41588','41641','42308','42752','42769',
                 '42797','42842','43070','43149','43770','43794','43848','44890','58160']
LOG_PATHS = [os.path.join(REPO, d, f'{d}.log') for d in LOG_DIR_NAMES]

# Cache the aggregated timeline (deterministic, only built once)
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


# Default param values matching baseline (must match _v4_template.py defaults)
DEFAULTS = {
    "EMERALDS_MAKE_EDGE": 7,
    "EMERALDS_SOFT_LIMIT": 35,
    "EMERALDS_HARD_LIMIT": 60,
    "TOMATOES_EMA_ALPHA": 0.50,
    "TOMATOES_INV_SKEW": 0.05,
    "TOMATOES_SOFT_LIMIT": 40,
    "TOMATOES_HARD_LIMIT": 60,
    "TOMATOES_PASSIVE_CAP": 20,
    "TOMATOES_BBMID_WEIGHT": 0.00,
}


def write_candidate(params, dst_path):
    """Write template with params substituted to `dst_path` (must be in repo root)."""
    with open(TEMPLATE) as f:
        text = f.read()
    p = dict(DEFAULTS)
    p.update(params)
    text = re.sub(r"^EMERALDS_MAKE_EDGE = \d+",
                  f"EMERALDS_MAKE_EDGE = {p['EMERALDS_MAKE_EDGE']}", text, count=1, flags=re.M)
    text = re.sub(r"^EMERALDS_SOFT_LIMIT = \d+",
                  f"EMERALDS_SOFT_LIMIT = {p['EMERALDS_SOFT_LIMIT']}", text, count=1, flags=re.M)
    text = re.sub(r"^EMERALDS_HARD_LIMIT = \d+",
                  f"EMERALDS_HARD_LIMIT = {p['EMERALDS_HARD_LIMIT']}", text, count=1, flags=re.M)
    text = re.sub(r"^TOMATOES_EMA_ALPHA = [\d.]+",
                  f"TOMATOES_EMA_ALPHA = {p['TOMATOES_EMA_ALPHA']}", text, count=1, flags=re.M)
    text = re.sub(r"^TOMATOES_INV_SKEW = [\d.]+",
                  f"TOMATOES_INV_SKEW = {p['TOMATOES_INV_SKEW']}", text, count=1, flags=re.M)
    text = re.sub(r"^TOMATOES_SOFT_LIMIT = \d+",
                  f"TOMATOES_SOFT_LIMIT = {p['TOMATOES_SOFT_LIMIT']}", text, count=1, flags=re.M)
    text = re.sub(r"^TOMATOES_HARD_LIMIT = \d+",
                  f"TOMATOES_HARD_LIMIT = {p['TOMATOES_HARD_LIMIT']}", text, count=1, flags=re.M)
    text = re.sub(r"^TOMATOES_PASSIVE_CAP = \d+",
                  f"TOMATOES_PASSIVE_CAP = {p['TOMATOES_PASSIVE_CAP']}", text, count=1, flags=re.M)
    text = re.sub(r"^TOMATOES_BBMID_WEIGHT = [\d.]+",
                  f"TOMATOES_BBMID_WEIGHT = {p['TOMATOES_BBMID_WEIGHT']}", text, count=1, flags=re.M)
    with open(dst_path, "w") as f:
        f.write(text)


def run_simgui(strategy_path):
    """Return mean total profit over individual log runs."""
    vals = []
    for tl in _per_log_tls():
        trader = load_trader_from_file(strategy_path)
        vals.append(simulate(trader, tl).total_pnl)
    return sum(vals) / len(vals)


def run_cli(strategy_path):
    """Return total profit from prosperity4bt round 0."""
    out = subprocess.check_output(
        ["prosperity4bt", strategy_path, "0", "--no-out", "--no-progress"],
        stderr=subprocess.STDOUT,
        text=True,
    )
    # Last "Total profit: N" line is the merged total (can be negative)
    matches = re.findall(r"Total profit: (-?[\d,]+)", out)
    if not matches:
        raise RuntimeError(f"no total profit in CLI output:\n{out}")
    return int(matches[-1].replace(",", ""))


def score(params):
    """Run candidate (param overrides on the _v4_template) through both
    backtesters. Returns (sim, cli)."""
    # Strategy file MUST be at repo root so `from datamodel import ...` works
    tmp_path = os.path.join(REPO, "_v4_candidate.py")
    try:
        write_candidate(params, tmp_path)
        sim = run_simgui(tmp_path)
        cli = run_cli(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        # Also remove pycache for the candidate
        pyc = os.path.join(REPO, "__pycache__")
        if os.path.exists(pyc):
            for f in os.listdir(pyc):
                if f.startswith("_v4_candidate."):
                    try:
                        os.remove(os.path.join(pyc, f))
                    except OSError:
                        pass
    return sim, cli


def score_file(src_path):
    """Run an ARBITRARY strategy file through both backtesters. Copies it
    to the repo root first so `from datamodel import ...` resolves.
    Returns (sim, cli)."""
    src_path = os.path.abspath(src_path)
    if not os.path.isfile(src_path):
        raise FileNotFoundError(src_path)
    tmp_path = os.path.join(REPO, "_v4_candidate.py")
    try:
        shutil.copyfile(src_path, tmp_path)
        sim = run_simgui(tmp_path)
        cli = run_cli(tmp_path)
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        pyc = os.path.join(REPO, "__pycache__")
        if os.path.exists(pyc):
            for f in os.listdir(pyc):
                if f.startswith("_v4_candidate."):
                    try:
                        os.remove(os.path.join(pyc, f))
                    except OSError:
                        pass
    return sim, cli


def fmt_file(label, path):
    sim, cli = score_file(path)
    ds = sim - BASELINE_SIM
    dc = cli - BASELINE_CLI
    sim_marker = "+" if ds > 0 else ("=" if ds == 0 else "-")
    cli_marker = "+" if dc > 0 else ("=" if dc == 0 else "-")
    print(f"  {label:35s}  sim={sim:8.1f} ({sim_marker}{abs(ds):>7.1f})   "
          f"cli={cli:6d} ({cli_marker}{abs(dc):>5d})")
    return sim, cli


# Baseline reference values (verified manually)
BASELINE_SIM = 2457.735294117647
BASELINE_CLI = 31116


def fmt_delta(label, params):
    sim, cli = score(params)
    ds = sim - BASELINE_SIM
    dc = cli - BASELINE_CLI
    sim_marker = "+" if ds > 0 else ("=" if ds == 0 else "-")
    cli_marker = "+" if dc > 0 else ("=" if dc == 0 else "-")
    print(f"  {label:30s}  sim={sim:8.1f} ({sim_marker}{abs(ds):>7.1f})   "
          f"cli={cli:6d} ({cli_marker}{abs(dc):>5d})")
    return sim, cli


if __name__ == "__main__":
    print("Baseline (no overrides):")
    fmt_delta("baseline", {})
