"""fno_portfolio.py — combine the VIX-gated short strangle (short-vol) with the index trend leg
(long-momentum) and analyze joint P&L. Thesis: the strangle loses on big moves; the trend leg wins
on big moves -> the trend leg may act as a near-free tail hedge, raising risk-adjusted return even
though it loses standalone. Aligns both to a monthly P&L series over the overlapping window.

    python fno_portfolio.py
"""
import csv, math, os, statistics as st, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fno_strangle import run as strangle_run

LOT = 65
HERE = os.path.dirname(os.path.abspath(__file__))


def monthly_series():
    # strangle: bucket by expiry month (Rs)
    sttr = strangle_run(body=1.0, min_vix=12, max_vix=999, stop_mult=2.0,
                        cost_leg=2.0, oi_min=500, vol_min=1)
    S = {}
    for t in sttr:
        S[t["E"][:7]] = S.get(t["E"][:7], 0.0) + t["pnl"] * LOT
    # trend: bucket by exit month (Rs, at Rs1000 risk)
    T = {}
    path = os.path.join(HERE, "results", "idx_trend_trades.csv")
    for r in csv.DictReader(open(path, newline="", encoding="utf-8")):
        T[r["exit_dt"][:7]] = T.get(r["exit_dt"][:7], 0.0) + float(r["pnl_inr"])
    return S, T


def metrics(series):
    vals = list(series)
    n = len(vals)
    if not n:
        return None
    tot = sum(vals); mean = tot / n; sd = st.pstdev(vals)
    sharpe = mean / sd * math.sqrt(12) if sd else 0
    eq = peak = mdd = 0
    for v in vals:
        eq += v; peak = max(peak, eq); mdd = max(mdd, peak - eq)
    return dict(n=n, total=round(tot), sharpe=round(sharpe, 2), maxdd=round(mdd),
                worst=round(min(vals)), best=round(max(vals)))


def main():
    S, T = monthly_series()
    # overlapping window: months from the later start to the earlier end
    lo = max(min(S), min(T)); hi = min(max(S), max(T))
    months = sorted(m for m in (set(S) | set(T)) if lo <= m <= hi)
    s = [S.get(m, 0.0) for m in months]
    t = [T.get(m, 0.0) for m in months]
    print(f"overlap {lo}..{hi}  ({len(months)} months)\n")

    # correlation
    if st.pstdev(s) and st.pstdev(t):
        ms, mt = st.mean(s), st.mean(t)
        cov = sum((a - ms) * (b - mt) for a, b in zip(s, t)) / len(s)
        corr = cov / (st.pstdev(s) * st.pstdev(t))
    else:
        corr = float("nan")
    print(f"correlation(strangle, trend) = {corr:+.2f}  (negative => trend hedges the strangle)\n")

    sm = metrics(s)
    print(f"STRANGLE only : total Rs{sm['total']:+,} | Sharpe {sm['sharpe']} | maxDD {sm['maxdd']:,} | "
          f"worst mo {sm['worst']:+,}")
    tm = metrics(t)
    print(f"TREND only    : total Rs{tm['total']:+,} | Sharpe {tm['sharpe']} | maxDD {tm['maxdd']:,} | "
          f"worst mo {tm['worst']:+,}")
    print("\nCOMBINED strangle + k x trend (k scales the trend hedge size):")
    best = None
    for k in (1, 3, 5, 8, 12, 20):
        c = [a + k * b for a, b in zip(s, t)]
        cm = metrics(c)
        flag = ""
        if cm["sharpe"] > sm["sharpe"]:
            flag = "  <-- beats strangle-alone Sharpe"
        print(f"  k={k:>2}: total Rs{cm['total']:+,} | Sharpe {cm['sharpe']} | maxDD {cm['maxdd']:,} | "
              f"worst mo {cm['worst']:+,}{flag}")
        if best is None or cm["sharpe"] > best[1]["sharpe"]:
            best = (k, cm)
    print(f"\nbest combined: k={best[0]} Sharpe {best[1]['sharpe']} vs strangle-alone {sm['sharpe']}")
    # show the strangle's worst months and what trend did then
    print("\nstrangle's worst 5 months vs trend P&L that month (hedge check):")
    for m in sorted(months, key=lambda m: S.get(m, 0))[:5]:
        print(f"  {m}: strangle Rs{S.get(m,0):+,.0f} | trend(Rs1k-risk) Rs{T.get(m,0):+,.0f}")


if __name__ == "__main__":
    main()
