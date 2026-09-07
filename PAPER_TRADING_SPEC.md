# US Microcap EBIT Turnaround — Paper Trading Execution Specification

Status: frozen operational specification for paper trading. This document translates the validated research rules into an execution/logging protocol. It does not change the signal definition and must not be used to optimize the backtest.

## 1. Scope

The purpose of paper trading is to test execution realism and operational discipline for the frozen FCF High subset of the EBIT-turnaround strategy. The research signal, priority rule, entry timing, holding period, slot cap, and liquidity cap remain unchanged.

Historical 2012-2020 and modern 2023-2026 evidence must continue to be reported separately. Historical data has known survivorship/mapping limitations and missing Q4 coverage. Modern OOS has only 12 mature FCF High events. Neither period should be represented as an investable-performance claim.

## 2. Frozen signal and priority rules

Discovery signal: Candidate3, unchanged from the research handoff.

FCF High priority requires both:
- current quarterly FCF / market cap >= 3.591639%
- YoY quarterly FCF improvement / market cap >= 11.938595%

Within FCF High, rank larger YoY quarterly FCF improvement / market cap higher. Do not add new accounting filters or hard thresholds without a separately preregistered redesign.

## 3. Entry and exit

- Signal timestamp: actual filing/publication timestamp only; no look-ahead.
- Entry: first trading-day open after the filing/publication date.
- Exit: day-20 trading-day close.
- No forced interim stop-loss.
- No forced take-profit.
- No day-10 no-response exit.
- Do not substitute later-known data when reconstructing pre-entry information.

## 4. Portfolio rules

- Maximum concurrent positions: 3.
- Target allocation per new position: up to one third of marked portfolio equity.
- Position notional must also be <= 5% of pre-entry ADV20 dollar volume.
- ADV20 must use exactly the 20 trading days strictly before entry.
- Initial paper-capital reference: USD 15,000.
- USD 30,000 remains an upper experimental sensitivity level, not the default deployment size.
- If a candidate position is too small to be operationally meaningful, log it as skipped_min_order rather than altering the signal.

Minimum practical order size was not frozen by the research handoff. During paper trading, record the chosen operational minimum explicitly before the first signal and do not change it in response to returns. The validated sensitivity grid was USD 100 / 250 / 500 / 1,000; USD 500 is a reasonable default reference for logging because it preserved all 12 modern OOS events while filtering several extremely illiquid historical events, but it is an operational convention rather than a research-optimized parameter.

## 5. Pre-entry liquidity diagnostics

For every candidate event, capture before entry:
- 20 trading days of Open, High, Low, Close, Volume
- ADV20 dollar volume
- median dollar volume
- median Amihud illiquidity proxy
- median Corwin-Schultz-style OHLC spread proxy

These are pre-entry diagnostics only. Corwin-Schultz is an OHLC-based spread proxy, not a measured quoted or realized spread.

## 6. Expected execution-cost model

Expected round-trip cost is a scenario estimate, not a measured transaction cost.

Primary paper reference:
- spread component = 1.0 x pre-entry median Corwin-Schultz spread proxy
- impact component = k * sqrt(position_notional / ADV20)
- reference impact coefficient k = 0.01

Required stress logging:
- spread multiplier 1.0x and 2.0x
- k = 0.005, 0.01, 0.02, 0.05

Do not choose the scenario that best matches realized returns. Paper trading should record all scenarios alongside actual observed execution data when available.

## 7. Actual execution logging

For every signal, including skipped signals, create one immutable row in `paper_trade_log.csv`.

Before entry, populate all fields through `expected_rt_cost_*`. After the market open, record the paper fill or actual executable quote snapshot. At day-20 close, record exit information and realized paper return.

Expected cost and observed cost must remain separate fields. Never overwrite expected cost after observing the outcome.

## 8. Required skip reasons

Use only the following operational skip codes unless this document is formally versioned:
- none
- skipped_min_order
- skipped_slot
- skipped_cash
- data_unavailable
- filing_timestamp_ambiguous
- trading_halt_or_no_open

A skipped trade remains part of the signal log. Do not delete it from the dataset.

## 9. Live/paper review metrics

Report at minimum:
- number of FCF High signals
- number and percentage traded
- skip counts by reason
- median position notional
- median participation rate vs ADV20
- median expected round-trip cost under 1x/k=0.01 and 2x/k=0.01
- median observed entry slippage when observable
- median observed exit slippage when observable
- median and mean net R20
- win rate
- >= +20% rate
- <= -20% rate
- maximum concurrent positions

Do not combine historical and modern periods into one CAGR. For paper trading, report the paper period separately from both historical and modern backtest evidence.

## 10. Change control

Any change to signal criteria, ranking, entry timing, 20-day holding period, 3-slot cap, 5% ADV20 limit, cost-proxy definition, or minimum-order convention requires a dated change-log entry before the next signal is processed.

Research bugs require recomputation of all dependent outputs. Do not patch only the narrative.

## 11. Current interpretation

Execution robustness passed the pre-entry proxy stress test in the frozen 30-event FCF High sample: the direction of results remained positive across 1x/2x spread-proxy multipliers and impact sensitivities, while the main historical constraint was low liquidity/minimum practical order size rather than the 3-slot cap.

This does not establish live investability. The next evidence to collect is paper/live execution data under the frozen protocol above.