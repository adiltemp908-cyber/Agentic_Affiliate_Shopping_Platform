"""Bounded broad-category collection and provenance-preserving historical import."""
import json
import re
import sqlite3
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin,urlparse,parse_qs,urlencode
from urllib.robotparser import RobotFileParser
from bs4 import BeautifulSoup
from .ingest import Collector,specs,parse_price
from .taxonomy import infer_category,product_type,literal_attributes,CATEGORIES,catalog_category
from .catalog import canonical_url,freshness
from .schema import Listing,utcnow

def category_cards(html,source_url,category_hint=None,observed_at=None):
    soup=BeautifulSoup(html,'html.parser');rows=[];seen=set()
    for card in soup.select('[data-id]'):
        pid=card.get('data-id','')
        if pid in seen:continue
        link=next((a for a in card.select('a[href]') if '/p/itm' in a['href']),None)
        if not link:continue
        try:
            retailer,sid,url=canonical_url(urljoin(source_url,link['href']))
            if retailer!='Flipkart' or sid!=pid:continue
            # Only known selling-price elements, never strike-through MRP or
            # conditional bank/exchange text. Unknown markup fails closed.
            price_node=card.select_one('.hZ3P6w, .Nx9bqj, ._30jeq3')
            if not price_node:continue
            price_text=price_node.get_text('',strip=True)
            if not re.fullmatch(r'₹\s*[\d,]+(?:\.\d+)?',price_text):continue
            image=card.select_one('img[alt]')
            title=(image.get('alt','') if image else '')
            named=card.select_one('a[title]')
            if named and len(named.get('title',''))>len(title):title=named['title']
            if len(title)<8:continue
            bullets=' '.join(x.get_text(' ',strip=True) for x in card.select('li'))
            values=specs(title+' '+bullets)
            # A book's title can name a phone, coffee, or clothing; the retailer's
            # book department identifies the sold item more reliably than those words.
            category=catalog_category(title,category_hint)
            attributes=literal_attributes(title,category)
            # Category-card specifications can identify the panel even when the title cannot.
            display=literal_attributes(title+' '+bullets,category).get('display')
            if display:attributes['display']=display
            values.update(category=category,product_type=product_type(title,category),attributes=attributes)
            if display=='oled' and 'oled' not in values['features']:values['features'].append('oled')
            text=card.get_text(' ',strip=True)
            row=Listing(retailer=retailer,source_id=sid,title=title,url=url,price=parse_price(price_text),
              availability='out_of_stock' if re.search(r'\b(out of stock|sold out)\b',text,re.I) else 'unknown',
              source_kind='web',observed_at=observed_at or utcnow(),
              source_note='Observed on a retailer category page, not a product-detail or checkout check. Displayed base price; selected size, stock, shipping and postcode availability need confirmation.',
              evidence={'title':title,'specifications':bullets,'price':price_text,'category_page':source_url,'page_product_id':sid,
                        **({'category_department':category_hint} if category_hint else {})},**values)
            rows.append(row);seen.add(sid)
        except (ValueError,TypeError):continue
    return rows

class CatalogBuilder(Collector):
    def __init__(self,catalog):super().__init__(catalog);self.policies={}

    def read_category(self,url):
        parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname!='www.flipkart.com' or parsed.username or parsed.password or parsed.port or not parsed.path.endswith('/pr'):
            raise ValueError('Use an HTTPS Flipkart category /pr URL.')
        host=parsed.hostname
        if host not in self.policies:
            r=self.session.get(f'https://{host}/robots.txt',timeout=(8,20),allow_redirects=False);r.raise_for_status()
            policy=RobotFileParser();policy.parse(r.text.splitlines());self.policies[host]=policy
        policy=self.policies[host]
        if not policy.can_fetch(self.USER_AGENT,url):raise ValueError('Category is disallowed by robots.txt.')
        delay=max(self.min_delay,policy.crawl_delay(self.USER_AGENT) or 0)
        wait=delay-(time.monotonic()-self.last_request.get(host,0))
        if wait>0:time.sleep(wait)
        self.last_request[host]=time.monotonic()
        target=url
        for hop in range(4):
            r=self.session.get(target,timeout=(8,25),allow_redirects=False,stream=True)
            if r.status_code not in {301,302,303,307,308}:break
            next_url=urljoin(target,r.headers.get('Location',''));r.close();next_parsed=urlparse(next_url)
            if next_parsed.scheme!='https' or next_parsed.hostname!=host or next_parsed.username or next_parsed.password or next_parsed.port or not next_parsed.path.endswith('/pr') or not policy.can_fetch(self.USER_AGENT,next_url):
                raise ValueError('Category redirect left the permitted category paths.')
            target=next_url;time.sleep(delay);self.last_request[host]=time.monotonic()
        else:raise ValueError('Too many category redirects.')
        with r:
            r.raise_for_status()
            if r.status_code!=200:raise ValueError('Unexpected category redirect.')
            data=bytearray()
            for chunk in r.iter_content(65536):
                data.extend(chunk)
                if len(data)>5_000_000:raise ValueError('Category exceeds response size limit.')
            html=data.decode(r.encoding or 'utf-8',errors='replace')
        if re.search(r'verify you are human|enter the characters you see|access denied',html,re.I):raise ValueError('Source challenge; collection stopped for this category.')
        return html

    def collect(self,url,pages=2,category=None):
        if not 1<=pages<=10:raise ValueError('Choose 1–10 pages per category.')
        if category is not None and category not in CATEGORIES:raise ValueError('Unknown category.')
        parsed=urlparse(url);query=parse_qs(parsed.query);reports=[];seen=set()
        existing={(r['retailer'],r['source_id']):r for r in self.catalog.records()}
        for page in range(1,pages+1):
            query['page']=[str(page)];target=parsed._replace(query=urlencode(query,doseq=True)).geturl()
            try:
                html=self.read_category(target);rows=category_cards(html,target,category);count=0
                new_rows=[]
                for row in rows:
                    if row.source_id in seen:continue
                    seen.add(row.source_id);old=existing.get((row.retailer,row.source_id))
                    # A recent product-detail observation is stronger evidence.
                    if old and freshness(old)=='recent' and not old.get('evidence',{}).get('category_page'):continue
                    new_rows.append(row)
                count=self.catalog.upsert_many(new_rows)
                report={'url':target,'status':'ok','cards':len(rows),'imported':count}
                self.catalog.log_refresh(target,'ok',f'{count} category observations imported; stock and shipping unverified.')
                reports.append(report)
                if not rows or (page>1 and not new_rows):break
            except Exception as exc:
                self.catalog.log_refresh(target,'failed',str(exc));reports.append({'url':target,'status':'failed','detail':str(exc)[:250]});break
        return {'pages':reports,'imported':sum(r.get('imported',0) for r in reports)}

def import_broad_history(catalog,path,per_category=600):
    """Read original text metadata only; never execute the unsafe pickle store."""
    counts=Counter();seen=set();rows=[];scanned=0
    source=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    try:
        for (text,) in source.execute("SELECT string_value FROM embedding_metadata WHERE key='chroma:document'"):
            scanned+=1
            fields={p.partition(':')[0].strip():p.partition(':')[2].strip() for p in text.split(' | ')}
            title=fields.get('name','');hint=fields.get('sub_category','')
            category=infer_category(title,hint)
            if not category or counts[category]>=per_category:continue
            try:
                retailer,sid,url=canonical_url(fields.get('link',''))
                if (retailer,sid) in seen:continue
                values=specs(title);values.update(category=category,product_type=product_type(title,category),attributes=literal_attributes(title,category))
                row=Listing(retailer=retailer,source_id=sid,url=url,title=title,price=parse_price(fields.get('discount_price')),
                    source_kind='historical',observed_at=None,source_note='Original 2023 capstone dataset. Historical research only; price, variant and availability are not current.',
                    evidence={'title':title,'price':fields.get('discount_price',''),'original_category':hint},**values)
                rows.append(row);seen.add((retailer,sid));counts[category]+=1
            except ValueError:continue
    finally:source.close()
    imported=catalog.upsert_many(rows)
    return {'scanned':scanned,'imported':imported,'selected_by_category':dict(counts),'provenance':'historical; not fresh inventory'}
