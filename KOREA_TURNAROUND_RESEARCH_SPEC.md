# Korea Microcap Operating-Profit Turnaround Research

Status: preregistered research track, separate from the frozen U.S. strategy.
Date: 2026-09-08 (Asia/Seoul)

## 1. Research question

Test whether Korean small/micro-cap stocks show a reproducible post-disclosure repricing effect after a year-over-year quarterly operating-profit turnaround, and whether strong cash-flow improvement identifies a higher-quality subset.

This is an independent market replication. U.S. thresholds are NOT imported as Korean thresholds.

## 2. Core hypothesis

The economic mechanism is delayed information incorporation / PEAD-like underreaction in hard-to-value, low-attention and/or illiquid stocks. Korean-market literature documents PEAD and links it to investor underreaction and retail trading. The research test is whether an operating-profit loss-to-profit transition plus cash-flow confirmation creates a particularly strong short-horizon event signal.

## 3. Universe

Primary universe:
- KOSPI and KOSDAQ common stocks.
- KONEX excluded from the primary test.
- ETFs, ETNs, SPACs, preferred shares, REIT-like non-comparable vehicles and funds excluded where identifiable.
- Delisted names must remain in the historical universe when data are available; do not build the universe from today's survivors.

The primary small-cap boundary is not frozen yet. First report results by contemporaneous market-cap buckets/quantiles and only freeze a Korean cutoff using the development period.

## 4. Point-in-time event date

The signal date is the earliest timestamp/date at which the relevant earnings information became public.

Priority:
1. Preliminary/earnings-result disclosure that contains the relevant quarterly operating-profit information, if it predates the periodic report.
2. Otherwise the DART periodic filing receipt date/time.

Never use a later periodic report as the signal date if materially equivalent earnings information was already publicly disclosed.

DART receipt number and receipt date must be retained for auditability. If exact intraday time is unavailable from the API used, entry is forced to the first trading session strictly after the confirmed public disclosure date; no same-day entry.

## 5. Accounting basis

Primary accounting basis:
- Consolidated financial statements where available and economically comparable.
- Standalone statements used only when consolidated statements are unavailable, with an explicit basis flag.
- Do not silently mix consolidated and standalone observations for the same issuer/event.

Primary profitability item:
- Quarterly operating profit (영업이익), not U.S.-style EBIT taxonomy.

Quarter reconstruction:
- Q1: reported quarterly amount.
- Q2: H1 cumulative less Q1 when only YTD flow is reported.
- Q3: 9M cumulative less H1 when only YTD flow is reported.
- Q4: annual cumulative less 9M, provided annual disclosure timing is treated correctly and there is no earlier preliminary result disclosure.

Cash-flow items are reconstructed on the same pure-quarter basis where possible.

## 6. Korea Base A (first test; no optimized thresholds)

At the public disclosure event:
- point-in-time market cap is positive and observable using only pre-entry information;
- current pure-quarter operating profit > 0;
- same fiscal quarter one year earlier operating profit <= 0;
- trailing-twelve-month net income < 0;
- quarter-end equity > 0.

Do NOT add the U.S. Candidate3 filters to the first Korean test.

## 7. Cash-flow quality diagnostics

For every Base A event compute, when data are available:
- current quarterly FCF / point-in-time market cap;
- YoY change in quarterly FCF / point-in-time market cap;
- absolute TTM net loss / point-in-time market cap.

FCF baseline definition:
- operating cash flow minus cash capital expenditure.
- definition and DART account mapping must be frozen before examining OOS performance.

The U.S. thresholds 3.591639% and 11.938595% are NOT Korean decision thresholds. They may be shown only as a cross-market reference table after the primary Korean analysis.

## 8. Entry and returns

Entry:
- first KRX trading-day open strictly after the earliest confirmed public disclosure date.

Primary horizon:
- R20 = day-20 close / entry open - 1, with entry day = day 0.

Diagnostics only until independently justified:
- R5, R10, R60, R120.
- MFE/MAE over the first 20 sessions.

No stop-loss, take-profit, trailing-stop or day-10 no-response rule in the first replication.

## 9. Time splits and anti-overfitting rules

Because OpenDART disclosure search provides robust API-era coverage from 2015 onward, use:
- Development: 2015-01-01 through 2020-12-31.
- Validation: 2021-01-01 through 2022-12-31.
- Untouched modern OOS: 2023-01-01 through the latest mature event date.

The OOS period is not used to choose market-cap cutoffs, FCF thresholds, holding period, exit rules, slot count or liquidity limits.

Any threshold selection must be made on Development only, checked once on Validation, then frozen before OOS is opened.

## 10. Primary outputs

For Base A and any later frozen Korean quality subset, separately by era report:
- event count;
- median and mean R20;
- win rate (R20 > 0);
- share >= +20%;
- share <= -20%;
- 10th/25th/75th/90th percentiles;
- bootstrap confidence interval for median R20;
- yearly event counts and yearly median R20;
- leave-one-year-out median R20;
- KOSPI vs KOSDAQ split;
- market-cap bucket split;
- liquidity bucket split.

Never combine separated eras into a single CAGR.

## 11. Execution-realism outputs

Pre-entry only:
- ADV20 KRW;
- median daily traded value 20;
- Amihud-style illiquidity;
- suspension/zero-volume flags;
- price-limit/VI-adjacent diagnostics where observable.

Capacity simulation is performed only after the signal is shown to replicate. Initial execution assumptions are diagnostic, not optimized filters.

## 12. Korea-specific confounders / exclusions to audit

At minimum flag:
- trading suspensions;
- management/designation issues where point-in-time data are available;
- delisting status and delisting-return handling;
- capital impairment/equity issues;
- rights offerings, CB/BW and other financing events near the earnings disclosure;
- stock splits/reverse splits;
- SPAC mergers;
- preliminary earnings disclosure preceding the periodic report;
- revised/corrected disclosures;
- consolidated vs standalone statement basis changes;
- fiscal-year-end changes.

These are diagnostics first. Do not turn them into return-optimized filters without preregistration.

## 13. Data source contract

Fundamentals/disclosures:
- Financial Supervisory Service OpenDART APIs.
- Store corp_code, stock_code, rcept_no, rcept_dt, report name/type, statement basis and source account identifiers.

Prices/market cap/listing universe:
- KRX-derived daily data, with historical-date universe construction so delisted names are not dropped by construction.

Every derived event must be reproducible from cached raw extracts. Never rewrite raw source files in place.

## 14. Freeze rules

Until Development results are generated:
- no Korean market-cap cutoff is fixed;
- no Korean FCF threshold is fixed;
- no additional accounting-strength filter is fixed;
- R20 is the primary horizon solely because this is an independent replication of the already-frozen U.S. research hypothesis, not because Korean R20 has been inspected.

After Development/Validation choices are frozen, create a versioned `KOREA_TURNAROUND_FROZEN_SPEC.md` before opening 2023+ OOS results.

## 15. Success / failure interpretation

Strong replication:
- Base A has positive, economically meaningful R20 in Development and Validation;
- a cash-flow quality dimension improves results without relying on a handful of winners;
- the frozen rule remains positive in untouched 2023+ OOS;
- performance survives realistic liquidity/cost stress.

Weak/no replication:
- R20 effect is absent or sign-unstable across eras;
- effect exists only in highly untradeable names;
- result depends on revised disclosures/look-ahead or survivors;
- result collapses under leave-one-year-out or a few extreme winners.

A failed Korean replication is informative and must not trigger retrospective editing of the frozen U.S. strategy.