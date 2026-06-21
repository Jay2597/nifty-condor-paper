# nifty-condor-paper — VIX-gated NIFTY monthly iron condor (forward paper test)

Forward (paper) test of the only F&O edge that survived honest revalidation: a **monthly NIFTY
iron condor**, shorts ~1.0×EM, wings 0.5×EM, on **liquid (OI-filtered) strikes**, entered **only
when India VIX ≥ 12**. On real bhavcopy prices this showed Sharpe ~1.35 (n=23, cost-robust); the
earlier "Sharpe 1.37" headline using a naive 50-pt grid was a stale-settle / methodology artifact.

## Files
- `fno_forward_paper.py` — record a new monthly condor entry (run locally with fresh chain data).
- `fno_settle.py` — **auto-settles** open trades once the expiry NIFTY close exists (via yfinance
  `^NSEI`). Runs weekly in GitHub Actions (`.github/workflows/settle.yml`); no broker login needed.
- `fno_condor_liquid.py` — the liquid-strike backtest + VIX-gate / stop sweeps.
- `fno_build_liquid_chains.py` — rebuilds `data/fno/chains_liq.json` (settle+OI+vol) from raw bhavcopy.
- `fno_calendar.py` — calendar-spread test (tested, weaker than the condor — not deployed).
- `results/fno_paper_trades.csv` — the trade + P&L ledger (the thing to watch).

## Status
Open paper trade: entry 2026-06-19 → **expiry 2026-07-28** (VIX 13.0), SELL 23200PE+24800CE /
BUY 22800PE+25200CE, credit 120pts, profit zone 23080–24920. The settle workflow resolves it
automatically after expiry.

> Paper only. Settle prices ≈ close, not real fills. The edge is **index-specific** — single-stock
> condors lose. Not investment advice.
