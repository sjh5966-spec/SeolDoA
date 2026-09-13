# Korea Turnaround — One-Time Validation Decision

Status: **FAIL — insufficient Validation replication for the locked primary specification**

Decision recorded after the one-time 2021–2022 Validation check and **before any 2023+ OOS access**.

## Locked specification evaluated

No thresholds were retuned. The Validation check used only the pre-registered rule from `KOREA_TURNAROUND_PREVALIDATION_LOCK.md`:

- PIT market cap <= KRW 50 billion;
- current pure-quarter FCF / PIT market cap >= 0%;
- YoY pure-quarter FCF improvement / PIT market cap >= 5%;
- entry at the first tradable KRX open strictly after the signal date;
- primary horizon R20;
- corporate-action-contaminated R20 excluded.

Signal dates were restricted to 2021-01-01 through 2022-12-31. Market data were restricted to 2021 and 2022. No 2023 price was read to mature late-2022 observations; such observations were censored. 2022 Q4 accounting remained excluded. 2020 Development accounting was used only as prior-year / TTM context.

## Validation evidence

Base A clean observations:

- n = 448
- median R20 = -1.42%
- mean R20 = +0.55%
- win rate = 46.0%
- >= +20% = 9.6%
- <= -20% = 4.7%
- bootstrap 95% CI for median R20 = -2.65% to +0.41%

By signal year, Base A was positive in 2021 but materially negative in 2022:

- 2021: n=210, median +2.08%, win rate 57.1%
- 2022: n=238, median -4.01%, win rate 36.1%

Locked frozen filter clean observations:

- n = 2
- median R20 = +15.96%
- mean R20 = +15.96%
- win rate = 100%
- >= +20% = 50%
- <= -20% = 0%
- bootstrap 95% CI for median R20 = +6.36% to +25.57%

However, both frozen-filter observations occurred in 2022; there were **zero** frozen-filter observations in 2021. The two observations split one KOSPI and one KOSDAQ name.

## Decision

The locked specification does **not** pass the preregistered Validation standard that Validation remain directionally consistent and economically meaningful across the 2021–2022 window. Although the two qualifying frozen-rule trades were positive, a sample of only two observations, with no 2021 representation, is insufficient to establish Validation replication or cross-year stability. Treating those two outcomes as a Pass would rely on an inadequately identified sample rather than robust out-of-sample evidence.

Therefore the one-time Validation outcome is **FAIL**, specifically an **insufficient-replication / insufficient-sample failure**, not a finding that the two frozen-rule trades themselves lost money.

No Validation threshold, holding period, exit rule, slot count, liquidity filter, or other strategy parameter is to be optimized from these results.

## Data / methodology limitations carried into the decision

- 2021 accounting coverage is below 100%, so non-random missingness may affect the count of qualifying events.
- The historical universe is based on DART Y/K periodic filers intersected with historical KOSPI/KOSDAQ market data; security-type and delisting coverage inherit those source limitations.
- Signal timing uses the conservative periodic-report receipt fallback used for Development comparability; earlier preliminary disclosures were not reconstructed for this efficacy check.

## OOS gate

2023+ OOS remains unopened. Under the preregistered rule, this failed primary specification must not be repaired using Validation or 2023+ OOS. Any further Korea research should be treated as a clearly separated new research generation while continuing to keep 2023+ OOS untouched until that new generation is independently frozen and validated.
