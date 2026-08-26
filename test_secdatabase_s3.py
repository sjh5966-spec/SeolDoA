import duckdb,sys
con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs")
con.execute("SET s3_region='us-east-1'")
con.execute("SET s3_url_style='path'")
con.execute("SET s3_endpoint='s3.amazonaws.com'")
for path in [
 's3://dataset.secdatabase.com/sec_financial_statements/parquet/20200930/data_point/*',
 'https://dataset.secdatabase.com.s3.amazonaws.com/sec_financial_statements/parquet/20200930/data_point/*'
]:
    try:
        print('TRY',path)
        print(con.execute(f"SELECT COUNT(*),MIN(filing_date),MAX(filing_date) FROM read_parquet('{path}')").fetchone())
        sys.exit(0)
    except Exception as e:
        print(type(e).__name__,repr(e))
sys.exit(1)
