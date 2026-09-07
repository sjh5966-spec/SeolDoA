from pathlib import Path
import sys
import pandas as pd

LOG = Path(sys.argv[1] if len(sys.argv) > 1 else 'paper_trade_log.csv')
TEMPLATE = Path('paper_trade_log_template.csv')

ALLOWED_SKIP = {
    'none','skipped_min_order','skipped_slot','skipped_cash','data_unavailable',
    'filing_timestamp_ambiguous','trading_halt_or_no_open'
}

required = list(pd.read_csv(TEMPLATE, nrows=0).columns)
if not LOG.exists():
    raise SystemExit(f'missing log file: {LOG}')

df = pd.read_csv(LOG)
missing = [c for c in required if c not in df.columns]
extra = [c for c in df.columns if c not in required]
if missing:
    raise SystemExit(f'missing columns: {missing}')
if extra:
    raise SystemExit(f'unexpected columns: {extra}')

errors = []
for i, r in df.iterrows():
    row = i + 2
    skip = str(r.get('skip_reason','')).strip()
    if skip not in ALLOWED_SKIP:
        errors.append(f'row {row}: invalid skip_reason={skip!r}')

    try:
        adv = float(r['adv20_dollar'])
        planned = float(r['planned_notional'])
        if pd.notna(adv) and pd.notna(planned) and planned > 0.05 * adv + 1e-9:
            errors.append(f'row {row}: planned_notional exceeds 5% ADV20')
    except Exception:
        pass

    try:
        equity = float(r['portfolio_equity_pre_entry'])
        planned = float(r['planned_notional'])
        if pd.notna(equity) and pd.notna(planned) and planned > equity / 3 + 1e-9:
            errors.append(f'row {row}: planned_notional exceeds one-third portfolio equity')
    except Exception:
        pass

    try:
        slots = int(r['slot_count_pre_entry'])
        if slots < 0 or slots > 3:
            errors.append(f'row {row}: slot_count_pre_entry outside 0..3')
        if slots >= 3 and skip == 'none':
            errors.append(f'row {row}: trade marked executable with no free slot')
    except Exception:
        pass

    if skip == 'none':
        try:
            min_order = float(r['chosen_min_order'])
            planned = float(r['planned_notional'])
            if pd.notna(min_order) and pd.notna(planned) and planned < min_order:
                errors.append(f'row {row}: planned_notional below chosen_min_order without skip')
        except Exception:
            pass

if errors:
    print('\n'.join(errors))
    raise SystemExit(1)

print(f'OK: {len(df)} rows, schema and frozen execution constraints passed')
