"""fno_settle.py — auto-settle open NIFTY condor paper trades.

Standalone settlement watcher for results/fno_paper_trades.csv (written by fno_forward_paper.py).
For any OPEN trade whose expiry date has passed, it fetches NIFTY's close on the expiry day from a
public source (yfinance ^NSEI — no Kite login needed) and settles the condor to realized P&L at
intrinsic. Designed to run unattended on a schedule (GitHub Actions): it only acts once the expiry
close exists, otherwise it no-ops.

    python fno_settle.py
"""
import csv, os
from datetime import date, datetime, timedelta

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LEDGER = os.path.join(RESULTS, "fno_paper_trades.csv")


def nifty_close_on(day: str):
    """NIFTY (^NSEI) close on `day` (YYYY-MM-DD) via yfinance; None if unavailable yet."""
    try:
        import yfinance as yf
    except Exception:
        print("yfinance not installed -> cannot settle"); return None
    d = datetime.strptime(day, "%Y-%m-%d").date()
    if d > date.today():
        return None  # expiry hasn't happened yet
    df = yf.Ticker("^NSEI").history(start=day, end=(d + timedelta(days=4)).isoformat())
    if df is None or df.empty:
        return None
    # first available close on/after the expiry date
    return float(df["Close"].iloc[0])


def main():
    if not os.path.exists(LEDGER):
        print("no ledger yet"); return
    rows = list(csv.DictReader(open(LEDGER, newline="", encoding="utf-8")))
    cols = list(rows[0].keys()) if rows else []
    changed = False

    for r in rows:
        if r.get("status") != "open":
            continue
        E = r["expiry"]
        ST = nifty_close_on(E)
        if ST is None:
            print(f"[wait] {r['entry_date']}->{E}: expiry close not available yet")
            continue
        sp, sc, lp, lc = float(r["sp"]), float(r["sc"]), float(r["lp"]), float(r["lc"])
        cr = float(r["credit"]); lot = float(r["lot"])
        payoff = (cr - max(0.0, sp - ST) + max(0.0, lp - ST)
                  - max(0.0, ST - sc) + max(0.0, ST - lc))
        r["status"] = "closed"; r["expiry_spot"] = round(ST, 1)
        r["pnl_pts"] = round(payoff, 1); r["pnl_inr"] = round(payoff * lot, 0)
        won = sp <= ST <= sc
        print(f"[settle] {r['entry_date']}->{E}: NIFTY {ST:.0f} -> "
              f"{'WIN' if won else 'BREACH'} {payoff:+.0f}pts (Rs{payoff*lot:+,.0f})")
        changed = True

    if changed:
        with open(LEDGER, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
            w.writerows(rows)
        print("ledger updated")
    else:
        print("no trades settled this run")


if __name__ == "__main__":
    main()
