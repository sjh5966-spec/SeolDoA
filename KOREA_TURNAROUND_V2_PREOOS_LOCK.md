# Korea Turnaround V2 — Pre-OOS Lock

Status: FROZEN BEFORE ANY 2023+ OOS ACCESS

## Research-generation boundary
- V1 remains frozen as FAIL and is not modified.
- V2 treats all previously observed 2021-2022 results as Development/Research, not validation.
- 2023+ filings, prices, and returns remain unopened at the time of this lock.

## Frozen V2 rule
1. Universe: historical KOSPI/KOSDAQ securities represented by the existing pre-OOS research pipeline.
2. PIT market capitalization: <= KRW 50B measured immediately before the signal.
3. Turnaround signal: pure-quarter operating profit has improved year-over-year, i.e. current-quarter operating profit minus same-quarter prior-year operating profit > 0. This is intentionally continuous/state-agnostic: it allows operating-loss narrowing, loss-to-profit turns, and profit expansion. There is no requirement that current operating profit or FCF be positive.
4. FCF: not a hard eligibility requirement. FCF improvement may be retained only as a diagnostic/secondary confirmation in post-analysis; it must not be used to change this frozen primary rule before OOS.
5. Signal timing: use the same PIT periodic-disclosure timing convention as the pre-OOS research pipeline.
6. Entry: first tradable KRX open strictly after the signal date.
7. Primary holding period: R20 only.
8. Corporate-action-contaminated R20 observations: excluded using the same pre-OOS handling convention.
9. No liquidity threshold, alternate market-cap threshold, alternate holding period, exit rule, ranking threshold, or FCF threshold may be introduced before the first 2023+ OOS evaluation.

## Why this rule was selected
The V2 exploration run 34794505921 showed that the broad operating-profit-improvement family had enough breadth and cross-year stability to avoid the V1 two-event problem without relying on a fitted numerical threshold.

Pre-OOS evidence for PIT market cap <= KRW 50B and YoY operating-profit improvement > 0:
- n = 365
- median R20 = +0.982%
- mean R20 = +3.609%
- win rate = 55.07%
- >= +20% = 8.49%
- <= -20% = 3.01%
- 2021: n=128, median +3.964%, mean +7.060%, win rate 57.03%
- 2022: n=237, median +0.802%, mean +1.746%, win rate 54.01%
- KOSDAQ: n=317, median +1.247%, mean +2.939%, win rate 54.89%
- KOSPI: n=48, median +0.893%, mean +8.034%, win rate 56.25%

State-transition diagnostics were directionally supportive but were not selected as separate hard filters:
- operating-profit loss-to-profit turn: n=137, median +2.536%, mean +5.539%, win 57.66%; positive median in both 2021 and 2022
- operating-profit expansion while already profitable: n=111, median +1.961%, mean +3.167%, win 62.16%; positive median in both 2021 and 2022
- dual operating-profit + FCF improvement: n=53, median +1.852%, mean +6.374%, win 60.38%, but materially narrower and with weaker high-liquidity subgroup stability
- FCF-only improvement was less stable across years, so it is not frozen as the primary V2 condition.

## Interpretation
This lock deliberately prefers a simple sign-based improvement rule over an optimized magnitude cutoff. The purpose is to test whether a broad economic-improvement effect survives genuinely unseen 2023+ OOS data, not to maximize Development-period backtest returns.

Do not open or use 2023+ OOS until this lock is present in the repository. Once OOS is opened, this rule must not be retuned based on those OOS results.