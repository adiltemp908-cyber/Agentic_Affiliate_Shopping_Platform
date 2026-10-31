"""Refresh a bounded, diverse sample of known Amazon URLs without search-page discovery."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from shortlist.catalog import Catalog,freshness
from shortlist.config import DATA,ROOT
from shortlist.ingest import Collector,is_laptop
from shortlist.taxonomy import infer_category


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=30)
    parser.add_argument('--report',type=Path,default=ROOT/'reports/known-amazon-refresh.json')
    args=parser.parse_args()
    if not 1<=args.limit<=100:parser.error('Choose 1–100 product pages.')
    catalog=Catalog(DATA/'catalog.sqlite3');collector=Collector(catalog)
    collector.session.trust_env=False;collector.min_delay=6
    buckets=defaultdict(list)
    for row in catalog.records():
        if row['retailer']!='Amazon' or freshness(row)=='recent' or not row.get('brand'):continue
        if row['category']!=infer_category(row['title']):continue
        if row['category']=='laptop' and not is_laptop(row['title']):continue
        buckets[row['category']].append(row)
    for rows in buckets.values():rows.sort(key=lambda r:(r['source_kind']=='historical',r['source_id']))
    # Round-robin categories; identifier order is deterministic, not a release-date claim.
    selected=[]
    for position in range(args.limit):
        for category in sorted(buckets):
            if position<len(buckets[category]):selected.append(buckets[category][position])
        if len(selected)>=args.limit:break
    report={'before':catalog.stats(),'attempts':[],'stop_reason':None}
    def save():
        args.report.parent.mkdir(parents=True,exist_ok=True)
        temporary=args.report.with_suffix('.tmp')
        temporary.write_text(json.dumps(report,indent=2),encoding='utf-8');temporary.replace(args.report)
    blocked=0
    for row in selected[:args.limit]:
        try:
            result=collector.refresh(row['url'])
            outcome={'url':row['url'],'status':'ok','category':result.category,'price':result.price,'availability':result.availability}
            blocked=0
        except Exception as exc:
            detail=str(exc)
            outcome={'url':row['url'],'status':'failed','detail':detail[:500]}
            # Removed products can return 404; this is different from source-wide refusal.
            if re.search(r'HTTP (?:403|429|5\d\d)|challenge|captcha|disallowed|Could not verify|Connection|Timeout|NameResolution',detail,re.I):blocked+=1
            else:blocked=0
        report['attempts'].append(outcome);save();print(json.dumps(outcome),flush=True)
        if blocked>=3:
            report['stop_reason']='Three consecutive access/network failures; no more requests.';break
    collector.session.close();report['after']=catalog.stats();save()
    print(json.dumps({'attempted':len(report['attempts']),'stop_reason':report['stop_reason'],
                      'amazon_coverage':report['after']['retailer_coverage'].get('Amazon')}),flush=True)


if __name__=='__main__':main()
