"""fno_settle.py — auto-settle open index vol-seller paper trades (condor + strangle).

Settlement watcher for results/fno_paper_trades.csv (written by fno_forward_paper.py). Uses public
index data (yfinance, per the trade's `index` column: NIFTY->^NSEI, BANKNIFTY->^NSEBANK) — no broker
login. Per open trade, if a stop is set (stop_mult>0) it walks the daily index path and BS-reprices
the position; if the mark-to-model loss reaches stop_mult x credit it closes there (stopped).
Otherwise it settles at expiry intrinsic once the expiry close exists. Handles both structures:
condor (4 legs, loss also wing-capped) and strangle (2 legs, naked). BS uses entry-day VIX flat
(mild approximation; BANKNIFTY condor is stopless so its sigma is unused). No-ops until data exists.
"""
import csv, math, os
from datetime import datetime, timedelta

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
LEDGER = os.path.join(RESULTS, "fno_paper_trades.csv")
YTICKER = {"NIFTY": "^NSEI", "BANKNIFTY": "^NSEBANK"}


def _N(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, sigma, t, call=True):
    if t <= 0 or sigma <= 0:
        return max(0.0, (S - K) if call else (K - S))
    d1 = (math.log(S / K) + (sigma * sigma / 2) * t) / (sigma * math.sqrt(t))
    d2 = d1 - sigma * math.sqrt(t)
    return (S * _N(d1) - K * _N(d2)) if call else (K * _N(-d2) - S * _N(-d1))


def _d(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def value_to_close(r, S, sig, trem):
    """Mark-to-model cost to close the position (buy back shorts, sell longs)."""
    v = bs(S, float(r["sp"]), sig, trem, call=False) + bs(S, float(r["sc"]), sig, trem, call=True)
    if r.get("kind") == "condor" and r["lp"] and r["lc"]:
        v -= bs(S, float(r["lp"]), sig, trem, call=False) + bs(S, float(r["lc"]), sig, trem, call=True)
    return v


def expiry_payoff(r, ST):
    cr = float(r["credit"])
    p = cr - max(0.0, float(r["sp"]) - ST) - max(0.0, ST - float(r["sc"]))
    if r.get("kind") == "condor" and r["lp"] and r["lc"]:
        p += max(0.0, float(r["lp"]) - ST) + max(0.0, ST - float(r["lc"]))
    return p


def index_history(ticker, start, end):
    try:
        import yfinance as yf
    except Exception:
        print("yfinance not installed -> cannot settle"); return {}
    df = yf.Ticker(ticker).history(start=start, end=end)
    if df is None or df.empty:
        return {}
    return {str(ix.date()): float(c) for ix, c in zip(df.index, df["Close"])}


def settle_trade(r, hist):
    """Return (pnl_pts, exit_spot, status_tag) or None if not yet resolvable."""
    E = r["expiry"]; entry = r["entry_date"]; cr = float(r["credit"])
    sig = float(r["vix"]) / 100.0
    sm = float(r["stop_mult"]) if r.get("stop_mult") not in (None, "") else 0.0
    Ed = _d(E)
    if sm > 0:
        for d in sorted(x for x in hist if entry < x < E):
            trem = max(1, (Ed - _d(d)).days) / 365.0
            V = value_to_close(r, hist[d], sig, trem)
            if (V - cr) >= sm * cr:
                return -(V - cr), round(hist[d], 1), "STOP"
    on = [x for x in hist if x >= E]
    if not on:
        return None
    ST = hist[min(on)]
    payoff = expiry_payoff(r, ST)
    return payoff, round(ST, 1), ("WIN" if payoff > 0 else "LOSS")


def main():
    if not os.path.exists(LEDGER):
        print("no ledger yet"); return
    rows = list(csv.DictReader(open(LEDGER, newline="", encoding="utf-8")))
    cols = list(rows[0].keys()) if rows else []
    changed = False
    for r in rows:
        if r.get("status") != "open":
            continue
        E = r["expiry"]; idx = r.get("index", "NIFTY")
        ticker = YTICKER.get(idx, "^NSEI")
        hist = index_history(ticker, r["entry_date"], (_d(E) + timedelta(days=5)).isoformat())
        res = settle_trade(r, hist)
        if res is None:
            print(f"[wait] [{idx} {r.get('kind')}] {r['entry_date']}->{E}: data not available yet")
            continue
        payoff, ST, tag = res
        lot = float(r["lot"])
        r["status"] = "closed"; r["expiry_spot"] = ST
        r["pnl_pts"] = round(payoff, 1); r["pnl_inr"] = round(payoff * lot, 0)
        print(f"[settle] [{idx} {r.get('kind')}] {r['entry_date']}->{E}: exit {ST} {tag} "
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
