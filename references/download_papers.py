import urllib.request, urllib.parse, json, pathlib, re, time
root=pathlib.Path('references/papers'); root.mkdir(parents=True,exist_ok=True)
rows=[]
for line in pathlib.Path('references/paper_list.tsv').read_text(encoding='utf-8').splitlines():
 doi,title=line.split('|',1); doi=doi.rsplit('/',1)[-1]; rec={'title':title,'doi':doi,'status':'not_downloaded','url':'','file':''}
 try:
  data=json.load(urllib.request.urlopen('https://api.openalex.org/works/https://doi.org/'+urllib.parse.quote(doi,safe=''),timeout=20)); oa=data.get('open_access') or {}; loc=data.get('best_oa_location') or {}; url=loc.get('pdf_url') or oa.get('oa_url')
  rec['url']=url or ('https://doi.org/'+doi)
  if url and url.lower().endswith('.pdf'):
   path=root/(re.sub(r'[^A-Za-z0-9._-]+','_',title)[:90]+'.pdf')
   try:
    req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 research downloader'})
    with urllib.request.urlopen(req,timeout=40) as resp, open(path,'wb') as f: f.write(resp.read())
    if path.stat().st_size>10000: rec.update(status='downloaded',file=str(path),bytes=path.stat().st_size)
    else: path.unlink(missing_ok=True); rec['status']='url_not_pdf_or_too_small'
   except Exception as e: rec['status']='download_failed: '+type(e).__name__
  else: rec['status']='no_open_pdf'
 except Exception as e: rec['status']='metadata_failed: '+type(e).__name__
 rows.append(rec); time.sleep(.2)
pathlib.Path('references/paper_downloads.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
for r in rows: print(r['status'], '|', r['title'], '|', r['file'] or r['url'])
