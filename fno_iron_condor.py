"""fno_iron_condor.py — F&O strategy #1b: NIFTY weekly IRON CONDOR (defined-risk short vol).

Defined-risk version of the short-straddle vol-risk-premium trade ([[fno-strategy]]):
  SELL OTM put (Kps) + SELL OTM call (Kcs)   -> collect premium (the vol risk premium)
  BUY  far-OTM put (Kpb) + BUY far-OTM call (Kcb) -> protective wings that CAP the loss
Max profit = net credit (NIFTY expires between the short strikes); Max loss = wing width - credit.

MODEL (same basis as fno_straddle): weekly cycle, all legs Black-Scholes priced off India VIX as
IV (r=0, T=7/365), strikes set in expected-move units (EM = S0*sigma*sqrt(T)) and rounded to the
50-pt NIFTY grid, held to weekly expiry, settled at intrinsic. Inputs: data/fno/ daily NIFTY+VIX.
Not a live-fill sim; margin not modeled. Lot default 75.

    python fno_iron_condor.py [--min-vix 14] [--body 1.0] [--wing 1.0] [--cost-leg 1.5] [--lot 75]
      body = short-strike distance from spot in EM units; wing = extra distance to long strikes.
"""
from __future__ import annotations
import argparse, json, math, os, statistics as st

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fno")
T = 7 / 365
STEP = 5


def _n(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, sigma, t=T, call=True):
    if t <= 0 or sigma <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (sigma * sigma / 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if call:
        return S * _n(d1) - K * _n(d2)
    return K * _n(-d2) - S * _n(-d1)


def load(name):
    return {r["date"]: r for r in json.load(open(os.path.join(DATA, f"{name}_day.json")))}


def r50(x):
    return round(x / 50.0) * 50.0


def backtest(min_vix=0.0, body=1.0, wing=1.0, cost_leg=1.5, lot=75):
    N, V = load("NIFTY50"), load("INDIAVIX")
    days = sorted(set(N) & set(V))
    trades = []
    for i in range(0, len(days) - STEP, STEP):
        d0 = days[i]; S0 = N[d0]["close"]; vix = V[d0]["close"]
        if vix < min_vix:
            continue
        sigma = vix / 100.0
        em = S0 * sigma * math.sqrt(T)
        bpts = max(50.0, r50(body * em)); wpts = max(50.0, r50(wing * em))
        Kps, Kcs = S0 - bpts, S0 + bpts          # short put / short call
        Kpb, Kcb = Kps - wpts, Kcs + wpts        # long wings
        credit = (bs(S0, Kps, sigma, call=False) + bs(S0, Kcs, sigma, call=True)
                  - bs(S0, Kpb, sigma, call=False) - bs(S0, Kcb, sigma, call=True))
        max_loss = wpts - credit                  # defined risk
        ST = N[days[i + STEP]]["close"]
        payoff = (credit
                  - max(0.0, Kps - ST) + max(0.0, Kpb - ST)     # put spread
                  - max(0.0, ST - Kcs) + max(0.0, ST - Kcb))    # call spread
        pnl = payoff - cost_leg * 4               # 4 legs
        trades.append(dict(d0=d0, vix=vix, credit=credit, max_loss=max_loss, pnl=pnl,
                           atmax=(payoff <= -max_loss + 1)))
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
    avgcred = st.mean(t["credit"] for t in trades); avgcap = st.mean(t["max_loss"] for t in trades)
    atmax = sum(1 for t in trades if t["atmax"])
    print(f"{label}: n={n} win={100*wins/n:.0f}% | avg credit {avgcred:.0f}pts cap {avgcap:.0f}pts | "
          f"avg {avg:+.0f}pts/wk | total {tot:+.0f}pts (Rs{tot*lot:+,.0f}/lot) | Sharpe {sharpe:.2f} | "
          f"maxDD {mdd:.0f}pts | worst {min(pnls):.0f}pts | maxloss-weeks {atmax}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-vix", type=float, default=0.0)
    ap.add_argument("--body", type=float, default=1.0, help="short-strike distance in expected-move units")
    ap.add_argument("--wing", type=float, default=1.0, help="wing distance in expected-move units")
    ap.add_argument("--cost-leg", type=float, default=1.5, help="cost per leg in points (x4 legs)")
    ap.add_argument("--lot", type=int, default=75)
    a = ap.parse_args()
    print(f"NIFTY weekly IRON CONDOR (VIX-priced) | min_vix={a.min_vix} body={a.body}EM wing={a.wing}EM "
          f"cost/leg={a.cost_leg}pts lot={a.lot}\n")
    report(backtest(a.min_vix, a.body, a.wing, a.cost_leg, a.lot), "RESULT", a.lot)


if __name__ == "__main__":
    main()
