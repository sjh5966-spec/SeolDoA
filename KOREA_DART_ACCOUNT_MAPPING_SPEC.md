# Korea OpenDART Account Mapping Spec

Status: **pre-OOS accounting mapping freeze**

This file freezes the accounting-row selection rules used to construct the Korean turnaround research dataset. It is based only on the OpenDART schema audit using years <= 2022. It does not inspect 2023+ Korean returns.

## 1. Statement basis

- Prefer consolidated financial statements (`CFS`) whenever the relevant company-period has usable CFS data.
- Use separate statements (`OFS`) only when CFS is unavailable for that company-period.
- Persist the chosen basis for every observation and never silently mix CFS and OFS within a YoY comparison or TTM chain.
- A change in statement basis is a diagnostic flag and the affected event is not treated as clean until comparability is verified.

## 2. Statement-section restrictions

Account labels alone are not sufficient. Candidate rows must come from the appropriate statement section (`sj_div`). This prevents broad regex matches from confusing operating profit with continuing-operation profit, equity-method profit, or cash-flow/SCE duplicates.

### Operating profit

Use only income-statement rows (`sj_div` = `IS` or equivalent income-statement section).

Preferred standardized account ID:

1. `dart_OperatingIncomeLoss`

Fallback only when the standardized ID is absent:

- exact Korean labels representing operating profit/loss, such as `영업이익`, `영업손실`, or `영업이익(손실)`.

Do **not** use `ifrs_ProfitLossFromContinuingOperations` as operating profit even if a broad text classifier matches it.

### Net income

Use only income-statement / comprehensive-income rows representing total period profit or loss.

Preferred standardized account ID:

1. `ifrs_ProfitLoss`

Fallback exact labels may include `당기순이익(손실)`, `당기순이익`, `당기순손실`, `분기순이익(손실)`, or `반기순이익(손실)` when the standardized ID is unavailable.

Do not substitute pretax profit, parent-attributable profit, non-controlling-interest profit, equity-method profit, cash-flow reconciliation rows, or statement-of-changes-in-equity duplicates for total net income.

### Equity

Use only balance-sheet (`BS`) total equity.

Preferred standardized account ID:

1. `ifrs_Equity`

Require the row to represent total equity (`자본총계` or economically equivalent total-equity label). Do not use equity attributable only to owners of parent, other equity components, investments accounted for using the equity method, equity-and-liabilities total, or statement-of-changes-in-equity rows.

### Operating cash flow (CFO)

Use only cash-flow-statement (`CF`) rows.

Preferred standardized account ID:

1. `ifrs_CashFlowsFromUsedInOperatingActivities`

Fallback exact/equivalent Korean label: operating-activities cash flow. Do not use cash-flow reconciliation components.

### Cash CAPEX

Use only cash-flow-statement (`CF`) acquisition/purchase cash-flow rows. Baseline FCF is CFO minus cash acquisition of tangible and intangible assets.

Preferred standardized account IDs include:

- `ifrs_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities`
- `ifrs_PurchaseOfIntangibleAssetsClassifiedAsInvestingActivities`

Fallback rows must explicitly describe cash acquisition/purchase of tangible or intangible assets. Do not treat depreciation, disposals, revaluation, or non-cash additions as CAPEX.

## 3. Pure-quarter reconstruction

For flow variables (operating profit, net income, CFO, CAPEX):

- Q1 = Q1 reported amount.
- Q2 = H1 cumulative amount - Q1 cumulative amount when H1 is cumulative.
- Q3 = 9M cumulative amount - H1 cumulative amount when 9M is cumulative.
- Q4 = FY cumulative amount - 9M cumulative amount.

When OpenDART provides both current-period and cumulative fields, retain the raw fields and explicitly record which field was used. Never assume a field is pure-quarter solely from its column name; validate the period label/context first.

For stock variables such as equity, use the quarter-end balance directly; do not difference balances.

## 4. YoY and TTM comparability

- YoY operating-profit turnaround compares the same fiscal quarter one year apart.
- Require comparable statement basis and fiscal-period structure.
- TTM net income is the sum of the latest four reconstructed pure quarters.
- FCF is reconstructed at the pure-quarter level before YoY improvement is calculated.
- Fiscal-year-end changes or missing predecessor quarters are flagged rather than imputed silently.

## 5. Duplicate resolution

If multiple rows survive the rules for the same metric/company/period/basis:

1. prefer the standardized account ID above;
2. prefer the canonical statement section;
3. prefer the exact total metric over attributable/subcomponent rows;
4. otherwise mark the metric ambiguous and exclude it from the clean research sample until reviewed.

Never select a duplicate merely because it appears first in the API response.

## 6. Audit trail

Persist at minimum:

- stock_code / corp_code
- business year / report code / fiscal quarter
- CFS or OFS basis
- `sj_div`, `account_id`, `account_nm`
- raw current-period and cumulative amounts
- selected amount and reconstruction method
- source filing receipt number/date when linked to the event layer
- ambiguity/comparability flags

## 7. Frozen exclusions from mapping

The initial broad probe regex produced false-positive classes. In particular, generic matches on `Equity` and `ProfitLoss` are not valid metric definitions. The production builder must use the section + standardized-ID + exact-label hierarchy above, not the probe classifier itself.

## 8. Research guardrail

These mapping rules are frozen before inspecting 2023+ Korean OOS returns. Changes after OOS inspection must be documented as post-hoc robustness changes and cannot silently replace the primary specification.
