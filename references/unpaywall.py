import urllib.request,urllib.parse,json,pathlib
for doi in ['10.3390/s21030853','10.1631/jzus.a2100598','10.1155/2021/8699362','10.1016/j.jpse.2022.100074']:
 u='https://api.unpaywall.org/v2/'+doi+'?email=research@example.com'
 try:
  d=json.load(urllib.request.urlopen(u)); print(doi, d.get('is_oa'), (d.get('best_oa_location') or {}).get('url_for_pdf'), (d.get('best_oa_location') or {}).get('url'))
 except Exception as e: print(doi,type(e).__name__,e)
