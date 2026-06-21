"""fno_straddle.py — F&O strategy #1: NIFTY weekly ATM short-straddle (volatility risk premium).

Edge: India VIX (implied vol) is systematically ABOVE realized vol, so selling the ATM straddle
collects more premium than the realized move costs — ON AVERAGE. Validated 2026-06-19 (2023-26):
the edge is concentrated in HIGH-IV regimes (sell only when VIX is elevated); selling in low IV
loses. Tail risk on big-gap weeks is real -> a stop is mandatory (never sell naked unhedged).

This is a MODEL: each week sell the ATM straddle priced via Black-Scholes using India VIX as IV
(r=0, T=7/365), hold to a weekly expiry, settle at intrinsic. Inputs are daily NIFTY + India VIX
(data/fno/). Not a live-fill simulator — directional/validation tool. Margin not modeled; judge
by Sharpe / return-on-margin, not raw rupees. Lot size has changed over time (default 75).

    python fno_straddle.py [--min-vix 14] [--stop-mult 1.5] [--cost 0.005] [--lot 75]
"""
from __future__ import annotations
import argparse, json, math, os, statistics as st

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fno")
T = 7 / 365
STEP = 5  # trading days per weekly cycle (non-overlapping)


def _ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def atm_straddle(S, sigma, t=T):
    """Black-Scholes ATM (K=S, r=0) call+put premium in index points."""
    d1 = sigma * math.sqrt(t) / 2
    return 2 * S * (_ncdf(d1) - _ncdf(-d1))


def load(name):
    return {r["date"]: r for r in json.load(open(os.path.join(DATA, f"{name}_day.json")))}


def backtest(min_vix=0.0, stop_mult=0.0, cost=0.005, lot=75):
    N, V = load("NIFTY50"), load("INDIAVIX")
    days = sorted(set(N) & set(V))
    trades = []
    for i in range(0, len(days) - STEP, STEP):
        d0 = days[i]; S0 = N[d0]["close"]; vix = V[d0]["close"]
        if vix < min_vix:
            continue
        prem = atm_straddle(S0, vix / 100.0)
        # walk the week; optional stop when the move exceeds stop_mult x premium
        exit_move = abs(N[days[i + STEP]]["close"] - S0); stopped = False
        if stop_mult > 0:
            for j in range(i + 1, i + STEP + 1):
                intraday_move = max(abs(N[days[j]]["high"] - S0), abs(N[days[j]]["low"] - S0))
                if intraday_move >= stop_mult * prem:
                    exit_move = intraday_move; stopped = True; break
        pnl = prem - exit_move - cost * prem
        trades.append(dict(d0=d0, vix=vix, prem=prem, move=exit_move, pnl=pnl, stopped=stopped))
    return trades


def report(trades, label, lot):
    n = len(trades)
    if not n:
        print(f"{label}: no trades"); return
    wins = sum(1 for t in trades if t["pnl"] > 0)
    pnls = [t["pnl"] for t in trades]; tot = sum(pnls); avg = tot / n
    sd = st.pstdev(pnls); sharpe = avg / sd * math.sqrt(52) if sd else 0
    eq = peak = mdd = 0
    for t in trades:
        eq += t["pnl"]; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    edge = st.mean(t["prem"] for t in trades) - st.mean(t["move"] for t in trades)
    stops = sum(1 for t in trades if t["stopped"])
    print(f"{label}: n={n} win={100*wins/n:.0f}% | premium-vs-move edge {edge:+.0f}pts | "
          f"avg {avg:+.0f}pts/wk | total {tot:+.0f}pts (Rs{tot*lot:+,.0f}/lot) | "
          f"Sharpe {sharpe:.2f} | maxDD {mdd:.0f}pts | worst {min(pnls):.0f}pts"
          + (f" | stops {stops}" if stops else ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-vix", type=float, default=0.0, help="only sell when India VIX >= this")
    ap.add_argument("--stop-mult", type=float, default=0.0, help="stop when move >= mult x premium (0=hold to expiry)")
    ap.add_argument("--cost", type=float, default=0.005)
    ap.add_argument("--lot", type=int, default=75)
    a = ap.parse_args()
    print(f"NIFTY weekly ATM short-straddle (VIX-priced) | min_vix={a.min_vix} stop_mult={a.stop_mult} "
          f"cost={a.cost*100:.1f}% lot={a.lot}\n")
    report(backtest(a.min_vix, a.stop_mult, a.cost, a.lot), "RESULT", a.lot)


if __name__ == "__main__":
    main()
