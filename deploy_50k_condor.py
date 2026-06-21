"""deploy_50k_condor.py — concrete Rs50,000 deployment plan for the validated F&O edge.

THE EDGE (the only equity/index strategy in this project that survives realistic costs out-of-sample):
the VIX-gated monthly NIFTY iron condor on LIQUID strikes. Backtest (real bhavcopy, liquid-strike,
n=23, VIX>=12): ~83% win, Sharpe ~1.35, +Rs90k/3yr/lot, worst month -251pts. Generalizes to BANKNIFTY
(Sharpe 1.50). This file turns that into an exact, zero-interpretation monthly order ticket for a
Rs50,000 account — sizing, strikes, margin check, max loss, breakevens, and the management rules.

WHY NIFTY (not BANKNIFTY) FOR Rs50k: defined-risk max loss per lot must fit the account with a buffer.
NIFTY condor max loss ~Rs18k/lot (~36% of 50k); BANKNIFTY ~Rs27k/lot (~54%) = too concentrated. So
Rs50k = exactly ONE NIFTY condor lot.

================================ THE MONTHLY PROCESS (deterministic) ================================
Run ONCE per monthly cycle, ~28 days before the monthly expiry (the last weekly expiry of the month):
 1. Refresh the chain: python fno_build_liquid_chains.py   (pulls latest bhavcopy -> chains_liq.json)
 2. python deploy_50k_condor.py                            (prints the exact ticket, or "NO TRADE")
 3. GATE: trade ONLY if India VIX >= 12 on entry day. If VIX < 12 -> NO TRADE, sit in cash this cycle.
 4. Place the 4 legs as the ticket states (sell 2, buy 2). Use LIMIT orders at/inside the mid.
 5. Set a GTT / alert at the daily-close credit-stop level (1.5x credit). Hold to expiry otherwise.
 6. At expiry: let it settle (defined-risk; wings cap the loss). Repeat next cycle.

MANAGEMENT (no discretion):
 - Profit: hold to expiry. (Optional: book at 50% of max profit if you want to free margin early.)
 - Stop: if the position's mark-to-model loss hits 1.5x the credit on any daily close, close all 4 legs.
 - Never roll a tested side for a debit. Never remove the wings (they are the account's protection).
 - One position at a time. No adding on red days. No naked legs, ever.

RISK DISCLOSURE: a single bad cycle can lose the full defined max (~36% of the account). The edge is
~83% win historically, but n is small and this is ONE concentrated position. Only deploy capital you
can see draw down 36% in a month. This is paper-validated, not a guarantee.
====================================================================================================
"""
import fno_condor_liquid as L

CAPITAL = 50000.0
LOT = 65                  # NIFTY lot size (verify with broker each cycle; has changed historically)
BODY, WING = 1.0, 0.5     # shorts 1.0xEM, wings 0.5xEM (the rescued VIX-gated config)
OI_MIN, VOL_MIN = 500, 1
MIN_VIX = 12.0
MIN_DTE, MAX_DTE, TARGET_DTE = 20, 40, 28
STOP_MULT = 1.5           # 1.5x-credit daily-close stop (stop-sweep optimum for the condor)
MARGIN_PER_LOT_EST = None # estimated below from max loss (defined-risk margin ~= max loss + buffer)
MARGIN_BUFFER = 1.15      # broker SPAN+exposure ~ max loss x this for a hedged condor
MAX_MARGIN_FRAC = 0.80    # deploy at most 80% of capital as margin (keep cash buffer)
MAX_LOSS_FRAC = 0.40      # cap defined max loss per cycle at 40% of capital


def build_current():
    chains, nifty, vix = L.load()
    d0 = max(chains)
    v0 = vix.get(d0)
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
    d0, v0, E, built = build_current()
    print("=" * 78)
    print(f"  Rs{CAPITAL:,.0f} DEPLOYMENT - VIX-gated NIFTY monthly iron condor")
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
    be_low = c["sp"]["strike"] - credit
    be_high = c["sc"]["strike"] + credit

    print(f"  Spot {S0:.0f} | expected-move {em:.0f}pts | DTE {dte}\n")

    # ---- VIX gate ----
    if v0 is None or v0 < MIN_VIX:
        print(f"  *** GATE FAILED: VIX {v0} < {MIN_VIX} -> NO TRADE. Sit in cash this cycle. ***")
        print(f"  (For reference the structure would have been credit {credit:.0f}pts.)")
        return

    # ---- sizing for Rs50k ----
    lots_by_margin = int((MAX_MARGIN_FRAC * CAPITAL) / margin_rs) if margin_rs else 0
    lots_by_loss = int((MAX_LOSS_FRAC * CAPITAL) / max_loss_rs) if max_loss_rs else 0
    lots = max(0, min(lots_by_margin, lots_by_loss))
    print(f"  GATE PASSED (VIX {v0} >= {MIN_VIX}).\n")
    print("  ---- ORDER TICKET (1 lot = {} qty) ----".format(LOT))
    print(f"    SELL  {c['sp']['strike']:.0f} PE   @ ~{c['sp']['price']:.1f}   (short put,  OI {c['sp']['oi']:.0f})")
    print(f"    SELL  {c['sc']['strike']:.0f} CE   @ ~{c['sc']['price']:.1f}   (short call, OI {c['sc']['oi']:.0f})")
    print(f"    BUY   {c['lp']['strike']:.0f} PE   @ ~{c['lp']['price']:.1f}   (long put / wing)")
    print(f"    BUY   {c['lc']['strike']:.0f} CE   @ ~{c['lc']['price']:.1f}   (long call / wing)")
    print(f"\n    Net CREDIT     : {credit:.1f} pts  = Rs{credit*LOT:,.0f} / lot received")
    print(f"    Wing width     : {wing_w:.0f} pts")
    print(f"    MAX LOSS       : {max_loss_pts:.1f} pts = Rs{max_loss_rs:,.0f} / lot (defined, wings cap it)")
    print(f"    Est. margin    : ~Rs{margin_rs:,.0f} / lot (SPAN+exposure ~ max loss x {MARGIN_BUFFER})")
    print(f"    Profit zone    : NIFTY {be_low:.0f} - {be_high:.0f} at expiry (breakevens)")
    print(f"    Daily stop     : close all if mark-to-model loss >= {STOP_MULT}x credit "
          f"(~Rs{STOP_MULT*credit*LOT:,.0f}/lot)")
    print(f"\n  ---- SIZE FOR Rs{CAPITAL:,.0f} ----")
    print(f"    lots by margin cap ({MAX_MARGIN_FRAC:.0%} of capital): {lots_by_margin}")
    print(f"    lots by max-loss cap ({MAX_LOSS_FRAC:.0%} of capital): {lots_by_loss}")
    print(f"    >>> TRADE {lots} LOT(S)" + (" <<<" if lots else "  -> capital too small even for 1 lot"))
    if lots:
        print(f"        margin used   : ~Rs{margin_rs*lots:,.0f}  ({margin_rs*lots/CAPITAL:.0%} of capital)")
        print(f"        max loss      : Rs{max_loss_rs*lots:,.0f}  ({max_loss_rs*lots/CAPITAL:.0%} of capital)")
        print(f"        credit collected: Rs{credit*LOT*lots:,.0f}")
        print(f"        if wins (~83% base rate): keep ~Rs{credit*LOT*lots:,.0f} (+{credit*LOT*lots/CAPITAL:.0%})")
    print("\n  NOTE: prices are bhavcopy settle (indicative). Place LIMIT orders at live mid; the live")
    print("  credit may differ. Verify lot size + margin with your broker before sending.")


if __name__ == "__main__":
    main()
