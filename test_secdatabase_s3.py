import duckdb,sys
con=duckdb.connect()
con.execute("INSTALL httpfs; LOAD httpfs")
con.execute("SET s3_region='us-east-1'")
con.execute("SET s3_url_style='path'")
con.execute("SET s3_endpoint='s3.amazonaws.com'")
path='s3://dataset.secdatabase.com/sec_financial_statements/parquet/20200930/data_point/*.parquet'
try:
    print(con.execute(f"SELECT COUNT(*),MIN(filing_date),MAX(filing_date) FROM read_parquet('{path}')").fetchone())
except Exception as e:
    print(type(e).__name__,repr(e));sys.exit(1)
