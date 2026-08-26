import duckdb
con=duckdb.connect(); con.execute("INSTALL httpfs; LOAD httpfs"); con.execute("SET s3_region='us-east-1'"); con.execute("SET s3_url_style='path'"); con.execute("SET s3_endpoint='s3.amazonaws.com'")
P='s3://dataset.secdatabase.com/sec_financial_statements/parquet/20200930/data_point/*'
patterns=['%OperatingIncome%','%NetIncomeLoss%','%NetCashProvidedByUsedInOperatingActivities%','%PaymentsToAcquire%Property%','%PaymentsForAdditionsToProperty%','%StockholdersEquity%']
for pat in patterns:
    print('\nPATTERN',pat)
    q=f"""SELECT datapoint_name,COUNT(*) n,COUNT(DISTINCT cik) ciks,MIN(filing_date),MAX(filing_date),MIN(period_month),MAX(period_month)
    FROM read_parquet('{P}') WHERE datapoint_name ILIKE ? AND segment_hash IS NULL GROUP BY 1 ORDER BY n DESC LIMIT 30"""
    for r in con.execute(q,[pat]).fetchall(): print(r)
