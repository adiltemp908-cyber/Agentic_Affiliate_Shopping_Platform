import argparse
import json
from . import config

def main():
    parser=argparse.ArgumentParser(description='Shortlist local shopping research')
    sub=parser.add_subparsers(dest='command',required=True)
    serve=sub.add_parser('serve');serve.add_argument('--port',type=int,default=config.PORT)
    legacy=sub.add_parser('import-legacy');legacy.add_argument('path');legacy.add_argument('--limit',type=int,default=250)
    imp=sub.add_parser('import');imp.add_argument('path')
    refresh=sub.add_parser('refresh');refresh.add_argument('url')
    discover=sub.add_parser('discover');discover.add_argument('url');discover.add_argument('--limit',type=int,default=12)
    sub.add_parser('index');sub.add_parser('status')
    collect=sub.add_parser('collect');collect.add_argument('url');collect.add_argument('--pages',type=int,default=3);collect.add_argument('--category')
    broad=sub.add_parser('import-broad-history');broad.add_argument('path');broad.add_argument('--per-category',type=int,default=600)
    args=parser.parse_args();config.initialize()
    if args.command=='serve':
        from .server import serve
        serve(args.port);return
    from .catalog import Catalog
    catalog=Catalog(config.DATA/'catalog.sqlite3')
    if args.command=='collect':
        from .acquisition import CatalogBuilder
        result=CatalogBuilder(catalog).collect(args.url,args.pages,args.category)
    elif args.command=='import-broad-history':
        from .acquisition import import_broad_history
        result=import_broad_history(catalog,args.path,args.per_category)
    elif args.command=='import-legacy':
        from .ingest import import_legacy
        result={'imported':import_legacy(catalog,args.path,args.limit)}
    elif args.command=='import':
        from .ingest import import_jsonl
        result={'imported':import_jsonl(catalog,args.path)}
    elif args.command=='refresh':
        from .ingest import Collector
        result=Collector(catalog).refresh(args.url).model_dump()
    elif args.command=='discover':
        from .ingest import Collector
        result=Collector(catalog).discover(args.url,args.limit)
    elif args.command=='index':
        from .search import Search
        result=Search(catalog).build()
    else:result=catalog.stats()
    print(json.dumps(result,ensure_ascii=True,indent=2))

if __name__=='__main__':main()

