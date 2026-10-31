"""Deterministic extraction; missing fields stay unknown. No model-generated facts."""
import json
import re
import sqlite3
import time
from html import unescape
from pathlib import Path
from urllib.parse import urlparse, urljoin,parse_qs,urlencode
from urllib.robotparser import RobotFileParser
import requests
from bs4 import BeautifulSoup
from .schema import Listing, utcnow
from .catalog import canonical_url
from .taxonomy import infer_category,product_type,literal_attributes
from .detail_specs import flipkart_details

BRANDS = ['Lenovo','ASUS','Acer','Dell','HP','Apple','MSI','Samsung','Microsoft','LG','Huawei','Honor','Infinix','Avita','Fujitsu','Gigabyte','Sony','JBL','Bose','boAt','OnePlus','Xiaomi','Redmi','Realme','Poco','Vivo','Oppo','Motorola','Google','Nothing','Nike','Adidas','Puma','Reebok','Levis','Allen Solly','Van Heusen','H&M','Zara','Woodland','Usha','Havells','Philips','Prestige','Pigeon','Hawkins','Bosch','Whirlpool','Godrej','Haier','Panasonic','Canon','Nikon','Fastrack','Titan','Noise','Fire-Boltt']

def specs(title):
    values = {}
    category=infer_category(title)
    if category:
        values.update(category=category,product_type=product_type(title,category),attributes=literal_attributes(title,category))
    for brand in BRANDS:
        if re.search(r'\b'+re.escape(brand)+r'\b',title,re.I):
            values['brand']=brand
            break
    # Only explicitly labelled memory/storage, never video-memory capacity.
    ram=re.search(r'(\d{1,3})\s*GB\s*(?:DDR\d\s*)?(?:RAM|Memory)\b',title,re.I)
    if not ram:
        ram=re.search(r'[(/]\s*(\d{1,3})\s*GB\s*[/,]',title,re.I)
    physical=re.search(r'(\d{1,3})\s*GB\s*(?:physical|on[ -]board)\s*RAM\b',title,re.I)
    mixed_ram=re.search(r'\d+\s*GB\s*\+\s*\d+\s*GB\s*(?:RAM|memory)\b|\b(?:extended|virtual|dynamic)\s+(?:\d+\s*GB\s*)?(?:RAM|memory)\b|\d+\s*GB\s*(?:extended|virtual|dynamic)\b',title,re.I)
    if physical:ram=physical
    elif mixed_ram:ram=None  # Advertised physical + virtual totals are not physical RAM.
    storage=re.search(r'(\d+(?:\.\d+)?)\s*(GB|TB)\s*(?:PCIe\s*|NVMe\s*)?(SSD|HDD|eMMC|Storage|ROM)\b',title,re.I)
    weight=re.search(r'(\d(?:\.\d+)?)\s*kg\b',title,re.I)
    if ram:values['ram_gb']=int(ram[1])
    if storage:values['storage_gb']=int(float(storage[1])*(1024 if storage[2].lower()=='tb' else 1))
    if weight:values['weight_kg']=float(weight[1])
    cpu=re.search(r'\b(?:i[3579]-?\d{4,5}[a-z]{0,3}|Ryzen\s*[3579]\s*\d{4}[a-z]{0,3}|Apple\s*M[1234](?:\s*(?:Pro|Max))?)\b',title,re.I)
    gpu=re.search(r'\b(?:(?:RTX|GTX)\s*\d{3,4}(?:\s*Ti)?|RX\s*\d{4}M?)\b',title,re.I)
    if cpu:values['cpu']=cpu[0]
    if gpu:
        values['gpu']=re.sub(r'\s+',' ',gpu[0].upper())
        vram=re.search(r'(\d+)\s*GB\s*(?:GDDR\d\s*)?(?:graphics|graphic memory|vram)',title,re.I)
        if vram:values['vram_gb']=int(vram[1])
    if re.search(r'\b(?:gaming|TUF|ROG|Nitro|Predator|Legion)\b',title,re.I):values['gaming']=True
    # Absence of the word gaming is not proof of a non-gaming laptop.
    values['features']=[f for f in ['touchscreen','backlit keyboard'] if f in title.lower()]
    if values.get('attributes',{}).get('display')=='oled':values['features'].append('oled')
    if re.search(r'\btouch[ -]+screen\b',title,re.I):values['features'].append('touchscreen')
    if re.search(r'\b(?:ANC|active noise cancell?ation|active noise cancell?ing)\b',title,re.I):values['features'].append('anc')
    for feature in ['wireless','bluetooth','5g','waterproof','induction']:
        if re.search(r'\b'+feature+r'\b',title,re.I):values['features'].append(feature)
    if re.search(r'\b(?:renewed|refurbished)\b',title,re.I):values['condition']='refurbished'
    return values

def is_laptop(title):
    return bool(re.search(r'\b(?:laptop|notebook|macbook|chromebook)\b',title,re.I)) and not bool(re.search(r'\b(?:sleeves?|backpacks?|chargers?|adapters?|stands?|bags?|skins?|covers?|screen protector|battery replacement|replacement battery|cooling pad|keyboard for|stickers?|microfibre|scratch remover|cleaning|wipes|cables?|external|bluetooth speaker|portable speaker|roller case|messenger|shoulder|lens|hub|mouse|screws?)\b',title,re.I))

def parse_price(value):
    if value is None:return None
    if isinstance(value,dict):value=value.get('value')
    match=re.search(r'\d[\d,]*(?:\.\d+)?',str(value))
    if not match:return None
    price=float(match[0].replace(',',''))
    return price if price>0 else None

def extract_listing(html, url, source_kind='web', observed_at=None):
    retailer,sid,url=canonical_url(url)
    soup=BeautifulSoup(html,'html.parser')
    text=soup.get_text(' ',strip=True)
    if any(s in text.lower() for s in ['enter the characters you see below','sorry, we just need to make sure','verify you are human','access denied']):
        raise ValueError('Retailer returned an access challenge; no product was imported.')
    asin=soup.select_one('input#ASIN') if retailer=='Amazon' else None
    if asin and asin.get('value') and asin['value'].upper()!=sid:raise ValueError('Amazon page ASIN differs from requested product.')
    nodes=[]
    def walk(node):
        if isinstance(node,list):
            for item in node:walk(item)
        elif isinstance(node,dict):
            typ=node.get('@type',[])
            if typ=='Product' or isinstance(typ,list) and 'Product' in typ:nodes.append(node)
            if '@graph' in node:walk(node['@graph'])
    for script in soup.find_all('script',type='application/ld+json'):
        try:walk(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError):pass
    candidates=[p for p in nodes if len(str(p.get('name','')))>7]
    matching=[]
    for candidate in candidates:
        try:
            if canonical_url(candidate.get('url',''))[:2]==(retailer,sid):matching.append(candidate)
        except ValueError:pass
    if len(candidates)>1 and len(matching)!=1:raise ValueError('Multiple products on page; no unique matching product identity.')
    product=matching[0] if matching else candidates[0] if len(candidates)==1 else None
    if not product and retailer=='Flipkart':
        return extract_flipkart_state(html,url,source_kind,observed_at)
    if not product and retailer=='Amazon':
        title_node=soup.select_one('#productTitle')
        asin=soup.select_one('input#ASIN')
        if asin and asin.get('value') and asin['value']!=sid:raise ValueError('Amazon page ASIN differs from requested product.')
        if title_node and len(title_node.get_text(' ',strip=True))>7:
            product={'name':title_node.get_text(' ',strip=True),'offers':{}}
            price_node=soup.select_one('#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen, #corePrice_feature_div .priceToPay .a-offscreen')
            if price_node and '₹' in price_node.get_text():
                product['offers']={'price':parse_price(price_node.get_text()),'priceCurrency':'INR'}
    if not product:
        raise ValueError('No unambiguous Product data found. Import a documented listing manually instead.')
    title=unescape(str(product['name'])).strip()
    if retailer=='Amazon':
        primary_title=soup.select_one('#productTitle')
        if primary_title:title=primary_title.get_text(' ',strip=True)
        title=clean_amazon_title(title)
    values=specs(title)
    values.setdefault('category','other')
    if product.get('brand'):
        brand=product['brand']
        values['brand']=str(brand.get('name','') if isinstance(brand,dict) else brand)
    if product.get('mpn'):values['model']=str(product['mpn'])
    elif product.get('model') and isinstance(product['model'],str):values['model']=product['model']
    offers=product.get('offers',{})
    if isinstance(offers,list):
        # Several sellers/variants must not be silently collapsed to the cheapest.
        if len(offers)!=1:raise ValueError('Multiple embedded offers require a variant-specific manual import.')
        offers=offers[0]
    if not isinstance(offers,dict):offers={}
    if offers.get('@type')=='AggregateOffer':
        raise ValueError('Aggregate price range is not a specific purchasable offer.')
    price=parse_price(offers.get('price'))
    currency=offers.get('priceCurrency')
    # Some primary Product JSON omits the offer even while its selected variant
    # displays a price. Only use the scoped price with an independently matching ASIN.
    if price is None and retailer=='Amazon' and asin and asin.get('value','').upper()==sid:
        price_node=soup.select_one('#corePriceDisplay_desktop_feature_div .priceToPay .a-offscreen, #corePrice_feature_div .priceToPay .a-offscreen')
        if price_node and '₹' in price_node.get_text():
            price=parse_price(price_node.get_text());currency='INR'
            offers={**offers,'price':price,'priceCurrency':currency}
    if price is not None and currency != 'INR':
        raise ValueError('Missing or unsupported price currency; expected explicit INR.')
    availability=str(offers.get('availability','')).lower()
    stock='in_stock' if availability.endswith('/instock') else 'out_of_stock' if availability.endswith(('/outofstock','/soldout','/discontinued')) else 'unknown'
    if retailer=='Amazon':
        stock_node=soup.select_one('#availability')
        if stock_node:
            stock_text=stock_node.get_text(' ',strip=True).lower()
            if 'currently unavailable' in stock_text or 'out of stock' in stock_text:stock='out_of_stock'
            elif re.search(r'\bin stock\b',stock_text):stock='in_stock'
            offers['availability']=stock_text
    condition=str(offers.get('itemCondition',product.get('itemCondition',''))).lower()
    if condition.endswith('/newcondition'):values['condition']='new'
    elif condition.endswith('/usedcondition'):values['condition']='used'
    elif condition.endswith('/refurbishedcondition'):values['condition']='refurbished'
    return Listing(retailer=retailer,source_id=sid,title=title,url=url,price=price,
                   availability=stock,observed_at=observed_at,source_kind=source_kind,
                   source_note='Product structured data / primary listing fields; location-specific shipping and discounts not verified.',
                   evidence={'title':title,'price':str(offers.get('price','')),'availability':str(offers.get('availability',''))},**values)

def extract_flipkart_state(html,url,source_kind,observed_at):
    # Parse only the current product's context. Recommendations/ads are separate nodes.
    marker=re.search(r'window\.__INITIAL_STATE__\s*=\s*',html)
    if not marker:raise ValueError('No supported Flipkart product data found.')
    try:
        state,_=json.JSONDecoder().raw_decode(html[marker.end():])
        data=state['multiWidgetState']['pageDataResponse']
        context=data['pageContext'];seo=data['seoData']['seo']
        primary=context['fdpEventTracking']['events']['psi']
        if context['productId']!=primary['fsn']:raise ValueError('Product identifier mismatch.')
        _,sid,url=canonical_url(url)
        if not sid.startswith('itm') and sid!=context['productId']:raise ValueError('Requested variant does not match page data.')
        if canonical_url(seo['canonical'])[1] != canonical_url(url.split('?')[0])[1]:
            raise ValueError('Canonical page does not match requested product.')
        # Item pages can contain several variants; persist the actual product PID.
        sid=context['productId']
        url=url.split('?')[0]+'?pid='+sid
        title=seo.get('title','').split(' Rs.')[0].strip()
        if len(title)<8:raise ValueError('The page has no valid product title.')
        brand=str(primary.get('bd','')).strip()
        spec_title=title[len(brand):].lstrip() if brand and title.casefold().startswith(brand.casefold()+' ') else title
        values=specs(spec_title)
        values.setdefault('category','other')
        values['brand']=str(primary.get('bd',values.get('brand',''))).title()
        for attr in primary.get('swa',[]):
            if attr.get('attributeName')=='color':values['color']=attr['attributeValue']
        price=parse_price(primary.get('ppd',{}).get('fsp'))
        # fsp is base selling price; never use conditional finalPrice/nepPrice values.
        status=primary.get('pls',{})
        available='in_stock' if status.get('available') is True else 'unknown'
        return Listing(retailer='Flipkart',source_id=sid,title=title,url=url,price=price,
            availability=available,observed_at=observed_at,source_kind=source_kind,
            source_note='Flipkart primary-product page state. Base selling price only; location, shipping and conditional bank/exchange offers not verified.',
            evidence={'title':title,'price':str(primary.get('ppd',{}).get('fsp','')),'page_product_id':context['productId'],
                      'availability':str(status.get('available','unknown'))},**values)
    except (KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('Flipkart page format changed or product fields are incomplete.') from exc

def clean_amazon_title(title):
    title=unescape(title).strip()
    title=re.sub(r'^Buy (.+) Online at Low Prices in India - Amazon\.in$',r'\1',title)
    return re.split(r'\s*:\s*Amazon\.in\b',title,maxsplit=1)[0].strip()


def amazon_product_links(html):
    """Discover primary result identities only; search-card prices are not evidence."""
    soup=BeautifulSoup(html,'html.parser');found={}
    for card in soup.select('[data-component-type="s-search-result"][data-asin]'):
        asin=card.get('data-asin','')
        if not re.fullmatch(r'[A-Z0-9]{10}',asin):continue
        for link in card.select('a[href]'):
            try:
                retailer,sid,url=canonical_url(urljoin('https://www.amazon.in',link['href']))
                if retailer=='Amazon' and sid==asin:found.setdefault(sid,url);break
            except ValueError:continue
    return list(found.values())


def is_service_plan(title):
    head=re.split(r'\b(?:with|includes|including)\b',title,maxsplit=1,flags=re.I)[0]
    return bool(re.search(r'\b(?:(?:protection|insurance|warranty|care) plan|extended warranty|e[- ]?mail delivery)\b|\b\d+\s*years?\b.*\bdamage protection\b',head,re.I))


def amazon_related_product_links(html,source_url,limit=40):
    """URL discovery only: every candidate still requires its own product-page check."""
    source=canonical_url(source_url)[2];found=[];seen={source}
    for link in BeautifulSoup(html,'html.parser').select('a[href]'):
        label=link.get_text(' ',strip=True)+' '+link.get('aria-label','')+' '+' '.join(img.get('alt','') for img in link.select('img'))
        if is_service_plan(label):continue
        try:
            retailer,_,url=canonical_url(urljoin(source,link['href']))
        except ValueError:continue
        if retailer!='Amazon' or url in seen:continue
        found.append(url);seen.add(url)
        if len(found)>=limit:break
    return found


class ProductRedirect(ValueError):
    def __init__(self,url):
        self.url=url
        super().__init__('Retailer redirected to a different product variant; original listing was not refreshed.')


class Collector:
    USER_AGENT='ShortlistResearchBot/0.1'
    def __init__(self,catalog):
        self.catalog=catalog
        self.session=requests.Session()
        self.session.headers['User-Agent']=self.USER_AGENT
        self.last_request={}
        self.min_delay=3

    def discover(self,url,limit=12):
        """Discover public listing links, then use our own catalog and ranking."""
        parsed=urlparse(url)
        if parsed.hostname=='www.amazon.in':return self.discover_amazon(url,limit)
        if parsed.scheme!='https' or parsed.hostname!='www.flipkart.com' or not parsed.path.startswith('/laptops/') or not parsed.path.endswith('/pr') or parsed.username or parsed.port:
            raise ValueError('Discovery currently supports public www.flipkart.com/laptops/.../pr category pages only.')
        if not 1<=limit<=30:raise ValueError('Discovery limit must be 1–30.')
        policy_response=self.session.get('https://www.flipkart.com/robots.txt',timeout=(8,15),allow_redirects=False)
        if policy_response.status_code!=200:raise ValueError('Could not verify category crawl policy.')
        policy=RobotFileParser();policy.parse(policy_response.text.splitlines())
        if not policy.can_fetch(self.USER_AGENT,url):raise ValueError('Category disallowed by robots.txt.')
        response=self.session.get(url,timeout=(8,25),allow_redirects=False)
        if response.status_code!=200:raise ValueError(f'Category returned HTTP {response.status_code}.')
        if len(response.content)>5_000_000:raise ValueError('Category response exceeded 5 MB.')
        soup=BeautifulSoup(response.text,'html.parser');found={}
        for link in soup.find_all('a',href=True):
            try:
                retailer,sid,target=canonical_url(urljoin(url,link['href']))
                if retailer=='Flipkart':found.setdefault(sid,target)
            except ValueError:continue
        results=[]
        self.last_request['www.flipkart.com']=time.monotonic()
        for target in list(found.values())[:limit]:
            try:
                row=self.refresh(target)
                results.append({'url':row.url,'status':'ok','price_known':row.price is not None})
            except Exception as exc:results.append({'url':target,'status':'failed','detail':str(exc)[:200]})
        return {'discovered':len(found),'attempted':len(results),'imported':sum(r['status']=='ok' for r in results),'results':results}

    def discover_amazon(self,url,limit=12):
        parsed=urlparse(url);query=parse_qs(parsed.query).get('k',[])
        if parsed.scheme!='https' or parsed.hostname!='www.amazon.in' or parsed.path!='/s' or parsed.username or parsed.password or parsed.port or len(query)!=1 or not 1<=len(query[0].strip())<=200:
            raise ValueError('Use a public Amazon India search URL: https://www.amazon.in/s?k=your+product')
        if not 1<=limit<=30:raise ValueError('Discovery limit must be 1–30.')
        target='https://www.amazon.in/s?'+urlencode({'k':query[0].strip()})
        try:
            robots=self.session.get('https://www.amazon.in/robots.txt',timeout=(8,15),allow_redirects=False)
            if robots.status_code!=200:raise ValueError('Could not verify Amazon discovery crawl policy.')
            policy=RobotFileParser();policy.parse(robots.text.splitlines())
            if not policy.can_fetch(self.USER_AGENT,target):raise ValueError('Amazon search is disallowed by robots.txt; discovery skipped.')
            host='www.amazon.in';delay=max(self.min_delay,policy.crawl_delay(self.USER_AGENT) or 0)
            wait=delay-(time.monotonic()-self.last_request.get(host,0))
            if wait>0:time.sleep(wait)
            self.last_request[host]=time.monotonic()
            with self.session.get(target,timeout=(8,25),allow_redirects=False,stream=True) as response:
                if response.status_code!=200:raise ValueError(f'Amazon discovery returned HTTP {response.status_code}.')
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>5_000_000:raise ValueError('Discovery page exceeded 5 MB.')
                    chunks.append(chunk)
                html=b''.join(chunks).decode('utf-8',errors='replace')
            found=amazon_product_links(html)
            if not found:raise ValueError('No supported Amazon result cards found; page may be blocked or its layout changed.')
            results=[]
            for product_url in found[:limit]:
                try:
                    # Search commonly returns parent ASINs for fashion. Discover a
                    # selected child as its OWN record, never overwrite the parent.
                    current=product_url;visited=set()
                    for hop in range(3):
                        if current in visited:raise ValueError('Product variant redirect loop; discovery skipped.')
                        visited.add(current)
                        try:row=self.refresh(current);break
                        except ProductRedirect as redirect:current=redirect.url
                    else:raise ValueError('Too many product variant redirects; discovery skipped.')
                    results.append({'url':row.url,'discovered_url':product_url,'status':'ok','price':row.price,'availability':row.availability,'category':row.category})
                except Exception as exc:results.append({'url':product_url,'status':'failed','detail':str(exc)[:200]})
            report={'discovered':len(found),'attempted':len(results),'imported':sum(r['status']=='ok' for r in results),
                    'recent_priced':sum(r.get('price') is not None and r['price']>0 and r.get('availability')!='out_of_stock' for r in results),'results':results}
            self.catalog.log_refresh(target,'ok',f"{report['imported']} primary pages imported; {report['recent_priced']} priced and not marked unavailable.")
            return report
        except Exception as exc:
            self.catalog.log_refresh(target,'failed',str(exc));raise

    def refresh(self,url):
        self.last_product_links=[]
        _,_,url=canonical_url(url)
        host=urlparse(url).hostname
        try:
            robots_url=f'https://{host}/robots.txt'
            robots=self.session.get(robots_url,timeout=(8,15),allow_redirects=False)
            if robots.status_code != 200:
                raise ValueError(f'Could not verify robots.txt (HTTP {robots.status_code}); refresh skipped.')
            policy=RobotFileParser()
            policy.parse(robots.text.splitlines())
            if not policy.can_fetch(self.USER_AGENT,url):
                raise ValueError('Product URL is disallowed for this crawler by robots.txt; refresh skipped.')
            delay=max(self.min_delay,policy.crawl_delay(self.USER_AGENT) or 0)
            wait=delay-(time.monotonic()-self.last_request.get(host,0))
            if wait>0:time.sleep(wait)
            self.last_request[host]=time.monotonic()
            # Follow only bounded same-product redirects on the allowlisted retailer.
            current=url
            identity=canonical_url(url)[:2]
            for hop in range(4):
                if not policy.can_fetch(self.USER_AGENT,current):raise ValueError('Redirect target is disallowed by robots.txt.')
                response=self.session.get(current,timeout=(8,20),allow_redirects=False,stream=True)
                if response.status_code not in {301,302,303,307,308}:break
                target=urljoin(current,response.headers.get('Location',''))
                response.close()
                if urlparse(target).hostname != host:
                    raise ValueError('Redirect changed product or retailer; no refresh performed.')
                target_identity=canonical_url(target)
                if target_identity[:2]!=identity:
                    if identity[0]=='Amazon':raise ProductRedirect(target_identity[2])
                    raise ValueError('Redirect changed product or retailer; no refresh performed.')
                current=target
            else:raise ValueError('Too many product redirects.')
            with response:
                if response.status_code!=200:raise ValueError(f'Retailer returned HTTP {response.status_code}; no refresh performed.')
                chunks=[];size=0
                for chunk in response.iter_content(65536):
                    size+=len(chunk)
                    if size>5_000_000:raise ValueError('Product response exceeded 5 MB limit.')
                    chunks.append(chunk)
                html=b''.join(chunks).decode(response.encoding or 'utf-8',errors='replace')
            listing=extract_listing(html,url,observed_at=utcnow())
            if getattr(self,'skip_service_plans',False) and is_service_plan(listing.title):
                raise ValueError('Service-plan listing skipped during physical-product discovery.')
            if listing.retailer=='Amazon' and getattr(self,'capture_product_links',False):
                self.last_product_links=amazon_related_product_links(html,url)
            if listing.retailer=='Flipkart':
                attributes,evidence=flipkart_details(html,listing.source_id)
                listing.attributes.update(attributes);listing.evidence.update(evidence)
            self.catalog.upsert(listing)
            self.catalog.log_refresh(url,'ok','Product structured data imported; shipping remains unknown.')
            return listing
        except Exception as exc:
            self.catalog.log_refresh(url,'failed',str(exc))
            raise

def import_jsonl(catalog,path):
    count=0
    # Validate the entire file before writing any rows.
    rows=[]
    for i,line in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(),1):
        if not line.strip():continue
        try:
            row=Listing.model_validate_json(line)
            retailer,sid,_=canonical_url(row.url)
            if retailer!=row.retailer or sid!=row.source_id:raise ValueError('Source identity mismatch')
            rows.append(row)
        except Exception as exc:raise ValueError(f'Line {i}: {exc}') from exc
    for row in rows:count+=catalog.upsert(row)
    return count

def import_legacy(catalog,path,limit=300):
    db=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    count=0;seen=set()
    try:
        rows=db.execute("SELECT string_value FROM embedding_metadata WHERE key='chroma:document' AND (string_value LIKE '%laptop%' OR string_value LIKE '%MacBook%')")
        for (text,) in rows:
            fields={p.partition(':')[0].strip():p.partition(':')[2].strip() for p in text.split(' | ')}
            title=fields.get('name','')
            if not is_laptop(title):continue
            parsed_specs=specs(title)
            if not parsed_specs.get('brand'):continue
            try:
                retailer,sid,url=canonical_url(fields.get('link',''))
                if sid in seen:continue
                price=parse_price(fields.get('discount_price'))
                if price is not None and price<5000:continue
                listing=Listing(retailer=retailer,source_id=sid,title=title,url=url,price=price,
                    source_kind='historical',observed_at=None,source_note='Imported from the original capstone 2023 catalog. Price, stock and specifications require rechecking.',
                    evidence={'title':title,'price':fields.get('discount_price','')},**parsed_specs)
                count+=catalog.upsert(listing);seen.add(sid)
                if count>=limit:break
            except ValueError:continue
    finally:db.close()
    return count
