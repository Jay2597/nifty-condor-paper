"""fno_strangle.py — VIX-gated NIFTY monthly SHORT STRANGLE, real liquid prices.

Same vol-selling edge as the condor but WITHOUT long wings -> ~2-3x the premium, at the cost of
undefined tail risk, so a stop is essential. SELL OTM put + OTM call at ~body*EM, enter only when
India VIX >= gate, manage with a daily-BS-repriced stop (exit when mark-to-model loss reaches
stop_mult x credit). Settles to intrinsic at expiry otherwise. Emits a per-trade list for combining
with other strategies.

    python fno_strangle.py [--body 1.0] [--min-vix 12] [--stop-mult 2.0] [--cost-leg 2] [--lot 65]
"""
import argparse, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fno_condor_liquid import load, monthly_expiries, pick_leg, atm_em, bs, _d


def build(opts, S0, E, em, body, oi_min, vol_min):
    sp = pick_leg(opts, E, "PE", S0 - body * em, oi_min, vol_min, True)
    sc = pick_leg(opts, E, "CE", S0 + body * em, oi_min, vol_min, True)
    if not sp or not sc or not (sp["strike"] < sc["strike"]):
        return None
    return {"sp": sp, "sc": sc, "credit": sp["price"] + sc["price"]}


def settle(c, E, d0, ST, cost_leg, stop_mult, nifty, vix):
    cr = c["credit"]; Kp, Kc = c["sp"]["strike"], c["sc"]["strike"]
    if stop_mult > 0:
        for t in (d for d in sorted(nifty) if d0 < d < E):
            S = nifty[t]; sig = vix.get(t, vix.get(d0, 12.0)) / 100.0
            trem = max(1, (_d(E) - _d(t)).days) / 365.0
            V = bs(S, Kp, sig, trem, call=False) + bs(S, Kc, sig, trem, call=True)
            if (V - cr) >= stop_mult * cr:
                return -(V - cr) - cost_leg * 2, True
    payoff = cr - max(0.0, Kp - ST) - max(0.0, ST - Kc)
    return payoff - cost_leg * 2, False


def run(body, min_vix, max_vix, stop_mult, cost_leg, oi_min, vol_min, target_dte=28,
        min_dte=20, max_dte=40):
    chains, nifty, vix = load()
    mexp = sorted(monthly_expiries(chains)); cdates = sorted(chains)
    trades = []
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
        d0, _ = best; v0 = vix.get(d0)
        if v0 is None or not (min_vix <= v0 <= max_vix):
            continue
        S0 = chains[d0]["spot"]
        em = atm_em(chains[d0]["opts"], S0, E, oi_min, vol_min)
        if not S0 or not em:
            continue
        c = build(chains[d0]["opts"], S0, E, em, body, oi_min, vol_min)
        if not c:
            continue
        pnl, stopped = settle(c, E, d0, ST, cost_leg, stop_mult, nifty, vix)
        trades.append({"d0": d0, "E": E, "vix": v0, "pnl": pnl, "credit": c["credit"], "stopped": stopped})
    return trades


def stats(trades, lot, label=""):
    n = len(trades)
    if not n:
        print(f"{label}: no trades"); return None
    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    tot = sum(pnls); avg = tot / n; sd = st.pstdev(pnls)
    sharpe = avg / sd * (12 ** 0.5) if sd else 0
    eq = peak = mdd = 0
    for p in pnls:
        eq += p; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    stp = sum(1 for t in trades if t["stopped"])
    print(f"{label}: n={n} win={100*wins/n:.0f}% | avgVIX {st.mean(t['vix'] for t in trades):.1f} | "
          f"avg credit {st.mean(t['credit'] for t in trades):.0f} | avg {avg:+.0f}pts | "
          f"total {tot:+.0f}pts (Rs{tot*lot:+,.0f}/lot) | Sharpe {sharpe:.2f} | maxDD {mdd:.0f} | "
          f"worst {min(pnls):.0f} | stopped {stp}")
    return dict(n=n, sharpe=round(sharpe, 2), total_inr=round(tot * lot), worst=round(min(pnls)),
                win=round(100 * wins / n), maxdd=round(mdd))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", type=float, default=1.0)
    ap.add_argument("--min-vix", type=float, default=12.0)
    ap.add_argument("--max-vix", type=float, default=999.0)
    ap.add_argument("--stop-mult", type=float, default=2.0)
    ap.add_argument("--cost-leg", type=float, default=2.0)
    ap.add_argument("--oi-min", type=float, default=500)
    ap.add_argument("--vol-min", type=float, default=1)
    ap.add_argument("--lot", type=int, default=65)
    a = ap.parse_args()
    print(f"NIFTY MONTHLY SHORT STRANGLE | body {a.body}EM | VIX>={a.min_vix} | "
          f"stop {a.stop_mult}xcredit | cost {a.cost_leg}pts/leg | lot {a.lot}\n")
    t = run(a.body, a.min_vix, a.max_vix, a.stop_mult, a.cost_leg, a.oi_min, a.vol_min)
    stats(t, a.lot, "STRANGLE")


if __name__ == "__main__":
    main()
