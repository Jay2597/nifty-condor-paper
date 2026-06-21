"""fno_backtest_blotter.py — trade-by-trade historical backtest of the VIX-gated vol-sellers.

Replays every past monthly cycle in chains_liq.json (2023-07..2026-06) that the strategy WOULD have
taken (India VIX >= 12 at entry) and records the actual outcome of BOTH structures on real liquid
prices: the iron condor (defined, no stop) and the short strangle (naked, 2x-credit daily-BS stop).
Emits a full blotter + per-strategy P&L summary, and writes results/fno_backtest_{condor,strangle}.csv.

    python fno_backtest_blotter.py [--min-vix 12] [--cost-leg 2] [--lot 65]
"""
import argparse, csv, math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fno_condor_liquid import (load, monthly_expiries, build_condor, atm_em, _d, settle_pnl)
import fno_strangle as strangle

OI_MIN, VOL_MIN = 500, 1
BODY, WING = 1.0, 0.5


def run(min_vix, cost_leg, lot, target_dte=28, min_dte=20, max_dte=40):
    chains, nifty, vix = load()
    mexp = sorted(monthly_expiries(chains)); cdates = sorted(chains)
    blotter = {"condor": [], "strangle": []}
    for E in mexp:
        if E not in nifty:
            continue
        ST = nifty[E]; best = None
        for d0 in cdates:
            if d0 >= E:
                continue
            dte = (_d(E) - _d(d0)).days
            if not (min_dte <= dte <= max_dte):
                continue
            if not any(o[0][:10] == E for o in chains[d0]["opts"]):
                continue
            if best is None or abs(dte - target_dte) < abs(best[1] - target_dte):
                best = (d0, dte)
        if not best:
            continue
        d0, dte = best; v0 = vix.get(d0)
        if v0 is None or v0 < min_vix:
            continue
        S0 = chains[d0]["spot"]
        em = atm_em(chains[d0]["opts"], S0, E, OI_MIN, VOL_MIN)
        if not S0 or not em:
            continue
        # condor (no stop)
        c = build_condor(chains[d0]["opts"], S0, E, em, BODY, WING, OI_MIN, VOL_MIN, True)
        if c:
            pnl, _ = settle_pnl(c, S0, E, d0, ST, cost_leg, 0.0, nifty, vix)
            blotter["condor"].append(dict(entry=d0, expiry=E, dte=dte, vix=round(v0, 1),
                spot=round(S0), sp=c["sp"]["strike"], sc=c["sc"]["strike"], lp=c["lp"]["strike"],
                lc=c["lc"]["strike"], credit=round(c["credit"], 1), exp_spot=round(ST),
                result="WIN" if c["sp"]["strike"] <= ST <= c["sc"]["strike"] else "BREACH",
                pnl_pts=round(pnl, 1), pnl_inr=round(pnl * lot)))
        # strangle (2x stop)
        s = strangle.build(chains[d0]["opts"], S0, E, em, BODY, OI_MIN, VOL_MIN)
        if s:
            pnl, stopped = strangle.settle(s, E, d0, ST, cost_leg, 2.0, nifty, vix)
            blotter["strangle"].append(dict(entry=d0, expiry=E, dte=dte, vix=round(v0, 1),
                spot=round(S0), sp=s["sp"]["strike"], sc=s["sc"]["strike"], lp="", lc="",
                credit=round(s["credit"], 1), exp_spot=round(ST),
                result="STOP" if stopped else ("WIN" if pnl > 0 else "LOSS"),
                pnl_pts=round(pnl, 1), pnl_inr=round(pnl * lot)))
    return blotter


def summarize(rows, lot, label):
    n = len(rows)
    pnls = [r["pnl_inr"] for r in rows]
    wins = sum(1 for r in rows if r["pnl_inr"] > 0)
    tot = sum(pnls); mean = tot / n; sd = st.pstdev(pnls)
    sharpe = mean / sd * math.sqrt(12) if sd else 0
    eq = peak = mdd = 0
    for p in pnls:
        eq += p; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    print(f"\n{label}: n={n} | win {100*wins/n:.0f}% | total Rs{tot:+,}/lot | avg Rs{mean:+,.0f} | "
          f"Sharpe {sharpe:.2f} | maxDD Rs{mdd:,.0f} | worst Rs{min(pnls):+,}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-vix", type=float, default=12.0)
    ap.add_argument("--cost-leg", type=float, default=2.0)
    ap.add_argument("--lot", type=int, default=65)
    a = ap.parse_args()
    bl = run(a.min_vix, a.cost_leg, a.lot)
    here = os.path.dirname(os.path.abspath(__file__))
    for kind, rows in bl.items():
        cols = list(rows[0].keys())
        path = os.path.join(here, "results", f"fno_backtest_{kind}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
        print(f"\n========== {kind.upper()} — past trades (VIX>={a.min_vix}) ==========")
        print(f"{'entry':11}{'expiry':11}{'vix':>5}{'spot':>7}{'shorts':>14}{'cred':>7}"
              f"{'expSpot':>8}{'res':>7}{'pnlRs':>9}")
        for r in rows:
            print(f"{r['entry']:11}{r['expiry']:11}{r['vix']:>5}{r['spot']:>7}"
                  f"{str(int(r['sp']))+'/'+str(int(r['sc'])):>14}{r['credit']:>7}{r['exp_spot']:>8}"
                  f"{r['result']:>7}{r['pnl_inr']:>9,}")
        summarize(rows, a.lot, f"{kind.upper()} SUMMARY")
    print(f"\nCSVs -> results/fno_backtest_condor.csv, results/fno_backtest_strangle.csv")


if __name__ == "__main__":
    main()
