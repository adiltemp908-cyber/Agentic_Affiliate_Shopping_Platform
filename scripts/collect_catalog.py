"""Resumable, bounded current-catalog expansion; two independent retailer workers."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
import json
from pathlib import Path
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shortlist import config
from shortlist.acquisition import CatalogBuilder
from shortlist.catalog import Catalog
from shortlist.ingest import Collector
from shortlist.search import Search

def plan(amazon_limit,flipkart_pages,profile='broad'):
    sources=json.loads((config.ROOT/'config/catalog_sources.json').read_text(encoding='utf-8'))
    return [{**job,**({'limit':amazon_limit} if job['retailer']=='Amazon' else {'pages':flipkart_pages})}
            for job in sources[profile]]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--amazon-limit',type=int,default=8)
    parser.add_argument('--flipkart-pages',type=int,default=8)
    parser.add_argument('--report',type=Path,default=config.ROOT/'reports/large-catalog-expansion.json')
    parser.add_argument('--plan-only',action='store_true')
    parser.add_argument('--retailer',choices=['Amazon','Flipkart','both'],default='both')
    parser.add_argument('--profile',choices=['broad','extended'],default='broad',help='Extended adds OLED TVs and previously uncollected departments.')
    parser.add_argument('--start-after',help='Resume after this exact job ID, using a separate report.')
    parser.add_argument('--request-delay',type=float,default=3,help='Minimum seconds between retailer page requests.')
    parser.add_argument('--skip-index',action='store_true',help='Defer indexing when another collection worker is still active.')
    args=parser.parse_args()
    if not 1<=args.amazon_limit<=30 or not 1<=args.flipkart_pages<=10:parser.error('Use 1–30 Amazon listings and 1–10 Flipkart pages per category.')
    if not 3<=args.request_delay<=60:parser.error('Request delay must be 3–60 seconds.')
    jobs=plan(args.amazon_limit,args.flipkart_pages,args.profile)
    if args.retailer!='both':jobs=[job for job in jobs if job['retailer']==args.retailer]
    if args.start_after:
        position=next((i for i,job in enumerate(jobs) if job['id']==args.start_after),None)
        if position is None:parser.error('--start-after does not match a job in this retailer plan.')
        jobs=jobs[position+1:]
    if args.plan_only:
        print(json.dumps({'amazon_searches':sum(j['retailer']=='Amazon' for j in jobs),
                          'amazon_listing_attempts_max':sum(j.get('limit',0) for j in jobs),
                          'flipkart_categories':sum(j['retailer']=='Flipkart' for j in jobs),
                          'flipkart_pages_max':sum(j.get('pages',0) for j in jobs),
                          'categories':sorted({j['category'] for j in jobs})},indent=2));return
    config.initialize();catalog=Catalog(config.DATA/'catalog.sqlite3');lock=threading.RLock()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    report=json.loads(args.report.read_text(encoding='utf-8')) if args.report.exists() else {
        'started_at':datetime.now(timezone.utc).isoformat(),'before':catalog.stats(),'jobs':jobs,'completed':{},'worker_stops':{}}
    if report['jobs']!=jobs:raise ValueError('This report has a different collection plan. Use a different --report path.')
    report['worker_stops']={};report['status']='running'

    def save():
        report['updated_at']=datetime.now(timezone.utc).isoformat()
        temp=args.report.with_suffix('.tmp');temp.write_text(json.dumps(report,indent=2),encoding='utf-8');temp.replace(args.report)

    def worker(retailer):
        collector=Collector(catalog) if retailer=='Amazon' else CatalogBuilder(catalog)
        collector.session.trust_env=False
        collector.min_delay=args.request_delay
        failures=0
        for job in [j for j in jobs if j['retailer']==retailer]:
            with lock:
                if job['id'] in report['completed']:continue
            try:
                result=collector.discover(job['url'],job['limit']) if retailer=='Amazon' else collector.collect(job['url'],job['pages'],job['category'])
                failed=not result.get('imported')
                outcome={'status':'no_imports' if failed else 'ok',**result}
            except Exception as exc:failed=True;outcome={'status':'failed','detail':str(exc)[:500]}
            failures=failures+1 if failed else 0
            with lock:
                report['completed'][job['id']]=outcome
                report['progress']={'done':len(report['completed']),'total':len(jobs)}
                save()
                print(json.dumps({'retailer':retailer,'category':job['label'],'status':outcome['status'],
                                  'imported':outcome.get('imported',0),'recent_priced':outcome.get('recent_priced'),
                                  **report['progress']}),flush=True)
            if failures>=3:
                with lock:report['worker_stops'][retailer]='Three consecutive unsuccessful categories; stopped further requests.';save()
                break
        collector.session.close()

    save()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures=[executor.submit(worker,retailer) for retailer in ['Amazon','Flipkart']]
        for future in futures:future.result()
    report['after']=catalog.stats()
    report['new_offer_records']=report['after']['offers']-report['before']['offers']
    report['status']='partial' if len(report['completed'])<len(jobs) else 'complete'
    save()
    report['index']=None if args.skip_index else Search(catalog).build();save()
    print(json.dumps({'status':report['status'],'new_offer_records':report['new_offer_records'],
                      'retailer_coverage':report['after']['retailer_coverage'],'index':report['index']}),flush=True)


if __name__=='__main__':main()
