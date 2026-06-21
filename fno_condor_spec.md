# NIFTY Iron Condor — Live Trading Spec

Validated on 3 years of real NSE option prices (bhavcopy, 2023-07 → 2026-06), survives realistic
slippage (Sharpe ~1.4 after ~2 pts/leg). Index-only — does NOT work on single stocks.

## Instrument
- **NIFTY index options** (NSE, cash-settled). Most liquid, no single-stock gap risk.

## Structure — Iron Condor (defined-risk short volatility)
- SELL 1 OTM put (short put)  + SELL 1 OTM call (short call)   -> collect premium
- BUY  1 further-OTM put (wing) + BUY 1 further-OTM call (wing) -> cap the loss

## Rules (exact)
1. **Expiry:** the nearest NIFTY expiry **>= 18 calendar days out** (in practice ~18-25 DTE,
   usually the next-but-one weekly). Do NOT use the front 0-10 DTE expiry (it loses).
2. **Expected move (EM):** `EM = ATM_call + ATM_put` settle/quote for that expiry, where
   `ATM = round(spot / 50) * 50`.
3. **Strikes (round each to nearest 50):**
   - Short put  `Kps = ATM - 1.5*EM`   |   Short call `Kcs = ATM + 1.5*EM`
   - Long put   `Kpb = Kps - 0.5*EM`    |   Long call  `Kcb = Kcs + 0.5*EM`
4. **Entry:** one 4-leg net-credit (limit ~mid) order. Verify the far-OTM wing legs have LIVE
   quotes (bhavcopy far-OTM settle can be stale). Budget ~1-2 pts/leg slippage.
5. **Exit:** HOLD TO EXPIRY (cash-settled at intrinsic). **No active stop** — the wings are the
   stop; a price stop was tested and *hurt* (whipsaw). Tail loss is capped by construction.
6. **Sizing:** max loss/trade = `(wing_width - net_credit) * lot` (= the margin). Size so max
   loss <= ~2-3% of capital. ~1 condor per cycle.

## Expected performance (3yr real prices, after ~2 pts/leg slippage, lot 75)
- Win rate ~84% | Sharpe ~1.37 | avg +Rs2,173/trade | worst ~ -Rs19k (capped) | +Rs82.6k/lot/3yr.
- Profit when NIFTY at expiry stays between the short strikes (Kps..Kcs).

## Risk / caveats
- Tail = a sustained trending month or a vol-spike cluster (~16% of cycles are losers). Defined
  risk caps each loss, but losers can cluster.
- NEVER sell naked (no wings). Index only. Sample ~38 trades over a mostly bull/range 2023-26
  regime; start small live to confirm fills match the model.

## Variant
- `wing = 1.0*EM` instead of 0.5: higher total profit (+Rs118k/3yr) but ~3x larger max loss
  (worst ~ -Rs44k). Use 0.5 for tighter risk, 1.0 for more income if capital/appetite allows.
