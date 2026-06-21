"""fno_forward_paper.py — record forward (paper) entries for the VIX-gated NIFTY vol-sellers.

Records BOTH validated vol-selling structures head-to-head, when India VIX >= 12 (the gate):
  * CONDOR   — shorts ~1.0xEM, wings 0.5xEM (defined risk, no stop; best return-on-margin).
  * STRANGLE — shorts ~1.0xEM, no wings (naked, managed by a 2x-credit stop; best absolute return).
EM = liquid ATM straddle. Run locally with a fresh chain to open a new monthly cycle; settlement is
handled by fno_settle.py (cloud). Ledger: results/fno_paper_trades.csv (one row per kind per cycle).
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fno_condor_liquid import load, monthly_expiries, build_condor, pick_leg, atm_em, _d

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LEDGER = os.path.join(RESULTS, "fno_paper_trades.csv")
COLS = ["entry_date", "expiry", "kind", "spot", "vix", "lot", "sp", "sc", "lp", "lc",
        "credit", "max_loss", "stop_mult", "be_low", "be_high", "status",
        "expiry_spot", "pnl_pts", "pnl_inr"]

BODY, WING, OI_MIN, VOL_MIN = 1.0, 0.5, 500, 1
MIN_VIX, LOT = 12.0, 65
MIN_DTE, MAX_DTE, TARGET_DTE = 20, 40, 28
# improved stops from the historical stop sweep: condor 1.5xcredit (Sharpe 1.35->1.75),
# strangle 2.5xcredit (Sharpe 1.53->1.97). Tight stops whipsaw; these are the better ranges.
CONDOR_STOP = 1.5
STRANGLE_STOP = 2.5


def read_ledger():
    if os.path.exists(LEDGER):
        return list(csv.DictReader(open(LEDGER, newline="", encoding="utf-8")))
    return []


def write_ledger(rows):
    os.makedirs(RESULTS, exist_ok=True)
    with open(LEDGER, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(rows)


def main():
    chains, nifty, vix = load()
    rows = read_ledger()
    have = {(r["entry_date"], r["expiry"], r.get("kind", "condor")) for r in rows}

    d0 = max(chains); v0 = vix.get(d0)
    mexp = sorted(e for e in monthly_expiries(chains)
                  if e > d0 and MIN_DTE <= (_d(e) - _d(d0)).days <= MAX_DTE
                  and any(o[0][:10] == e for o in chains[d0]["opts"]))
    if mexp and v0 is not None:
        E = min(mexp, key=lambda e: abs((_d(e) - _d(d0)).days - TARGET_DTE))
        S0 = chains[d0]["spot"]
        em = atm_em(chains[d0]["opts"], S0, E, OI_MIN, VOL_MIN)
        if v0 < MIN_VIX:
            print(f"[entry] {d0} VIX {v0:.1f} < {MIN_VIX} -> NO TRADE (gate blocks low-VIX)")
        elif em:
            base = dict(entry_date=d0, expiry=E, spot=round(S0, 1), vix=round(v0, 2), lot=LOT,
                        status="open", expiry_spot="", pnl_pts="", pnl_inr="")
            # ---- CONDOR ----
            c = build_condor(chains[d0]["opts"], S0, E, em, BODY, WING, OI_MIN, VOL_MIN, True)
            if c and (d0, E, "condor") not in have:
                wing_w = min(c["sp"]["strike"] - c["lp"]["strike"], c["lc"]["strike"] - c["sc"]["strike"])
                rows.append({**base, "kind": "condor", "sp": c["sp"]["strike"], "sc": c["sc"]["strike"],
                             "lp": c["lp"]["strike"], "lc": c["lc"]["strike"], "credit": round(c["credit"], 1),
                             "max_loss": round(wing_w - c["credit"], 1), "stop_mult": CONDOR_STOP,
                             "be_low": round(c["sp"]["strike"] - c["credit"], 1),
                             "be_high": round(c["sc"]["strike"] + c["credit"], 1)})
                print(f"[condor]   SELL {c['sp']['strike']:.0f}PE+{c['sc']['strike']:.0f}CE "
                      f"BUY {c['lp']['strike']:.0f}PE+{c['lc']['strike']:.0f}CE | credit {c['credit']:.0f} "
                      f"| zone {c['sp']['strike']-c['credit']:.0f}-{c['sc']['strike']+c['credit']:.0f}")
            # ---- STRANGLE ----
            sp = pick_leg(chains[d0]["opts"], E, "PE", S0 - BODY * em, OI_MIN, VOL_MIN, True)
            sc = pick_leg(chains[d0]["opts"], E, "CE", S0 + BODY * em, OI_MIN, VOL_MIN, True)
            if sp and sc and (d0, E, "strangle") not in have:
                cr = sp["price"] + sc["price"]
                rows.append({**base, "kind": "strangle", "sp": sp["strike"], "sc": sc["strike"],
                             "lp": "", "lc": "", "credit": round(cr, 1), "max_loss": "naked",
                             "stop_mult": STRANGLE_STOP, "be_low": round(sp["strike"] - cr, 1),
                             "be_high": round(sc["strike"] + cr, 1)})
                print(f"[strangle] SELL {sp['strike']:.0f}PE+{sc['strike']:.0f}CE (naked, {STRANGLE_STOP}x stop) "
                      f"| credit {cr:.0f} (Rs{cr*LOT:,.0f}) | zone {sp['strike']-cr:.0f}-{sc['strike']+cr:.0f}")

    write_ledger(rows)
    op = [r for r in rows if r["status"] == "open"]
    print(f"\nledger: {len(rows)} trades ({len(op)} open) -> {LEDGER}")
    for r in op:
        print(f"  OPEN [{r['kind']}] {r['entry_date']}->{r['expiry']} "
              f"zone {r['be_low']}-{r['be_high']} credit {r['credit']}")


if __name__ == "__main__":
    main()
