"""fno_condor_liquid.py — REAL-PRICE NIFTY monthly iron condor, LIQUID-STRIKE revalidation.

The prior real-price sweep ([[fno-strategy]]) found a monthly condor (shorts ~1.5xEM, wings 0.5xEM)
at Sharpe ~1.37 / +Rs82.6k/3yr — but the live check showed it was partly a STALE-SETTLE artifact:
far-OTM strikes with zero OI / zero volume carry theoretical settlement prices that inflate the
sold credit. This rebuilds the backtest from chains_liq.json (settle + OI + volume per strike) and
constructs the SAME condor on the SAME monthly expiries TWO ways:

  * LIQUID   : every leg snapped to the nearest strike passing an OI/volume filter (tradeable).
  * GRID     : every leg snapped to the nearest 50-pt strike regardless of liquidity (the old
               method — can pick never-traded strikes with stale settle).

Comparing the two isolates how much of the "edge" was real vs stale-settle illusion.

    python fno_condor_liquid.py [--body 1.5] [--wing 0.5] [--oi-min 500] [--cost-leg 2]
                                [--min-dte 20] [--max-dte 40] [--target-dte 28]
"""
import argparse, json, math, os, statistics as st
from datetime import date

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "fno")


def _d(s):
    y, m, dd = s[:10].split("-")
    return date(int(y), int(m), int(dd))


def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, sigma, t, call=True):
    if t <= 0 or sigma <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (sigma * sigma / 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    if call:
        return S * _N(d1) - K * _N(d2)
    return K * _N(-d2) - S * _N(-d1)


def load():
    chains = json.load(open(os.path.join(DATA, "chains_liq.json")))
    nifty = {r["date"][:10]: r["close"]
             for r in json.load(open(os.path.join(DATA, "NIFTY50_day.json")))}
    vix = {r["date"][:10]: r["close"]
           for r in json.load(open(os.path.join(DATA, "INDIAVIX_day.json")))}
    return chains, nifty, vix


def monthly_expiries(chains):
    """All expiries that are the last expiry within their calendar month (= monthly contracts)."""
    allx = set()
    for rec in chains.values():
        for o in rec["opts"]:
            allx.add(o[0][:10])
    by_month = {}
    for x in allx:
        d = _d(x)
        key = (d.year, d.month)
        by_month[key] = max(by_month.get(key, x), x)
    return set(by_month.values())


def pick_leg(opts, expiry, otype, target, oi_min, vol_min, liquid):
    """Nearest strike to `target` for (expiry, otype); filtered to liquid strikes if `liquid`."""
    cand = [o for o in opts if o[0][:10] == expiry and o[2] == otype and o[3] > 0]
    if liquid:
        cand = [o for o in cand if o[4] >= oi_min and o[5] >= vol_min]
    if not cand:
        return None
    o = min(cand, key=lambda r: abs(r[1] - target))
    return {"strike": o[1], "price": o[3], "oi": o[4], "vol": o[5]}


def build_condor(opts, S0, expiry, em, body, wing, oi_min, vol_min, liquid):
    sp = pick_leg(opts, expiry, "PE", S0 - body * em, oi_min, vol_min, liquid)   # short put
    sc = pick_leg(opts, expiry, "CE", S0 + body * em, oi_min, vol_min, liquid)   # short call
    if not sp or not sc:
        return None
    lp = pick_leg(opts, expiry, "PE", sp["strike"] - wing * em, oi_min, vol_min, liquid)  # long put
    lc = pick_leg(opts, expiry, "CE", sc["strike"] + wing * em, oi_min, vol_min, liquid)  # long call
    if not lp or not lc:
        return None
    # wings must be strictly beyond the shorts, else it isn't a condor
    if not (lp["strike"] < sp["strike"] < sc["strike"] < lc["strike"]):
        return None
    credit = sp["price"] + sc["price"] - lp["price"] - lc["price"]
    legs = [sp, sc, lp, lc]
    return {"sp": sp, "sc": sc, "lp": lp, "lc": lc, "credit": credit,
            "min_oi": min(l["oi"] for l in legs), "zero_vol_legs": sum(1 for l in legs if l["vol"] == 0)}


def atm_em(opts, S0, expiry, oi_min, vol_min):
    """Expected move = liquid ATM straddle price for the expiry."""
    ce = pick_leg(opts, expiry, "CE", S0, oi_min, vol_min, True)
    pe = pick_leg(opts, expiry, "PE", S0, oi_min, vol_min, True)
    if not ce or not pe:
        return None
    return ce["price"] + pe["price"]


def condor_value(c, S, sigma, t):
    """Mark-to-model cost to CLOSE the short condor (buy back shorts, sell longs)."""
    return (bs(S, c["sp"]["strike"], sigma, t, call=False)
            + bs(S, c["sc"]["strike"], sigma, t, call=True)
            - bs(S, c["lp"]["strike"], sigma, t, call=False)
            - bs(S, c["lc"]["strike"], sigma, t, call=True))


def settle_pnl(c, S0, E, d0, ST, cost_leg, stop_mult, nifty, vix):
    """Return (pnl, stopped). If stop_mult>0, BS-reprice daily off VIX and exit when the
    mark-to-model loss reaches stop_mult x credit; else hold to expiry intrinsic."""
    credit = c["credit"]
    max_loss = (min(c["sp"]["strike"] - c["lp"]["strike"], c["lc"]["strike"] - c["sc"]["strike"])) - credit
    if stop_mult > 0:
        days = [d for d in sorted(nifty) if d0 < d < E]
        for t in days:
            S = nifty[t]; sig = vix.get(t, vix.get(d0, 12.0)) / 100.0
            trem = max(1, (_d(E) - _d(t)).days) / 365.0
            V = condor_value(c, S, sig, trem)
            if (V - credit) >= stop_mult * credit:        # loss hit the stop
                loss = min(V - credit, max_loss)           # capped by structure
                return -loss - cost_leg * 4, True
    payoff = (credit
              - max(0.0, c["sp"]["strike"] - ST) + max(0.0, c["lp"]["strike"] - ST)
              - max(0.0, ST - c["sc"]["strike"]) + max(0.0, ST - c["lc"]["strike"]))
    return payoff - cost_leg * 4, False


def run(body, wing, oi_min, vol_min, cost_leg, min_dte, max_dte, target_dte, lot,
        min_vix=0.0, max_vix=999.0, stop_mult=0.0):
    chains, nifty, vix = load()
    mexp = monthly_expiries(chains)
    cdates = sorted(chains)
    results = {"LIQUID": [], "GRID": []}
    rows = []

    for E in sorted(mexp):
        if E not in nifty:                       # need expiry-day spot to settle
            continue
        ST = nifty[E]
        best = None
        for d0 in cdates:
            if d0 >= E:
                continue
            dte = (_d(E) - _d(d0)).days
            if not (min_dte <= dte <= max_dte):
                continue
            rec = chains[d0]
            if not any(o[0][:10] == E for o in rec["opts"]):
                continue
            if best is None or abs(dte - target_dte) < abs(best[1] - target_dte):
                best = (d0, dte)
        if not best:
            continue
        d0, dte = best
        v0 = vix.get(d0)
        if v0 is None or not (min_vix <= v0 <= max_vix):     # VIX regime gate
            continue
        rec = chains[d0]; S0 = rec["spot"]
        if not S0:
            continue
        em = atm_em(rec["opts"], S0, E, oi_min, vol_min)
        if not em:
            continue
        for mode, liquid in (("LIQUID", True), ("GRID", False)):
            c = build_condor(rec["opts"], S0, E, em, body, wing, oi_min, vol_min, liquid)
            if not c:
                continue
            pnl, stopped = settle_pnl(c, S0, E, d0, ST, cost_leg, stop_mult, nifty, vix)
            results[mode].append({"d0": d0, "E": E, "pnl": pnl, "credit": c["credit"],
                                  "vix": v0, "stopped": stopped,
                                  "min_oi": c["min_oi"], "zvl": c["zero_vol_legs"]})
    return results, rows


def report(trades, label, lot, cost_leg):
    n = len(trades)
    if not n:
        print(f"{label}: no trades"); return
    pnls = [t["pnl"] for t in trades]
    wins = sum(1 for p in pnls if p > 0)
    tot = sum(pnls); avg = tot / n
    sd = st.pstdev(pnls); sharpe = avg / sd * (12 ** 0.5) if sd else 0   # monthly -> annualize x sqrt12
    eq = peak = mdd = 0
    for p in pnls:
        eq += p; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    avgcred = st.mean(t["credit"] for t in trades)
    stopped = sum(1 for t in trades if t.get("stopped"))
    avgvix = st.mean(t.get("vix", 0) for t in trades)
    print(f"{label}: n={n} win={100*wins/n:.0f}% | avg credit {avgcred:.0f}pts | avgVIX {avgvix:.1f} | "
          f"avg {avg:+.0f}pts/mo | total {tot:+.0f}pts (Rs{tot*lot:+,.0f}/lot) | "
          f"Sharpe {sharpe:.2f} | maxDD {mdd:.0f} | worst {min(pnls):.0f} | stopped {stopped}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--body", type=float, default=1.5)
    ap.add_argument("--wing", type=float, default=0.5)
    ap.add_argument("--oi-min", type=float, default=500)
    ap.add_argument("--vol-min", type=float, default=1)
    ap.add_argument("--cost-leg", type=float, default=2.0, help="cost per leg in points (x4)")
    ap.add_argument("--min-dte", type=int, default=20)
    ap.add_argument("--max-dte", type=int, default=40)
    ap.add_argument("--target-dte", type=int, default=28)
    ap.add_argument("--lot", type=int, default=75)
    ap.add_argument("--min-vix", type=float, default=0.0, help="enter only if entry-day VIX >= this")
    ap.add_argument("--max-vix", type=float, default=999.0, help="enter only if entry-day VIX <= this")
    ap.add_argument("--stop-mult", type=float, default=0.0,
                    help="stop-loss at this x credit (BS-repriced daily off VIX); 0 = no stop")
    a = ap.parse_args()
    print(f"NIFTY MONTHLY iron condor, REAL prices | body {a.body}EM wing {a.wing}EM | "
          f"OI>={a.oi_min:.0f} vol>={a.vol_min:.0f} | cost {a.cost_leg}pts/leg | "
          f"DTE {a.min_dte}-{a.max_dte} | VIX [{a.min_vix},{a.max_vix}] | stop {a.stop_mult}xcredit | lot {a.lot}\n")
    results, _ = run(a.body, a.wing, a.oi_min, a.vol_min, a.cost_leg,
                     a.min_dte, a.max_dte, a.target_dte, a.lot,
                     a.min_vix, a.max_vix, a.stop_mult)
    report(results["LIQUID"], "LIQUID", a.lot, a.cost_leg)


if __name__ == "__main__":
    main()
