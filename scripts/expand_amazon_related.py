"""Bounded Amazon link discovery from checked product pages; no search-page dependency."""
import argparse
from collections import deque
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shortlist.catalog import Catalog,freshness
from shortlist.config import DATA,ROOT
from shortlist.ingest import Collector


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=40)
    parser.add_argument('--report',type=Path,default=ROOT/'reports/amazon-related-expansion.json')
    args=parser.parse_args()
    if not 1<=args.limit<=100:parser.error('Choose 1–100 product-page attempts.')
    catalog=Catalog(DATA/'catalog.sqlite3');rows=catalog.records()
    recent={r['url'] for r in rows if r['retailer']=='Amazon' and freshness(r)=='recent'}
    queue=deque();queued=set()
    for category in ['television','laptop','smartphone','clothing','furniture','cookware','bedding','headphones','appliance','bag']:
        seed=next((r for r in rows if r['retailer']=='Amazon' and r['category']==category
                   and r['url'] in recent and r['price'] and r['availability']!='out_of_stock'),None)
        if seed:queue.append((seed['url'],None));queued.add(seed['url'])
    collector=Collector(catalog);collector.session.trust_env=False;collector.min_delay=6;collector.capture_product_links=True;collector.skip_service_plans=True
    report={'before':catalog.stats(),'attempts':[],'stop_reason':None,'scope':'Product links only; each imported price is checked on its own product page.'}
    def save():
        args.report.parent.mkdir(parents=True,exist_ok=True);temporary=args.report.with_suffix('.tmp')
        temporary.write_text(json.dumps(report,indent=2),encoding='utf-8');temporary.replace(args.report)
    blocked=0
    while queue and len(report['attempts'])<args.limit:
        url,parent=queue.popleft()
        try:
            row=collector.refresh(url)
            outcome={'url':url,'discovered_from':parent,'status':'ok','category':row.category,'price':row.price,'availability':row.availability}
            added=0
            for candidate in collector.last_product_links:
                if candidate in queued or candidate in recent:continue
                queue.append((candidate,url));queued.add(candidate);added+=1
                if added>=4 or len(queued)>=args.limit*4:break
            outcome['queued_links']=added;blocked=0
        except Exception as exc:
            detail=str(exc);outcome={'url':url,'discovered_from':parent,'status':'failed','detail':detail[:500]}
            blocked=blocked+1 if re.search(r'HTTP (?:403|429|5\d\d)|challenge|captcha|disallowed|Could not verify|Connection|Timeout|NameResolution',detail,re.I) else 0
        report['attempts'].append(outcome);save();print(json.dumps(outcome),flush=True)
        if blocked>=3:report['stop_reason']='Three consecutive access/network failures; no more requests.';break
    collector.session.close();report['after']=catalog.stats();save()
    print(json.dumps({'attempted':len(report['attempts']),'stop_reason':report['stop_reason'],
                     'amazon_coverage':report['after']['retailer_coverage']['Amazon']}),flush=True)


if __name__=='__main__':main()
