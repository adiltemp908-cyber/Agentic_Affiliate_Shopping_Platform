import json
import os
import uuid
import threading
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from . import config
from .catalog import Catalog, canonical_url
from .schema import Listing
from .search import Search
from .local_model import LocalModel
from .workflow import ShoppingWorkflow
from .ingest import Collector
from .taxonomy import CATEGORIES
from .acquisition import CatalogBuilder

class Application:
    def __init__(self):
        config.initialize()
        self.catalog=Catalog(config.DATA/'catalog.sqlite3')
        self.search=Search(self.catalog)
        self.model=LocalModel()
        self.workflow=ShoppingWorkflow(self.search,self.model,config.DATA/'conversations.sqlite3')
        self.collector=Collector(self.catalog)
        self.builder=CatalogBuilder(self.catalog)

    def status(self):
        return {'app':'shortlist-local','catalog':self.catalog.stats(),'model':self.model.status(),'semantic_index':self.search.index_path.exists(),
                'scope':'Electronics, fashion, home and more · India · INR','categories':CATEGORIES,'affiliate_tracking':False}

def serve(port=config.PORT):
    app=Application()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def send(self,status,data,kind='application/json; charset=utf-8'):
            body=json.dumps(data,ensure_ascii=False).encode() if kind.startswith('application/json') else data
            self.send_response(status)
            self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Cache-Control','no-store')
            self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers();self.wfile.write(body)

        def safe_host(self):
            return self.headers.get('Host') in {f'127.0.0.1:{port}',f'localhost:{port}'}

        def do_GET(self):
            if not self.safe_host():return self.send(403,{'error':'Invalid host'})
            parsed=urlparse(self.path)
            if parsed.path=='/api/health':return self.send(200,{'app':'shortlist-local','ready':True})
            if parsed.path=='/api/status':return self.send(200,app.status())
            if parsed.path=='/api/sessions':return self.send(200,app.catalog.sessions())
            if parsed.path=='/api/catalog':return self.send(200,{'stats':app.catalog.stats(),'refreshes':app.catalog.refresh_log()})
            if parsed.path=='/api/session':
                session=parse_qs(parsed.query).get('id',[''])[0]
                try:uuid.UUID(session)
                except ValueError:return self.send(400,{'error':'Invalid session'})
                with app.workflow.lock:return self.send(200,app.workflow.snapshot(session))
            files={'/':('index.html','text/html; charset=utf-8'),'/app.js':('app.js','text/javascript; charset=utf-8'),'/styles.css':('styles.css','text/css; charset=utf-8')}
            if parsed.path in files:
                name,kind=files[parsed.path]
                return self.send(200,(config.ROOT/'web'/name).read_bytes(),kind)
            return self.send(404,{'error':'Not found'})

        def do_POST(self):
            if not self.safe_host():return self.send(403,{'error':'Invalid host'})
            origin=self.headers.get('Origin')
            if origin and origin not in {f'http://127.0.0.1:{port}',f'http://localhost:{port}'}:return self.send(403,{'error':'Invalid origin'})
            if self.headers.get('X-Shortlist')!='1':return self.send(403,{'error':'Missing local application header'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=2_000_000:raise ValueError('Request body must be between 1 byte and 2 MB.')
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict):raise ValueError('Expected a JSON object.')
                if self.path=='/api/shutdown':
                    self.send(200,{'stopping':True})
                    threading.Thread(target=server.shutdown,daemon=True).start()
                    return
                if self.path=='/api/search':
                    message=str(data.get('message','')).strip()
                    if not message or len(message)>2000:raise ValueError('Enter a request between 1 and 2,000 characters.')
                    session=str(data.get('session_id') or uuid.uuid4());uuid.UUID(session)
                    method=data.get('method','hybrid')
                    if method not in {'hybrid','bm25','semantic'}:raise ValueError('Unknown retrieval method.')
                    result=app.workflow.run(session,message,bool(data.get('use_model',True)),bool(data.get('include_historical',False)),method)
                    history=result.get('history',[])
                    app.catalog.remember(session,history[0]['content'] if history else message)
                    return self.send(200,result)
                if self.path=='/api/index':return self.send(200,app.search.build())
                if self.path=='/api/discover':return self.send(200,app.collector.discover(str(data.get('url','')),int(data.get('limit',8))))
                if self.path=='/api/collect':return self.send(200,app.builder.collect(str(data.get('url','')),int(data.get('pages',2)),data.get('category')))
                if self.path=='/api/refresh':
                    row=app.collector.refresh(str(data.get('url','')))
                    return self.send(200,{'imported':True,'listing':row.model_dump()})
                if self.path=='/api/import':
                    raw=data.get('listings')
                    if not isinstance(raw,list) or not 1<=len(raw)<=500:raise ValueError('Import 1–500 listing records at a time.')
                    listings=[Listing.model_validate(r) for r in raw]
                    for row in listings:
                        retailer,sid,_=canonical_url(row.url)
                        if retailer!=row.retailer or sid!=row.source_id:raise ValueError('Listing identity does not match its URL.')
                        if row.source_kind not in {'manual','historical'}:raise ValueError('Browser imports must be manual or historical observations.')
                    count=sum(app.catalog.upsert(row) for row in listings)
                    return self.send(200,{'imported':count})
                return self.send(404,{'error':'Not found'})
            except (ValueError,KeyError,TypeError) as exc:return self.send(400,{'error':str(exc)[:1600]})
            except Exception as exc:return self.send(503,{'error':str(exc)[:500]})

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Shortlist is ready at http://127.0.0.1:{port}',flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close();app.model.close();app.workflow.conn.close()

