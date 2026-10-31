import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs, urlencode
from .schema import Listing, utcnow
from .config import FRESH_HOURS

HOSTS = {"www.amazon.in": "Amazon", "amazon.in": "Amazon", "www.flipkart.com": "Flipkart", "flipkart.com": "Flipkart"}

def canonical_url(url):
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Use a direct HTTPS product link from amazon.in or flipkart.com.")
    if HOSTS[parsed.hostname] == "Amazon":
        match = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", parsed.path, re.I)
        if not match:
            raise ValueError("Amazon link must contain a product ASIN (/dp/...).")
        return "Amazon", match[1].upper(), f"https://www.amazon.in/dp/{match[1].upper()}"
    pid = parse_qs(parsed.query).get("pid", [None])[0]
    item = re.search(r'/p/(itm[a-z0-9]{8,30})(?:/|$)',parsed.path,re.I)
    if not item or (pid and not re.fullmatch(r"[A-Za-z0-9]{6,40}", pid)):
        raise ValueError("Flipkart link must contain a valid /p/itm... product identifier.")
    return "Flipkart", pid or item[1], f"https://www.flipkart.com{parsed.path}"+(f"?{urlencode({'pid':pid})}" if pid else '')

def clean(value):
    return re.sub(r"[^a-z0-9]+", "", (value or "").lower())

def identity(listing):
    # Conservative exact matching. Incomplete identifiers never merge across stores.
    required = [listing.brand, listing.model, listing.ram_gb, listing.storage_gb, listing.cpu, listing.gpu, listing.color]
    if listing.category=='laptop' and all(value is not None and str(value).strip() for value in required) and listing.condition != "unknown":
        material = "|".join(clean(str(v)) for v in required) + "|" + listing.condition
        confidence = "exact_variant"
    else:
        material = f"{listing.retailer}|{listing.source_id}"
        confidence = "retailer_listing"
    return hashlib.sha256(material.encode()).hexdigest()[:24], confidence

def freshness(record, now=None):
    if record.get("source_kind") in {"historical", "fixture"}:
        return record["source_kind"]
    if not record.get("observed_at"):
        return "unverified"
    age = (now or datetime.now(timezone.utc)) - datetime.fromisoformat(record["observed_at"].replace("Z", "+00:00"))
    if age < timedelta(0):
        return "unverified"
    return "recent" if age <= timedelta(hours=FRESH_HOURS) else "stale"

class Catalog:
    def __init__(self, path):
        self.path = str(path)
        with self.connect() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS offers (
                    retailer TEXT NOT NULL, source_id TEXT NOT NULL,
                    product_id TEXT NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(retailer, source_id));
                CREATE INDEX IF NOT EXISTS product_offers ON offers(product_id);
                CREATE TABLE IF NOT EXISTS refreshes (
                    id INTEGER PRIMARY KEY, url TEXT, time TEXT, status TEXT, detail TEXT);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT, updated_at TEXT);
            ''')

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def upsert(self, listing):
        retailer, sid, url = canonical_url(listing.url)
        if retailer != listing.retailer or sid != listing.source_id:
            raise ValueError("Retailer/product identifier does not match the source URL.")
        listing.url = url
        pid, confidence = identity(listing)
        payload = listing.model_dump()
        payload.update(product_id=pid, match_confidence=confidence)
        with self.connect() as db:
            # Do not let an old import overwrite a more recent observation.
            row = db.execute("SELECT payload FROM offers WHERE retailer=? AND source_id=?", (retailer, sid)).fetchone()
            if row:
                previous = json.loads(row[0])
                old_time, new_time = previous.get("observed_at"), payload.get("observed_at")
                if old_time and (not new_time or datetime.fromisoformat(old_time.replace('Z','+00:00')) > datetime.fromisoformat(new_time.replace('Z','+00:00'))):
                    return False
            db.execute("INSERT OR REPLACE INTO offers VALUES(?,?,?,?)", (retailer, sid, pid, json.dumps(payload, ensure_ascii=False)))
        return True

    def records(self):
        with self.connect() as db:
            return [json.loads(r[0]) for r in db.execute("SELECT payload FROM offers ORDER BY retailer,source_id")]

    def upsert_many(self,listings):
        prepared=[]
        for listing in listings:
            retailer,sid,url=canonical_url(listing.url)
            if (retailer,sid)!=(listing.retailer,listing.source_id):raise ValueError('Source identity mismatch.')
            listing.url=url;pid,confidence=identity(listing)
            data=listing.model_dump();data.update(product_id=pid,match_confidence=confidence)
            prepared.append((retailer,sid,pid,data))
        count=0
        with self.connect() as db:
            for retailer,sid,pid,data in prepared:
                old=db.execute('SELECT payload FROM offers WHERE retailer=? AND source_id=?',(retailer,sid)).fetchone()
                if old:
                    old_time=json.loads(old[0]).get('observed_at');new_time=data.get('observed_at')
                    if old_time and (not new_time or datetime.fromisoformat(old_time.replace('Z','+00:00'))>datetime.fromisoformat(new_time.replace('Z','+00:00'))):continue
                db.execute('INSERT OR REPLACE INTO offers VALUES(?,?,?,?)',(retailer,sid,pid,json.dumps(data,ensure_ascii=False)));count+=1
        return count

    def stats(self):
        rows = self.records()
        coverage={}
        for retailer in ['Amazon','Flipkart']:
            source=[r for r in rows if r['retailer']==retailer]
            recent=[r for r in source if freshness(r)=='recent']
            coverage[retailer]={'total':len(source),'recent':len(recent),
                'recent_priced':sum(r.get('price') is not None and r['price']>0 and r.get('availability')!='out_of_stock' for r in recent),
                'recent_out_of_stock':sum(r.get('availability')=='out_of_stock' for r in recent),
                'recent_unknown_price':sum(r.get('price') is None and r.get('availability')!='out_of_stock' for r in recent)}
        return {"offers":len(rows), "products":len({r['product_id'] for r in rows}),
                "retailer_coverage":coverage,
                "categories":{c:{'total':sum(r.get('category')==c for r in rows),'recent':sum(r.get('category')==c and freshness(r)=='recent' for r in rows)} for c in sorted({r.get('category','other') for r in rows})},
                "retailers":{s:sum(r['retailer']==s for r in rows) for s in ['Amazon','Flipkart']},
                "freshness":{s:sum(freshness(r)==s for r in rows) for s in ['recent','stale','unverified','historical','fixture']}}

    def log_refresh(self, url, status, detail):
        with self.connect() as db:
            db.execute("INSERT INTO refreshes(url,time,status,detail) VALUES(?,?,?,?)", (url,utcnow(),status,detail[:1500]))

    def refresh_log(self):
        with self.connect() as db:
            db.row_factory=sqlite3.Row
            return [dict(r) for r in db.execute("SELECT * FROM refreshes ORDER BY id DESC LIMIT 20")]

    def remember(self, session, title):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO sessions VALUES(?,?,?)", (session,title[:90],utcnow()))

    def sessions(self):
        with self.connect() as db:
            return [dict(id=r[0],title=r[1],updated_at=r[2]) for r in db.execute("SELECT * FROM sessions ORDER BY updated_at DESC LIMIT 30")]

