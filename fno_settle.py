"""fno_settle.py — auto-settle open NIFTY vol-seller paper trades (condor + strangle).

Settlement watcher for results/fno_paper_trades.csv (written by fno_forward_paper.py). Uses public
NIFTY data (yfinance ^NSEI) — no broker login. Per open trade:
  * CONDOR   : settle at expiry intrinsic once the expiry close exists (defined risk, no stop).
  * STRANGLE : walk the daily NIFTY path; if the BS-repriced loss hits stop_mult x credit, close
               there (stopped); otherwise settle at expiry intrinsic. BS uses entry-day VIX flat
               (a mild approximation, matching the backtest's stop model closely enough).
Designed to run unattended weekly (GitHub Actions); no-ops until the needed data exists.
"""
import csv, math, os
from datetime import date, datetime, timedelta

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LEDGER = os.path.join(RESULTS, "fno_paper_trades.csv")


def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, sigma, t, call=True):
    if t <= 0 or sigma <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (sigma * sigma / 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return (S * _N(d1) - K * _N(d2)) if call else (K * _N(-d2) - S * _N(-d1))


def nifty_history(start, end):
    """Daily ^NSEI closes {YYYY-MM-DD: close} between start and end (inclusive-ish); {} if N/A."""
    try:
        import yfinance as yf
    except Exception:
        print("yfinance not installed -> cannot settle"); return {}
    df = yf.Ticker("^NSEI").history(start=start, end=end)
    if df is None or df.empty:
        return {}
    return {str(ix.date()): float(c) for ix, c in zip(df.index, df["Close"])}


def settle_strangle(r, hist):
    """Return (pnl_pts, exit_spot, stopped) or None if not yet resolvable."""
    E = r["expiry"]; entry = r["entry_date"]
    cr = float(r["credit"]); Kp, Kc = float(r["sp"]), float(r["sc"])
    sig = float(r["vix"]) / 100.0; sm = float(r["stop_mult"])
    Ed = datetime.strptime(E, "%Y-%m-%d").date()
    path = sorted(d for d in hist if entry < d <= E)
    # need data through expiry (or at least a stop trigger) before settling
    have_expiry = any(d >= E for d in hist)
    for d in path:
        trem = max(1, (Ed - datetime.strptime(d, "%Y-%m-%d").date()).days) / 365.0
        S = hist[d]
        V = bs(S, Kp, sig, trem, call=False) + bs(S, Kc, sig, trem, call=True)
        if sm > 0 and (V - cr) >= sm * cr:
            return -(V - cr), round(S, 1), True
    if not have_expiry:
        return None
    ST = hist[max(d for d in hist if d <= E)]
    payoff = cr - max(0.0, Kp - ST) - max(0.0, ST - Kc)
    return payoff, round(ST, 1), False


def settle_condor(r, hist):
    E = r["expiry"]
    on = [d for d in hist if d >= E]
    if not on:
        return None
    ST = hist[min(on)]
    cr = float(r["credit"]); sp, sc, lp, lc = float(r["sp"]), float(r["sc"]), float(r["lp"]), float(r["lc"])
    payoff = (cr - max(0.0, sp - ST) + max(0.0, lp - ST) - max(0.0, ST - sc) + max(0.0, ST - lc))
    return payoff, round(ST, 1), False


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
        hist = nifty_history(r["entry_date"], (datetime.strptime(E, "%Y-%m-%d").date()
                                               + timedelta(days=5)).isoformat())
        res = settle_strangle(r, hist) if r.get("kind") == "strangle" else settle_condor(r, hist)
        if res is None:
            print(f"[wait] [{r.get('kind')}] {r['entry_date']}->{E}: data not available yet")
            continue
        payoff, ST, stopped = res
        lot = float(r["lot"])
        r["status"] = "closed"; r["expiry_spot"] = ST
        r["pnl_pts"] = round(payoff, 1); r["pnl_inr"] = round(payoff * lot, 0)
        tag = "STOPPED" if stopped else ("WIN" if payoff > 0 else "LOSS")
        print(f"[settle] [{r.get('kind')}] {r['entry_date']}->{E}: exit {ST} {tag} "
              f"{payoff:+.0f}pts (Rs{payoff*lot:+,.0f})")
        changed = True

    if changed:
        with open(LEDGER, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)
        print("ledger updated")
    else:
        print("no trades settled this run")


if __name__ == "__main__":
    main()
