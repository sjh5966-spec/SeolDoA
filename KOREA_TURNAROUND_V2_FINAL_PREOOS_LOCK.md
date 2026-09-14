# Korea Turnaround V2 — FINAL PRE-OOS LOCK

Locked before any 2023+ V2 OOS accounting, filings, market prices, or returns are accessed.

## Research status

V1 remains frozen FAIL and is not modified.
V2 Development/Research used signal dates in 2021-2022 only.
The V2 research sequence examined operating-profit improvement, magnitude ranks, size ranks, market benchmarks, and a same-market matched-cap benchmark. No 2023+ data were used for any of those choices.

## Final frozen eligibility rule

An event is eligible only when all conditions below are true:

1. Security is KOSPI or KOSDAQ common equity represented in the historical marcap universe.
2. Point-in-time market capitalization immediately before the DART disclosure is <= KRW 50,000,000,000.
3. Current pure-quarter operating profit is greater than operating profit in the same fiscal quarter one year earlier.
4. Operating-profit improvement magnitude is at least 5% of point-in-time market capitalization:

   `OP_IMPROVEMENT_PCT = (current pure-quarter operating profit - prior-year same-quarter pure-quarter operating profit) / PIT market cap * 100 >= 5.0`

5. Current profitability itself does NOT need to be positive. Loss narrowing, loss-to-profit transitions, and positive-profit expansion all qualify if the magnitude gate is met.
6. FCF is NOT an eligibility requirement.
7. Liquidity / trading value is NOT an eligibility requirement.
8. Entry is the first tradable KRX open strictly after the DART signal/disclosure date.
9. Primary outcome is R20: twentieth trading-session close relative to entry open.
10. Events whose R20 path is contaminated by a material share-count corporate action (same >20% share-count-change guard used in Development) are excluded.

## Portfolio priority when more signals exist than desired slots

Eligibility is governed only by the rules above. If portfolio capacity requires prioritization among simultaneously available eligible signals:

1. higher `OP_IMPROVEMENT_PCT` ranks first;
2. smaller PIT market capitalization is the secondary tie-breaker.

No additional accounting, valuation, FCF, revenue, or liquidity filters may be introduced for the one-time OOS test.

## Why 5.0% is frozen

Development quintiles showed the strongest concentration in the highest operating-profit-improvement quintile. Its empirical boundary was approximately 5.2%. The final cutoff is deliberately rounded to 5.0% rather than retaining a sample-specific decimal threshold. This is still a Development-derived enhancement and is therefore NOT an independent result until the one-time OOS test is opened after this lock.

## Development evidence used to authorize OOS

Among 365 V2 operating-profit-improvement events in 2021-2022, the strongest improvement quintile had n=73, median R20 about +9.68%, and win rate about 72.6%.

Same-market KOSPI/KOSDAQ benchmark adjustment:
- matched-period market-excess median about +9.76%
- market-excess win rate about 82.2%
- 2021 excess median about +10.29%
- 2022 excess median about +9.76%

Same-market, nearest-PIT-market-cap matched benchmark (20 clean peers; peer median R20):
- n=73
- matched-cap excess median +8.10%
- matched-cap excess win rate 75.3%
- 2021 matched-cap excess median +9.45%, win 77.3%
- 2022 matched-cap excess median +6.80%, win 74.5%

The matched-cap benchmark therefore indicates that the Development result is not explained solely by broad-market or generic micro-cap performance.

## One-time OOS protocol

After this file is committed, one-time OOS may be opened.

Frozen primary OOS signal window: DART signal dates 2023-01-01 through 2025-12-31.
- 2026 may be used only as needed to mature R20 for late-2025 signals or as accounting context disclosed before/within the signal rule where methodologically necessary; signals dated in 2026 are not part of the primary OOS.
- Signal-date logic, not fiscal-year labels, determines OOS membership.
- No threshold retuning, no filter additions, and no alternate holding-period selection after OOS is seen.

Primary pass/fail emphasis:
1. adequate eligible sample size;
2. positive median R20;
3. >50% positive R20 rate;
4. positive median excess R20 versus same-market benchmark;
5. positive median excess R20 versus matched-cap peers where feasible;
6. reasonable stability across 2023, 2024, and 2025 signal years rather than dependence on one year or a few outliers.

This document is the audit boundary: all OOS access must occur after this commit.
