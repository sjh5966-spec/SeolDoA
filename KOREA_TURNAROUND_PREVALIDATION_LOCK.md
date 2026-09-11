# Korea Turnaround — Pre-Validation Lock

Status: **Development-selected, locked before Validation**

This file records the Korea-specific thresholds chosen using Development data only. It is intentionally created before opening the 2021–2022 Validation window. Validation may accept or reject this specification, but must not be used to retune these thresholds. The 2023+ modern OOS remains untouched.

## Development window

- 2015–2020 preregistered Development window.
- Threshold selection evidence used here is the complete and quality-controlled 2017–2020 quarterly accounting / market sample. 2015–2016 remain robustness-extension years because 2015 XBRL coverage is materially weaker and 2016 is needed as prior-year accounting for 2017.

## Base A accounting condition

A candidate must satisfy, on comparable statement basis:

1. current pure-quarter operating profit > 0;
2. same fiscal quarter one year earlier operating profit <= 0;
3. exact latest-four-pure-quarter TTM net income < 0;
4. quarter-end total equity > 0.

CFS is preferred; OFS is explicit fallback only when CFS is unavailable. No silent basis mixing.

## Development-selected Korea filter

The primary Korea filter to carry into Validation is:

- PIT market cap <= **KRW 50 billion**;
- current pure-quarter FCF / PIT market cap >= **0%**;
- YoY pure-quarter FCF improvement / PIT market cap >= **5%**.

These are Korea-specific thresholds selected independently. U.S. thresholds are not imported.

### Why this condition was selected

Among neighboring Development-only alternatives, this condition provided the best balance of sample size, cross-year stability, downside control, and resistance to obvious in-sample overfitting.

2017–2020 clean observations under this condition:

- n = 42
- median R20 = +9.26%
- mean R20 = +13.70%
- win rate = 83.3%
- R20 >= +20% = 21.4%
- R20 <= -20% = 0.0%
- bootstrap 95% CI for median R20 ≈ +5.09% to +11.99%

Year-by-year median R20:

- 2017: n=7, +5.59%
- 2018: n=8, +8.32%
- 2019: n=15, +12.15%
- 2020: n=12, +9.71%

Neighbor checks:

- KRW 40B + current FCF>=0 + YoY FCF improvement>=5: n=27, median +9.32% (smaller sample, little median benefit)
- KRW 60B + current FCF>=0 + YoY FCF improvement>=5: n=54, median +6.37% (larger sample, weaker effect and weaker 2017)
- KRW 50B + current FCF>=0 + YoY improvement>=0: n=56, median +6.89% (weaker quality filter)
- KRW 50B + current FCF>=0 + YoY improvement>=10: n=26, median +10.18%, 100% wins (too small and more vulnerable to overfit; not selected)

Therefore the 50B / 0% / 5% condition is selected rather than the numerically highest in-sample grid point.

## Signal and execution rules

- Signal date target remains the earliest confirmed preliminary/earnings disclosure containing the relevant quarterly operating-profit information; if unavailable, use the DART periodic filing receipt.
- Development multiyear threshold selection used the conservative periodic-report receipt fallback for reproducibility. Exact preliminary-date reconstruction remains a signal-timing robustness check and must not change the locked thresholds.
- PIT market cap = last trading-day close strictly before signal date.
- Entry = first tradable KRX open strictly after signal date, requiring Open>0, Volume>0 and Amount>0.
- Primary return = R20.
- Corporate-action-contaminated R20 observations are excluded from the clean primary statistic.
- No stop loss, take profit, trailing stop, or day-10 exit is introduced at this stage.

## Validation rule

The 2021–2022 Validation window is to be checked once using this locked specification. Do not tune market-cap, FCF, holding-period, exit, slot, or liquidity thresholds from Validation results.

Possible outcomes:

- **Pass:** Validation remains directionally consistent and economically meaningful; then freeze the final Korea spec before opening 2023+ OOS.
- **Fail:** do not optimize on Validation. Record failure and either abandon the primary specification or restart a clearly separated new research generation without using 2023+ OOS.

## OOS protection

2023+ data must remain untouched until after the Validation decision and final frozen spec are recorded.
