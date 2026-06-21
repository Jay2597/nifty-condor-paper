"""fno_calendar.py — NIFTY calendar (horizontal) spread test, REAL prices + OI/vol filter.

A DIFFERENT vol exposure than the condor: instead of selling the level of vol, a calendar trades
the TERM STRUCTURE + theta differential. Long calendar = SELL near-monthly ATM option + BUY
far-monthly ATM option (same strike). It profits when the underlying stays near the strike (near
decays faster than far) and/or vol rises (long net vega); it loses on a big move.

Construction from chains_liq.json (settle + OI + vol): for each near monthly expiry, enter ~15 DTE
on a real chain date, pick the ATM strike liquid in BOTH the near and the next (far) monthly, price
both legs at real settle. At near expiry: near settles at intrinsic; far is BS-repriced off India
VIX (sigma=VIX, T=far remaining) — model-based, the one approximation.

    python fno_calendar.py [--type call|straddle] [--min-vix 0] [--max-vix 999]
                           [--target-dte 15] [--cost-leg 2] [--oi-min 500]
"""
import argparse, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fno_condor_liquid import load, monthly_expiries, pick_leg, bs, _d

LOT = 65


def run(kind, min_vix, max_vix, target_dte, cost_leg, oi_min, vol_min):
    chains, nifty, vix = load()
    mexp = sorted(monthly_expiries(chains))
    cdates = sorted(chains)
    trades = []

    for i, Enear in enumerate(mexp):
        if Enear not in nifty or Enear not in vix:
            continue
        fars = [e for e in mexp if e > Enear]
        if not fars:
            continue
        Efar = fars[0]
        # entry chain date: DTE-to-near closest to target, in [8,30], with both expiries listed
        best = None
        for d0 in cdates:
            if d0 >= Enear:
                continue
            dte = (_d(Enear) - _d(d0)).days
            if not (8 <= dte <= 30):
                continue
            opts = chains[d0]["opts"]
            if not (any(o[0][:10] == Enear for o in opts) and any(o[0][:10] == Efar for o in opts)):
                continue
            if best is None or abs(dte - target_dte) < abs(best[1] - target_dte):
                best = (d0, dte)
        if not best:
            continue
        d0, dte = best
        v0 = vix.get(d0)
        if v0 is None or not (min_vix <= v0 <= max_vix):
            continue
        S0 = chains[d0]["spot"]; opts = chains[d0]["opts"]
        if not S0:
            continue
        ST = nifty[Enear]
        sig_n = vix[Enear] / 100.0
        Trem = max(1, (_d(Efar) - _d(Enear)).days) / 365.0
        legs = ["CE", "PE"] if kind == "straddle" else ["CE"]
        pnl, ok, nlegs = 0.0, True, 0
        for ot in legs:
            near = pick_leg(opts, Enear, ot, S0, oi_min, vol_min, True)
            far = pick_leg(opts, Efar, ot, S0, oi_min, vol_min, True)
            if not near or not far:
                ok = False; break
            K = near["strike"]
            far2 = pick_leg(opts, Efar, ot, K, oi_min, vol_min, True)   # match strike
            if not far2 or far2["strike"] != K:
                ok = False; break
            far_val = bs(ST, K, sig_n, Trem, call=(ot == "CE"))
            intrinsic = max(0.0, (ST - K) if ot == "CE" else (K - ST))
            pnl += (near["price"] - far2["price"]) + far_val - intrinsic
            nlegs += 3   # entry sell + entry buy + far exit (near settles at exchange)
        if not ok:
            continue
        pnl -= cost_leg * nlegs
        trades.append({"d0": d0, "Enear": Enear, "Efar": Efar, "vix": v0, "pnl": pnl, "S0": S0, "ST": ST})
    return trades


def report(trades, label):
    n = len(trades)
    if not n:
        print(f"{label}: no trades"); return
    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    tot = sum(pnls); avg = tot / n
    sd = st.pstdev(pnls); sharpe = avg / sd * (12 ** 0.5) if sd else 0
    eq = peak = mdd = 0
    for p in pnls:
        eq += p; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    print(f"{label}: n={n} win={100*wins/n:.0f}% | avgVIX {st.mean(t['vix'] for t in trades):.1f} | "
          f"avg {avg:+.0f}pts/mo | total {tot:+.0f}pts (Rs{tot*LOT:+,.0f}/lot) | Sharpe {sharpe:.2f} | "
          f"maxDD {mdd:.0f} | worst {min(pnls):.0f} | best {max(pnls):.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--type", choices=["call", "straddle"], default="call")
    ap.add_argument("--min-vix", type=float, default=0.0)
    ap.add_argument("--max-vix", type=float, default=999.0)
    ap.add_argument("--target-dte", type=int, default=15)
    ap.add_argument("--cost-leg", type=float, default=2.0)
    ap.add_argument("--oi-min", type=float, default=500)
    ap.add_argument("--vol-min", type=float, default=1)
    a = ap.parse_args()
    print(f"NIFTY {a.type.upper()} CALENDAR (sell near-monthly ATM, buy far-monthly ATM) | "
          f"VIX [{a.min_vix},{a.max_vix}] | target {a.target_dte} DTE | cost {a.cost_leg}pts/leg\n")
    t = run(a.type, a.min_vix, a.max_vix, a.target_dte, a.cost_leg, a.oi_min, a.vol_min)
    report(t, f"{a.type.upper()} CALENDAR")


if __name__ == "__main__":
    main()
