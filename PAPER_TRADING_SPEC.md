# US Microcap EBIT Turnaround — Paper Trading Execution Specification

Status: frozen operational specification for paper trading. This document translates the validated research rules into an execution/logging protocol. It does not change the signal definition and must not be used to optimize the backtest.

## 1. Scope

Paper trading tests execution realism and operational discipline for the frozen FCF High cohort. Historical 2012-2020, modern 2023-2026 OOS, and paper results must be reported separately. None should be presented as an investable-performance claim.

## 2. Frozen signal and priority rules

Discovery signal: Candidate3, unchanged from the handoff:
- point-in-time market cap USD 10M-300M
- quarterly EBIT > 0 and same quarter prior year EBIT <= 0
- NI TTM < 0
- quarter-end equity > 0
- Candidate3: market cap < USD 80M, YoY quarterly FCF improvement / market cap > 1%, abs NI TTM loss / market cap > 10%

The removed EBIT-improvement / market-cap > 5% rule must not be reintroduced.

FCF High priority requires both:
- current quarterly FCF / market cap >= 3.591639%
- YoY quarterly FCF improvement / market cap >= 11.938595%

Within FCF High, rank larger YoY quarterly FCF improvement / market cap higher. Do not add accounting filters or return-dependent thresholds.

## 3. Filing, entry, and exit

- Signal date: confirmed actual filing/publication date; no look-ahead.
- Exact acceptance timestamp is retained when the source provides it, but missing time-of-day alone is not a skip when filing_date is confirmed.
- Entry: first trading-day open strictly AFTER the filing/publication date. Same-day entry is prohibited, so time-of-day cannot change the selected entry session under this protocol.
- Exit: close of the 20th subsequent trading session, with entry session treated as day 0.
- No forced interim stop-loss, take-profit, or day-10 no-response exit.
- Pre-entry fields must use only information available before entry.

## 4. Portfolio rules

- Maximum concurrent positions: 3.
- Target new-position allocation: up to one third of portfolio equity.
- Position notional <= 5% of strictly pre-entry ADV20 dollar volume.
- ADV20 uses exactly 20 trading sessions before entry.
- Initial paper capital: USD 15,000.
- USD 30,000 remains an execution sensitivity, not the default paper capital.
- Minimum practical paper order: USD 500, frozen before the first paper signal was logged. This operational choice was made after reviewing the existing sensitivity grid and therefore must not be cited as evidence of strategy quality or changed in response to paper returns.

## 5. Pre-entry liquidity diagnostics

Capture before entry:
- 20 sessions Open, High, Low, Close, Volume
- ADV20 dollar volume
- median dollar volume
- median Amihud illiquidity proxy
- median Corwin-Schultz-style OHLC spread proxy

The CS-style field is not a measured quote spread. The implementation uses the two-day high-low closed form and clips negative alpha to zero, but does not apply overnight-return adjustment. See `EXECUTION_PROXY_METHOD.md`.

## 6. Expected execution-cost model

Expected round-trip cost is a scenario estimate, not measured transaction cost.

Primary paper reference:
- spread component = 1.0 x pre-entry median CS-style spread proxy
- impact component = 0.01 * sqrt(position_notional / ADV20)

Required sensitivities:
- spread multiplier 1.0x and 2.0x
- k = 0.005, 0.01, 0.02, 0.05

Do not choose a scenario based on realized returns. Expected and observed execution costs remain separate.

## 7. Immutable signal log and lifecycle

Every FCF High paper signal gets one `paper_trade_log.csv` row, including skipped signals. Do not delete rows.

Lifecycle states are derived separately in `paper_portfolio_ledger.csv`:
- PLANNED: valid signal but entry open not yet observable
- OPEN: entry-session open observed, day-20 close not yet observable
- CLOSED: day-20 close observed
- SKIPPED: operational rule prevented execution

When daily data becomes available later, the lifecycle process may fill previously unavailable execution outcome fields such as entry open, exit date, exit close, gross R20 and paper net R20. Pre-entry signal, ranking, liquidity and expected-cost fields must not be rewritten after the outcome is known.

## 8. Skip reasons

Allowed codes:
- none
- skipped_min_order
- skipped_slot
- skipped_cash
- data_unavailable
- filing_timestamp_ambiguous
- trading_halt_or_no_open

`filing_timestamp_ambiguous` is reserved for cases where the filing/publication date itself cannot be safely established for strict next-session entry. Absence of time-of-day alone is not sufficient.

## 9. Review metrics

Report at minimum signal/trade counts, skips by reason, median notional, participation, expected cost at 1x/k=.01 and 2x/k=.01, observed slippage when available, median/mean net R20, win rate, >=20%, <=-20%, and maximum concurrent positions.

Do not combine historical and modern periods into one CAGR. Paper results are a third separate period.

## 10. Change control

Any change to signal criteria, FCF High thresholds, ranking, entry timing, 20-session hold, 3-slot cap, 5% ADV20 cap, minimum order, spread-proxy definition, or impact model requires a dated entry in `PAPER_TRADING_CHANGELOG.md` before processing the next signal.

Research bugs require recomputation of all dependent outputs. Narrative-only patches are not acceptable.

## 11. Current interpretation

Execution robustness remained positive in the frozen 30-event FCF High sample across the tested 1x/2x spread-proxy and impact sensitivities, while historical capacity was primarily constrained by liquidity/minimum practical order rather than the observed 3-slot cap. This remains proxy evidence, not proof of live investability.
