"""fno_forward_paper.py — forward (paper) test of the RESCUED VIX-gated NIFTY monthly condor.

Strategy (from the liquid-strike revalidation, [[fno-strategy]]): MONTHLY NIFTY iron condor,
shorts ~1.0xEM, wings 0.5xEM, LIQUID strikes only, ENTER ONLY when India VIX >= 12. EM = liquid
ATM straddle. This records the live recommendation as an open paper trade and, once the expiry's
NIFTY close is available, settles it to realized P&L — a true forward test (no look-ahead).

    python fno_forward_paper.py                 # record entry for the latest chain (if VIX>=12) + settle due trades

Outputs results/fno_paper_trades.csv (one row per monthly condor: open then closed with P&L).
"""
import csv, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fno_condor_liquid import load, monthly_expiries, build_condor, atm_em, _d

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LEDGER = os.path.join(RESULTS, "fno_paper_trades.csv")
COLS = ["entry_date", "expiry", "spot", "vix", "lot", "sp", "sc", "lp", "lc",
        "credit", "max_loss", "be_low", "be_high", "status", "expiry_spot", "pnl_pts", "pnl_inr"]

BODY, WING, OI_MIN, VOL_MIN = 1.0, 0.5, 500, 1
MIN_VIX = 12.0
LOT = 65
MIN_DTE, MAX_DTE, TARGET_DTE = 20, 40, 28


def read_ledger():
    if os.path.exists(LEDGER):
        return list(csv.DictReader(open(LEDGER, newline="", encoding="utf-8")))
    return []


def write_ledger(rows):
    os.makedirs(RESULTS, exist_ok=True)
    with open(LEDGER, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    chains, nifty, vix = load()
    rows = read_ledger()
    have = {(r["entry_date"], r["expiry"]) for r in rows}

    # ---- 1) record a NEW entry for the latest chain date, if the VIX gate passes ----
    d0 = max(chains)
    v0 = vix.get(d0)
    mexp = sorted(e for e in monthly_expiries(chains)
                  if e > d0 and MIN_DTE <= (_d(e) - _d(d0)).days <= MAX_DTE
                  and any(o[0][:10] == e for o in chains[d0]["opts"]))
    if mexp and v0 is not None:
        E = min(mexp, key=lambda e: abs((_d(e) - _d(d0)).days - TARGET_DTE))
        if (d0, E) not in have:
            if v0 < MIN_VIX:
                print(f"[entry] {d0} VIX {v0:.1f} < {MIN_VIX} -> NO TRADE (gate blocks low-VIX months)")
            else:
                S0 = chains[d0]["spot"]
                em = atm_em(chains[d0]["opts"], S0, E, OI_MIN, VOL_MIN)
                c = build_condor(chains[d0]["opts"], S0, E, em, BODY, WING, OI_MIN, VOL_MIN, True)
                if c:
                    wing_w = min(c["sp"]["strike"] - c["lp"]["strike"],
                                 c["lc"]["strike"] - c["sc"]["strike"])
                    row = {"entry_date": d0, "expiry": E, "spot": round(S0, 1), "vix": round(v0, 2),
                           "lot": LOT, "sp": c["sp"]["strike"], "sc": c["sc"]["strike"],
                           "lp": c["lp"]["strike"], "lc": c["lc"]["strike"],
                           "credit": round(c["credit"], 1), "max_loss": round(wing_w - c["credit"], 1),
                           "be_low": round(c["sp"]["strike"] - c["credit"], 1),
                           "be_high": round(c["sc"]["strike"] + c["credit"], 1),
                           "status": "open", "expiry_spot": "", "pnl_pts": "", "pnl_inr": ""}
                    rows.append(row)
                    print(f"[entry] OPENED monthly condor {d0} -> exp {E} (VIX {v0:.1f}, EM {em:.0f}):")
                    print(f"        SELL {c['sp']['strike']:.0f}PE + {c['sc']['strike']:.0f}CE | "
                          f"BUY {c['lp']['strike']:.0f}PE + {c['lc']['strike']:.0f}CE")
                    print(f"        credit {c['credit']:.0f}pts (Rs{c['credit']*LOT:,.0f}) | "
                          f"max loss {wing_w-c['credit']:.0f}pts (Rs{(wing_w-c['credit'])*LOT:,.0f}) | "
                          f"profit zone {row['be_low']:.0f}-{row['be_high']:.0f}")

    # ---- 2) settle any OPEN trade whose expiry NIFTY close is now known ----
    for r in rows:
        if r["status"] != "open":
            continue
        E = r["expiry"]
        if E in nifty:
            ST = nifty[E]
            sp, sc, lp, lc = float(r["sp"]), float(r["sc"]), float(r["lp"]), float(r["lc"])
            cr = float(r["credit"])
            payoff = (cr - max(0.0, sp - ST) + max(0.0, lp - ST)
                      - max(0.0, ST - sc) + max(0.0, ST - lc))
            r["status"] = "closed"; r["expiry_spot"] = round(ST, 1)
            r["pnl_pts"] = round(payoff, 1); r["pnl_inr"] = round(payoff * float(r["lot"]), 0)
            print(f"[settle] {r['entry_date']}->{E}: NIFTY closed {ST:.0f} -> "
                  f"P&L {payoff:+.0f}pts (Rs{payoff*float(r['lot']):+,.0f})")

    write_ledger(rows)
    op = [r for r in rows if r["status"] == "open"]
    cl = [r for r in rows if r["status"] == "closed"]
    print(f"\nledger: {len(rows)} trades ({len(op)} open, {len(cl)} closed) -> {LEDGER}")
    if cl:
        tot = sum(float(r["pnl_inr"]) for r in cl)
        wins = sum(1 for r in cl if float(r["pnl_pts"]) > 0)
        print(f"closed P&L: {wins}/{len(cl)} wins | total Rs{tot:+,.0f}/lot")
    for r in op:
        print(f"  OPEN: {r['entry_date']}->{r['expiry']} zone {r['be_low']}-{r['be_high']} "
              f"credit {r['credit']}pts (settles after {r['expiry']})")


if __name__ == "__main__":
    main()
