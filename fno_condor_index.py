"""fno_condor_index.py — revalidate the rescued NIFTY vol-seller on OTHER indices at REAL prices.

The rescued NIFTY candidate ([[fno-strategy]]) = monthly iron condor, shorts ~1.0xEM / wings 0.5xEM,
entered only when India VIX >= ~12, optional credit-multiple stop, on LIQUID (OI/vol-filtered) strikes.
This asks: is that edge NIFTY-specific, or does it generalize to BANKNIFTY / FINNIFTY / MIDCPNIFTY?

Reuses fno_condor_liquid's option machinery; only the data plumbing is parametrized per index:
  * chain      = data/fno/chains_liq_<SYM>.json (settle+OI+vol, built by fno_build_index_chains.py)
  * settle spot= a daily index close series (BANKNIFTY_day.json; FINNIFTY/MIDCPNIFTY via --spot-json)
  * VIX gate   = raw India VIX level (regime proxy; no per-index vol index exists)
  * stop sigma = India VIX x --vol-scale (BANKNIFTY ~1.22 realized-vol ratio vs NIFTY)

    python fno_condor_index.py --sym BANKNIFTY --body 1.0 --wing 0.5 --min-vix 12 --stop-mult 1.5 --lot 35
"""
import argparse, json, os
import fno_condor_liquid as L

DATA = L.DATA


def load_index(sym, spot_json):
    chains = json.load(open(os.path.join(DATA, f"chains_liq_{sym}.json")))
    spot = {r["date"][:10]: r["close"] for r in json.load(open(os.path.join(DATA, spot_json)))}
    vix = {r["date"][:10]: r["close"]
           for r in json.load(open(os.path.join(DATA, "INDIAVIX_day.json")))}
    return chains, spot, vix


def run(sym, spot_json, body, wing, oi_min, vol_min, cost_leg, min_dte, max_dte, target_dte,
        min_vix, max_vix, stop_mult, vol_scale):
    chains, spot, vix = load_index(sym, spot_json)
    svix = {d: v * vol_scale for d, v in vix.items()}   # index sigma for the stop reprice
    mexp = L.monthly_expiries(chains)
    cdates = sorted(chains)
    trades = []
    for E in sorted(mexp):
        if E not in spot:                       # need expiry-day index close to settle
            continue
        ST = spot[E]
        best = None
        for d0 in cdates:
            if d0 >= E:
                continue
            dte = (L._d(E) - L._d(d0)).days
            if not (min_dte <= dte <= max_dte):
                continue
            if not any(o[0][:10] == E for o in chains[d0]["opts"]):
                continue
            if best is None or abs(dte - target_dte) < abs(best[1] - target_dte):
                best = (d0, dte)
        if not best:
            continue
        d0, dte = best
        v0 = vix.get(d0)
        if v0 is None or not (min_vix <= v0 <= max_vix):     # gate on RAW India VIX
            continue
        rec = chains[d0]; S0 = rec["spot"]
        if not S0:
            continue
        em = L.atm_em(rec["opts"], S0, E, oi_min, vol_min)
        if not em:
            continue
        c = L.build_condor(rec["opts"], S0, E, em, body, wing, oi_min, vol_min, True)
        if not c:
            continue
        # settle: stop reprices off scaled-VIX sigma, expiry payoff off index close
        pnl, stopped = L.settle_pnl(c, S0, E, d0, ST, cost_leg, stop_mult, spot, svix)
        trades.append({"d0": d0, "E": E, "pnl": pnl, "credit": c["credit"], "vix": v0,
                       "stopped": stopped, "min_oi": c["min_oi"], "zvl": c["zero_vol_legs"]})
    return trades


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sym", default="BANKNIFTY", choices=["BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"])
    ap.add_argument("--spot-json", default=None, help="daily close JSON for settle (default <SYM>_day.json)")
    ap.add_argument("--body", type=float, default=1.0)
    ap.add_argument("--wing", type=float, default=0.5)
    ap.add_argument("--oi-min", type=float, default=500)
    ap.add_argument("--vol-min", type=float, default=1)
    ap.add_argument("--cost-leg", type=float, default=2.0)
    ap.add_argument("--min-dte", type=int, default=20)
    ap.add_argument("--max-dte", type=int, default=40)
    ap.add_argument("--target-dte", type=int, default=28)
    ap.add_argument("--lot", type=int, default=35)
    ap.add_argument("--min-vix", type=float, default=0.0)
    ap.add_argument("--max-vix", type=float, default=999.0)
    ap.add_argument("--stop-mult", type=float, default=0.0)
    ap.add_argument("--vol-scale", type=float, default=1.22, help="index sigma = India VIX x this (stop)")
    a = ap.parse_args()
    spot_json = a.spot_json or f"{a.sym}_day.json"
    print(f"{a.sym} MONTHLY iron condor, REAL liquid strikes | body {a.body}EM wing {a.wing}EM | "
          f"cost {a.cost_leg}pts/leg | DTE {a.min_dte}-{a.max_dte} | VIX [{a.min_vix},{a.max_vix}] | "
          f"stop {a.stop_mult}xcredit (sigma=VIXx{a.vol_scale}) | lot {a.lot}\n")
    trades = run(a.sym, spot_json, a.body, a.wing, a.oi_min, a.vol_min, a.cost_leg,
                 a.min_dte, a.max_dte, a.target_dte, a.min_vix, a.max_vix, a.stop_mult, a.vol_scale)
    L.report(trades, f"{a.sym} LIQUID", a.lot, a.cost_leg)


if __name__ == "__main__":
    main()
