"""fno_index_trend.py — test the validated trend engine on NIFTY/BANKNIFTY index (60min).

We proved the crypto/commodity engine (market entry, stop 3.0xATR, RR 2.5, ADX>=15 + EMA200-slope
gate) has edge on trending/less-arbitraged markets but NOT on single-stock equity/futures. This
tests the one untested case: the INDEX itself. Merges the Kite 60min pulls (saved as tool-result
files), runs the canonical backtester, and writes a per-trade CSV for portfolio combination.

    python fno_index_trend.py
"""
import glob, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backtest
from crypto import CryptoStrategy

TOOLDIR = r"C:\Users\deeps\.claude\projects\C--TradingApp\e277dd81-f874-4362-b241-8d8d6ada095a\tool-results"
IDXDIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "idx")


def merge():
    os.makedirs(IDXDIR, exist_ok=True)
    bysym = {"NIFTY": {}, "BANKNIFTY": {}}
    for fp in glob.glob(os.path.join(TOOLDIR, "*get_historical_data*.txt")):
        try:
            rows = json.load(open(fp, encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(rows, list) or not rows:
            continue
        med = sorted(r["close"] for r in rows)[len(rows) // 2]
        sym = "BANKNIFTY" if med > 40000 else "NIFTY"
        for r in rows:
            bysym[sym][r["date"]] = r        # dedup by timestamp
    for sym, d in bysym.items():
        rows = [d[k] for k in sorted(d)]
        json.dump(rows, open(os.path.join(IDXDIR, f"{sym}_60minute.json"), "w"))
        if rows:
            print(f"{sym}: {len(rows)} bars {rows[0]['date'][:10]}..{rows[-1]['date'][:10]}")


def main():
    merge()
    strat = CryptoStrategy(adx_min=15.0, slope_min=0.005, min_score=2.5)
    print("\n=== validated engine (market entry, stop 3xATR, RR 2.5, ADX15+slope0.5%) on INDEX 60min ===")
    trades = backtest.run_dir(IDXDIR, "60minute", rr=2.5, strat=strat,
                              csv=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                               "results", "idx_trend_trades.csv"))
    return trades


if __name__ == "__main__":
    main()
