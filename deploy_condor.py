"""deploy_condor.py — concrete monthly deployment ticket for the validated index vol-seller,
generalized across NIFTY and BANKNIFTY and any account size.

THE EDGE: VIX-gated monthly iron condor on LIQUID strikes (shorts 1.0xEM, wings 0.5xEM). Survives
realistic costs + OOS, on TWO independent liquid indices:
  * NIFTY     — backtest n=23, ~83% win, Sharpe ~1.35, +Rs90k/3yr/lot. 1.5x-credit daily stop.
  * BANKNIFTY — cross-index revalidation n=19, ~84% win, Sharpe 1.50, +Rs93k/lot. STOPLESS (the
                credit stop HURT BANKNIFTY, 1.50->1.25; its wings already cap the loss).

Per-lot defined max loss sets the minimum account size (max-loss capped at 40% of capital):
  NIFTY ~Rs18k/lot -> ~Rs45-50k min ;  BANKNIFTY ~Rs27k/lot -> ~Rs67-75k min.

    python deploy_condor.py --index NIFTY --capital 50000
    python deploy_condor.py --index BANKNIFTY --capital 75000

MONTHLY PROCESS (deterministic): refresh chain (fno_build_liquid_chains.py for NIFTY;
fno_build_index_chains.py for BANKNIFTY) ~28 days before the monthly expiry -> run this -> if VIX>=12,
place the 4 legs as LIMIT orders at live mid -> hold to expiry (NIFTY: close all if mark-to-model loss
>= 1.5x credit on a daily close; BANKNIFTY: no stop, wings cap it) -> repeat. One position per index
at a time. Never remove the wings. RISK: a bad cycle loses the full defined max (~36-40% of account).
Credit shown uses bhavcopy settle (indicative) -> place LIMIT orders; live credit may be lower.
"""
import argparse, json, os
import fno_condor_liquid as L

BODY, WING, OI_MIN, VOL_MIN = 1.0, 0.5, 500, 1
MIN_VIX = 12.0
MIN_DTE, MAX_DTE, TARGET_DTE = 20, 40, 28
MARGIN_BUFFER = 1.15        # broker SPAN+exposure ~ max loss x this for a hedged condor
MAX_MARGIN_FRAC = 0.80      # deploy at most 80% of capital as margin
MAX_LOSS_FRAC = 0.40        # cap defined max loss per cycle at 40% of capital

INDEX_CFG = {
    "NIFTY":     {"lot": 65, "chain": "chains_liq.json",           "stop": 1.5, "min_cap": 50000},
    "BANKNIFTY": {"lot": 35, "chain": "chains_liq_BANKNIFTY.json", "stop": 0.0, "min_cap": 75000},
}


def load_index(index):
    cfg = INDEX_CFG[index]
    chains = json.load(open(os.path.join(L.DATA, cfg["chain"])))
    vix = {r["date"][:10]: r["close"]
           for r in json.load(open(os.path.join(L.DATA, "INDIAVIX_day.json")))}
    return chains, vix


def build_current(index):
    chains, vix = load_index(index)
    d0 = max(chains); v0 = vix.get(d0)
    mexp = sorted(e for e in L.monthly_expiries(chains)
                  if e > d0 and MIN_DTE <= (L._d(e) - L._d(d0)).days <= MAX_DTE
                  and any(o[0][:10] == e for o in chains[d0]["opts"]))
    if not mexp:
        return d0, v0, None, None
    E = min(mexp, key=lambda e: abs((L._d(e) - L._d(d0)).days - TARGET_DTE))
    S0 = chains[d0]["spot"]
    em = L.atm_em(chains[d0]["opts"], S0, E, OI_MIN, VOL_MIN)
    if not em:
        return d0, v0, E, None
    c = L.build_condor(chains[d0]["opts"], S0, E, em, BODY, WING, OI_MIN, VOL_MIN, True)
    return d0, v0, E, (c, S0, em)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", default="NIFTY", choices=list(INDEX_CFG))
    ap.add_argument("--capital", type=float, default=50000.0)
    a = ap.parse_args()
    cfg = INDEX_CFG[a.index]; LOT = cfg["lot"]; STOP_MULT = cfg["stop"]; CAP = a.capital

    d0, v0, E, built = build_current(a.index)
    print("=" * 78)
    print(f"  Rs{CAP:,.0f} DEPLOYMENT - VIX-gated {a.index} monthly iron condor")
    print("=" * 78)
    print(f"  Entry date (latest chain): {d0}   India VIX: {v0}   Expiry: {E}")
    if built is None:
        print("  -> No tradeable monthly expiry / liquid chain. NO TRADE this run."); return
    c, S0, em = built
    dte = (L._d(E) - L._d(d0)).days
    credit = c["credit"]
    wing_w = min(c["sp"]["strike"] - c["lp"]["strike"], c["lc"]["strike"] - c["sc"]["strike"])
    max_loss_pts = wing_w - credit
    max_loss_rs = max_loss_pts * LOT
    margin_rs = max_loss_rs * MARGIN_BUFFER
    be_low = c["sp"]["strike"] - credit; be_high = c["sc"]["strike"] + credit
    print(f"  Spot {S0:.0f} | expected-move {em:.0f}pts | DTE {dte} | lot {LOT}\n")

    if v0 is None or v0 < MIN_VIX:
        print(f"  *** GATE FAILED: VIX {v0} < {MIN_VIX} -> NO TRADE. Sit in cash this cycle. ***")
        return
    print(f"  GATE PASSED (VIX {v0} >= {MIN_VIX}).\n")
    print(f"  ---- ORDER TICKET (1 lot = {LOT} qty) ----")
    print(f"    SELL  {c['sp']['strike']:.0f} PE  @ ~{c['sp']['price']:.1f}  (short put,  OI {c['sp']['oi']:.0f})")
    print(f"    SELL  {c['sc']['strike']:.0f} CE  @ ~{c['sc']['price']:.1f}  (short call, OI {c['sc']['oi']:.0f})")
    print(f"    BUY   {c['lp']['strike']:.0f} PE  @ ~{c['lp']['price']:.1f}  (long put / wing)")
    print(f"    BUY   {c['lc']['strike']:.0f} CE  @ ~{c['lc']['price']:.1f}  (long call / wing)")
    print(f"\n    Net CREDIT  : {credit:.1f} pts = Rs{credit*LOT:,.0f}/lot")
    print(f"    MAX LOSS    : {max_loss_pts:.1f} pts = Rs{max_loss_rs:,.0f}/lot (defined, wings cap it)")
    print(f"    Est. margin : ~Rs{margin_rs:,.0f}/lot")
    print(f"    Profit zone : {a.index} {be_low:.0f} - {be_high:.0f} at expiry")
    if STOP_MULT > 0:
        print(f"    Daily stop  : close all if mark-to-model loss >= {STOP_MULT}x credit "
              f"(~Rs{STOP_MULT*credit*LOT:,.0f}/lot)")
    else:
        print(f"    Daily stop  : NONE (stopless - the wings cap the loss; stop hurt {a.index} in backtest)")

    lots_by_margin = int((MAX_MARGIN_FRAC * CAP) / margin_rs) if margin_rs else 0
    lots_by_loss = int((MAX_LOSS_FRAC * CAP) / max_loss_rs) if max_loss_rs else 0
    lots = max(0, min(lots_by_margin, lots_by_loss))
    print(f"\n  ---- SIZE FOR Rs{CAP:,.0f} ----")
    print(f"    lots by margin cap ({MAX_MARGIN_FRAC:.0%}): {lots_by_margin} | "
          f"by max-loss cap ({MAX_LOSS_FRAC:.0%}): {lots_by_loss}")
    if lots:
        print(f"    >>> TRADE {lots} LOT(S) <<<")
        print(f"        margin ~Rs{margin_rs*lots:,.0f} ({margin_rs*lots/CAP:.0%}) | "
              f"max loss Rs{max_loss_rs*lots:,.0f} ({max_loss_rs*lots/CAP:.0%}) | "
              f"credit Rs{credit*LOT*lots:,.0f} (+{credit*LOT*lots/CAP:.0%} if win)")
    else:
        print(f"    >>> CAPITAL TOO SMALL for 1 {a.index} lot. Need ~Rs{cfg['min_cap']:,} "
              f"(1-lot max loss Rs{max_loss_rs:,.0f} must be <= {MAX_LOSS_FRAC:.0%} of capital). NO TRADE.")
    print("\n  NOTE: bhavcopy-settle prices (indicative). Place LIMIT orders at live mid; verify lot+margin.")


if __name__ == "__main__":
    main()
