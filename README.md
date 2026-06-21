# nifty-vol-seller-paper — VIX-gated NIFTY vol-selling (forward paper test)

Forward (paper) test of the only F&O edge that survived honest revalidation: **selling NIFTY vol
only when India VIX ≥ 12**, on **liquid (OI-filtered) strikes**, monthly. Two structures run
head-to-head:
- **Iron condor** — shorts ~1.0×EM, wings 0.5×EM, **1.5×-credit stop**. Stop-tuned Sharpe ~1.75
  (+Rs103k/3yr/lot), best **return-on-margin** (~100%/yr). The earlier "Sharpe 1.37" via a naive
  50-pt grid was a stale-settle artifact.
- **Short strangle** — shorts ~1.0×EM, no wings, **2.5×-credit stop**. Stop-tuned Sharpe ~1.97
  (+Rs209k/3yr/lot), best **absolute return** but needs naked SPAN margin.

Stops were chosen from a historical sweep (tight stops whipsaw; condor ~1.5×, strangle ~2.5× are
the better ranges). Note: real gaps can blow through a stop — the condor's wings can't be gapped.

- **BANKNIFTY iron condor** — shorts ~1.0×EM, wings 0.5×EM, **stopless**. A 2026-06-21 cross-index
  revalidation on real liquid strikes (n=30) reproduced the NIFTY pattern: VIX≥12 Sharpe **1.50**
  (+Rs92.8k/lot), VIX<12 *loses* (−1.13). The edge is **not NIFTY-specific**. Unlike NIFTY, the
  credit stop *hurt* BANKNIFTY (1.50→1.25), so it runs stopless — its wings still cap the loss.

Directional trend on the index and condor+trend combinations were tested and rejected (no edge / no
diversification benefit). FINNIFTY/MIDCPNIFTY were too thin/illiquid to judge (n=6–10).

## Files
- `fno_forward_paper.py` — record a new monthly condor entry (run locally with fresh chain data).
- `fno_settle.py` — **auto-settles** open trades once the expiry index close exists (via yfinance,
  per-index: NIFTY `^NSEI`, BANKNIFTY `^NSEBANK`). Runs weekly in GitHub Actions
  (`.github/workflows/settle.yml`); no broker login needed.
- `fno_condor_liquid.py` — the liquid-strike backtest + VIX-gate / stop sweeps.
- `fno_build_liquid_chains.py` — rebuilds `data/fno/chains_liq.json` (settle+OI+vol) from raw bhavcopy.
- `fno_calendar.py` — calendar-spread test (tested, weaker than the condor — not deployed).
- `results/fno_paper_trades.csv` — the trade + P&L ledger (the thing to watch).

## Status
Open paper trades, all entry 2026-06-19 → **expiry 2026-07-28** (VIX 13.0):
- NIFTY condor: SELL 23200PE+24800CE / BUY 22800PE+25200CE, credit 120pts, zone 23080–24920.
- NIFTY strangle: SELL 23200PE+24800CE (naked, 2.5× stop), credit 246pts, zone 22954–25046.
- BANKNIFTY condor: SELL 55600PE+59900CE / BUY 54500PE+61000CE, credit 330pts, zone 55270–60230.

The settle workflow resolves each automatically after expiry.

> Paper only. Settle prices ≈ close, not real fills. The edge is **index-specific** — single-stock
> condors lose. Not investment advice.
