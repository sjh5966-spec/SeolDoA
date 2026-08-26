import urllib.request, zipfile, os, sys
url='https://www.sec.gov/files/dera/data/financial-statement-data-sets/2010q1.zip'
req=urllib.request.Request(url,headers={'User-Agent':'SeolDoA research backtest https://github.com/sjh5966-spec/SeolDoA','Accept-Encoding':'gzip, deflate','Host':'www.sec.gov'})
try:
    with urllib.request.urlopen(req,timeout=120) as r:
        data=r.read()
        print('status',getattr(r,'status',None),'bytes',len(data),'content-type',r.headers.get('Content-Type'))
    open('2010q1.zip','wb').write(data)
    with zipfile.ZipFile('2010q1.zip') as z:
        print('files',z.namelist())
        for n in z.namelist():
            info=z.getinfo(n); print(n,info.file_size)
except Exception as e:
    print(type(e).__name__,repr(e)); sys.exit(1)
