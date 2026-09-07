# Paper Trading Change Log

This log records operational changes only. Research signal definitions remain frozen unless explicitly stated otherwise.

## 2026-09-07 — paper-v1-2026-09-07

- Instantiated the frozen Candidate3 / FCF High paper-trading protocol from the research handoff.
- Initial paper capital fixed at USD 15,000; 3 concurrent slots; target <= one third equity; position <= 5% strictly pre-entry ADV20; exit day-20 close with no interim stop/take-profit.
- Set paper minimum practical order to USD 500 before any paper signal was logged. This is an operational convention selected after reviewing the pre-existing sensitivity grid, so it must NOT be used as evidence of strategy quality and must not be changed in response to paper returns.
- Corwin-Schultz-style OHLC proxy documented as a non-overnight-adjusted proxy. Primary spread component is 1.0x proxy; 2.0x is conservative stress. Reference impact k=0.01 with mandatory k=0.005/0.02/0.05 sensitivities.
- Filing-time policy clarified: when confirmed filing_date exists and entry is the first trading session strictly after that date, missing exact acceptance time alone does not block paper execution. Exact timestamp remains an audit field when available. This clarification does not permit same-day entry.
- Added source freshness logging so a zero-signal scan is distinguished from a stale-source scan.
- Added automated paper portfolio lifecycle: PLANNED -> OPEN -> CLOSED, with SKIPPED retained; entry uses recorded entry-session open and exit uses the 20th subsequent trading-session close.
- Fixed lifecycle persistence so day-20 exit dates can be filled when they later become observable and new ledger/summary files are committed even when initially untracked.
