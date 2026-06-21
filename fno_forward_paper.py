"""fno_forward_paper.py — record forward (paper) entries for the VIX-gated index vol-sellers.

Records the validated vol-selling structures head-to-head, when India VIX >= 12 (the gate):
  * NIFTY CONDOR    — shorts ~1.0xEM, wings 0.5xEM (defined risk, 1.5x-credit stop; best ROM).
  * NIFTY STRANGLE  — shorts ~1.0xEM, no wings (naked, 2.5x-credit stop; best absolute return).
  * BANKNIFTY CONDOR— shorts ~1.0xEM, wings 0.5xEM, STOPLESS (cross-index revalidation 2026-06-21
                      showed the credit stop HURTS BANKNIFTY, Sharpe 1.50->1.25; wings cap the loss).
EM = liquid ATM straddle. Run locally with a fresh chain to open a new monthly cycle; settlement is
handled by fno_settle.py (cloud, yfinance per-index). Ledger: results/fno_paper_trades.csv
(one row per index+kind per cycle).
"""
import csv, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fno_condor_liquid import (load, monthly_expiries, build_condor, pick_leg, atm_em, _d, DATA)

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LEDGER = os.path.join(RESULTS, "fno_paper_trades.csv")
COLS = ["entry_date", "expiry", "index", "kind", "spot", "vix", "lot", "sp", "sc", "lp", "lc",
        "credit", "max_loss", "stop_mult", "be_low", "be_high", "status",
        "expiry_spot", "pnl_pts", "pnl_inr"]

BODY, WING, OI_MIN, VOL_MIN = 1.0, 0.5, 500, 1
MIN_VIX = 12.0
MIN_DTE, MAX_DTE, TARGET_DTE = 20, 40, 28
# improved stops from the historical stop sweep: NIFTY condor 1.5xcredit (Sharpe 1.35->1.75),
# NIFTY strangle 2.5xcredit (1.53->1.97). BANKNIFTY condor STOPLESS (stop hurt it, 1.50->1.25).
CONDOR_STOP, STRANGLE_STOP, BNF_CONDOR_STOP = 1.5, 2.5, 0.0
NIFTY_LOT, BNF_LOT = 65, 35


def read_ledger():
    if not os.path.exists(LEDGER):
        return []
    rows = list(csv.DictReader(open(LEDGER, newline="", encoding="utf-8")))
    for r in rows:                       # back-compat: pre-index rows are all NIFTY
        r.setdefault("index", "NIFTY")
    return rows


def write_ledger(rows):
    os.makedirs(RESULTS, exist_ok=True)
    with open(LEDGER, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(rows)


def pick_cycle(chains, d0):
    """The monthly expiry nearest TARGET_DTE that is tradeable from d0."""
    mexp = sorted(e for e in monthly_expiries(chains)
                  if e > d0 and MIN_DTE <= (_d(e) - _d(d0)).days <= MAX_DTE
                  and any(o[0][:10] == e for o in chains[d0]["opts"]))
    if not mexp:
        return None
    return min(mexp, key=lambda e: abs((_d(e) - _d(d0)).days - TARGET_DTE))


def condor_row(opts, d0, E, S0, v0, em, index, lot, stop):
    c = build_condor(opts, S0, E, em, BODY, WING, OI_MIN, VOL_MIN, True)
    if not c:
        return None
    wing_w = min(c["sp"]["strike"] - c["lp"]["strike"], c["lc"]["strike"] - c["sc"]["strike"])
    return dict(entry_date=d0, expiry=E, index=index, kind="condor", spot=round(S0, 1),
                vix=round(v0, 2), lot=lot, sp=c["sp"]["strike"], sc=c["sc"]["strike"],
                lp=c["lp"]["strike"], lc=c["lc"]["strike"], credit=round(c["credit"], 1),
                max_loss=round(wing_w - c["credit"], 1), stop_mult=stop,
                be_low=round(c["sp"]["strike"] - c["credit"], 1),
                be_high=round(c["sc"]["strike"] + c["credit"], 1),
                status="open", expiry_spot="", pnl_pts="", pnl_inr="")


def strangle_row(opts, d0, E, S0, v0, em, index, lot, stop):
    sp = pick_leg(opts, E, "PE", S0 - BODY * em, OI_MIN, VOL_MIN, True)
    sc = pick_leg(opts, E, "CE", S0 + BODY * em, OI_MIN, VOL_MIN, True)
    if not (sp and sc):
        return None
    cr = sp["price"] + sc["price"]
    return dict(entry_date=d0, expiry=E, index=index, kind="strangle", spot=round(S0, 1),
                vix=round(v0, 2), lot=lot, sp=sp["strike"], sc=sc["strike"], lp="", lc="",
                credit=round(cr, 1), max_loss="naked", stop_mult=stop,
                be_low=round(sp["strike"] - cr, 1), be_high=round(sc["strike"] + cr, 1),
                status="open", expiry_spot="", pnl_pts="", pnl_inr="")


def open_index(rows, have, chains, vix, index, lot, kinds):
    """Open the requested kinds for one index on its latest chain date, if the VIX gate passes."""
    d0 = max(chains); v0 = vix.get(d0)
    if v0 is None:
        return
    E = pick_cycle(chains, d0)
    if not E:
        print(f"[{index}] {d0}: no tradeable monthly expiry near {TARGET_DTE}DTE"); return
    S0 = chains[d0]["spot"]
    em = atm_em(chains[d0]["opts"], S0, E, OI_MIN, VOL_MIN)
    if not em:
        print(f"[{index}] {d0}: no liquid ATM straddle for {E}"); return
    if v0 < MIN_VIX:
        print(f"[{index}] {d0} VIX {v0:.1f} < {MIN_VIX} -> NO TRADE (gate blocks low-VIX)"); return
    for kind, stop in kinds:
        if (d0, E, index, kind) in have:
            continue
        builder = condor_row if kind == "condor" else strangle_row
        r = builder(chains[d0]["opts"], d0, E, S0, v0, em, index, lot, stop)
        if not r:
            print(f"[{index} {kind}] {d0}->{E}: could not build (illiquid strikes)"); continue
        rows.append(r)
        legs = (f"SELL {r['sp']:.0f}PE+{r['sc']:.0f}CE" +
                (f" BUY {r['lp']:.0f}PE+{r['lc']:.0f}CE" if r["lp"] != "" else " (naked)"))
        print(f"[{index} {kind}] {legs} | credit {r['credit']:.0f} (Rs{r['credit']*lot:,.0f}) "
              f"| zone {r['be_low']:.0f}-{r['be_high']:.0f} | stop {stop}x")


def load_bnf():
    """BANKNIFTY chain (settle+OI+vol) + the same India VIX series used as the regime gate."""
    chains = json.load(open(os.path.join(DATA, "chains_liq_BANKNIFTY.json")))
    vix = {r["date"][:10]: r["close"]
           for r in json.load(open(os.path.join(DATA, "INDIAVIX_day.json")))}
    return chains, vix


def main():
    rows = read_ledger()
    have = {(r["entry_date"], r["expiry"], r["index"], r["kind"]) for r in rows}

    # NIFTY: condor (1.5x stop) + strangle (2.5x stop)
    n_chains, _, n_vix = load()
    open_index(rows, have, n_chains, n_vix, "NIFTY", NIFTY_LOT,
               [("condor", CONDOR_STOP), ("strangle", STRANGLE_STOP)])

    # BANKNIFTY: condor only, STOPLESS
    b_chains, b_vix = load_bnf()
    open_index(rows, have, b_chains, b_vix, "BANKNIFTY", BNF_LOT,
               [("condor", BNF_CONDOR_STOP)])

    write_ledger(rows)
    op = [r for r in rows if r["status"] == "open"]
    print(f"\nledger: {len(rows)} trades ({len(op)} open) -> {LEDGER}")
    for r in op:
        print(f"  OPEN [{r['index']} {r['kind']}] {r['entry_date']}->{r['expiry']} "
              f"zone {r['be_low']}-{r['be_high']} credit {r['credit']} stop {r['stop_mult']}x")


if __name__ == "__main__":
    main()
