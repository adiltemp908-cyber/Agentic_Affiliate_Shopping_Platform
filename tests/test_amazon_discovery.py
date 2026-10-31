import pytest
import json
from shortlist.ingest import Collector,amazon_product_links
from shortlist.ingest import amazon_related_product_links,is_service_plan
from test_core import catalog
from types import SimpleNamespace
from shortlist.ingest import ProductRedirect
from shortlist.ingest import clean_amazon_title,specs
from shortlist.ingest import extract_listing
from shortlist.taxonomy import infer_category,catalog_category
from shortlist.acquisition import category_cards


def test_discovery_only_follows_primary_card_identity():
    html='''<a href="https://www.amazon.in/dp/B000000009">Unrelated ad</a>
    <div data-component-type="s-search-result" data-asin="B000000001">
      <a href="/dp/B000000002">Other variant</a><a href="/clock/dp/B000000001?ref=search">Clock</a><span>₹1</span>
    </div>
    <div data-component-type="s-search-result" data-asin="B000000001"><a href="/dp/B000000001">Duplicate</a></div>
    <div data-component-type="s-search-result" data-asin="B000000003"><a href="https://evil.example/dp/B000000003">External</a></div>'''
    assert amazon_product_links(html)==['https://www.amazon.in/dp/B000000001']


def test_related_discovery_is_bounded_canonical_urls_only():
    html='''<a href="/dp/B000000001">Self</a><a href="/dp/B000000002?ref=x">Related</a>
    <a href="https://evil.test/dp/B000000003">External</a><a href="http://www.amazon.in/dp/B000000003">HTTP</a>
    <a href="/product/dp/B000000002">Duplicate</a><a href="/dp/B000000006">Extended Warranty for TV</a><a href="/dp/B000000004">Another</a>
    <a href="/dp/B000000005">Beyond limit</a>'''
    assert amazon_related_product_links(html,'https://www.amazon.in/dp/B000000001',2)==[
        'https://www.amazon.in/dp/B000000002','https://www.amazon.in/dp/B000000004']


def test_service_plan_is_not_a_device_with_included_warranty():
    assert is_service_plan('OneAssist Total Protection Plan for TV')
    assert is_service_plan('Samsung Care+ Extended Warranty for LED TV')
    assert is_service_plan('OneAssist 1 Year Furniture Care Plan (E-Mail Delivery Only)')
    assert is_service_plan('Onsitego 1 Year Damage Protection for Appliances')
    assert not is_service_plan('Samsung OLED TV with Extended Warranty')


def test_physical_discovery_rejects_service_plan_before_catalog_write(catalog):
    collector=Collector(catalog);collector.skip_service_plans=True
    product={'@type':'Product','name':'OneAssist 1 Year Protection Plan for TV',
             'url':'https://www.amazon.in/dp/B000000001','offers':{'price':999,'priceCurrency':'INR'}}
    html=('<script type="application/ld+json">'+json.dumps(product)+'</script>').encode()
    class Response:
        status_code=200
        encoding='utf-8'
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):yield html
    collector.session.get=lambda url,**kw:SimpleNamespace(status_code=200,text='User-agent: *\nAllow: /') if url.endswith('robots.txt') else Response()
    with pytest.raises(ValueError,match='Service-plan listing skipped'):collector.refresh(product['url'])
    assert not catalog.records()


def test_source_category_suffix_and_camera_features_do_not_misroute_phones():
    title=clean_amazon_title('OnePlus N6x Smartphone, 50MP Camera : Amazon.in: Toys &amp; Games')
    assert title=='OnePlus N6x Smartphone, 50MP Camera'
    assert specs(title)['category']=='smartphone'
    assert specs('Samsung Galaxy M07 Mobile')['category']=='smartphone'
    assert specs('Redmi Pad with 8MP Camera')['category']=='tablet'
    assert specs('Canon Digital Camera with smartphone connectivity')['category']=='camera'
    assert clean_amazon_title('Buy Digital Alarm Clock Online at Low Prices in India - Amazon.in')=='Digital Alarm Clock'


def test_virtual_ram_advertising_does_not_become_physical_ram_filter():
    assert 'ram_gb' not in specs('Smartphone | 4GB + 8GB RAM, 64GB Storage')
    assert 'ram_gb' not in specs('Smartphone 16GB RAM including 8GB virtual RAM')
    assert specs('Smartphone 4GB physical RAM + 8GB virtual RAM')['ram_gb']==4
    assert specs('Smartphone 8GB RAM + 128GB Storage')['ram_gb']==8


def test_phone_features_do_not_turn_wearables_or_earbuds_into_phones():
    assert infer_category('Noise ColorFit Pulse Air Smartwatch, Compatible with Android Phone')=='smartwatch'
    assert infer_category('PTron Bassbuds Vibe, Mobile App, Bluetooth')=='headphones'
    assert infer_category('boAt Airdopes with Mobile App')=='headphones'
    assert infer_category('Wireless Audio with Mobile App') is None
    assert infer_category('My Cubicles Office Chair Hydraulic pump NA Office Adjustable Arm Chair')=='other'
    assert infer_category('Office Chair with Adjustable Height')=='furniture'


def test_appliance_parts_do_not_satisfy_whole_appliance_search():
    assert infer_category('SCIVER Silicone Baking Tray Accessories with Ear Handles Air Fryer')=='other'
    assert infer_category('RMI Gasket Compatible with Pigeon Pressure Cooker')=='other'
    assert infer_category('100 Pcs Air Fryer Paper Liners')=='other'
    assert infer_category('Air Fryer 6L with Baking Tray')=='appliance'
    assert infer_category('Pressure Cooker with Gasket')=='cookware'
    assert infer_category('Stand Mixer Grinder with Steel Bowl')=='appliance'
    assert infer_category('KESOL Airfryer Paper Air Fryer')=='other'
    assert infer_category('26 Inch Chrome Base for Revolving Chair Steel Base Wheel')=='other'


def test_book_department_outweighs_words_in_a_book_title():
    html='<div data-id="BOOK000001"><a href="/black-coffee/p/itm123456789?pid=BOOK000001" title="Black Coffee">Black Coffee</a><div class="Nx9bqj">₹299</div></div>'
    rows=category_cards(html,'https://www.flipkart.com/books/pr?sid=bks','book')
    assert len(rows)==1 and rows[0].category=='book' and rows[0].attributes=={}


def test_department_overrides_brand_only_phone_guess_without_hiding_accessories():
    assert catalog_category('OnePlus Bullets Wireless Z2 Bluetooth','headphones')=='headphones'
    assert catalog_category('realme TechLife 8 kg Semi Automatic Top Load Washing...','appliance')=='appliance'
    assert catalog_category('REDMI  Pad Pro 6 GB 128 GB Wi-Fi Gaming Table...','tablet')=='tablet'
    assert catalog_category('realme TechLife 32 inch Smart Google TV','television')=='television'
    assert catalog_category('Silicone cover for mobile phone','smartphone')=='accessory'
    assert catalog_category('Toy educational phone','smartphone')=='toy'


def test_brand_name_is_not_evidence_of_fabric():
    state={'multiWidgetState':{'pageDataResponse':{'pageContext':{'productId':'DRESS00001','fdpEventTracking':{'events':{'psi':{'fsn':'DRESS00001','bd':'RK SILK','ppd':{'fsp':225},'pls':{'available':True}}}}},'seoData':{'seo':{'title':'RK SILK Women Shift Pink Dress','canonical':'https://www.flipkart.com/a/p/itm123456789'}}}}}
    row=extract_listing('<script>window.__INITIAL_STATE__ = '+json.dumps(state)+';</script>','https://www.flipkart.com/a/p/itm123456789')
    assert row.category=='clothing' and row.attributes['color']=='pink'
    assert 'material' not in row.attributes


def test_primary_amazon_dom_price_can_fill_missing_structured_offer():
    product={'@type':'Product','name':'Test running shoes','url':'https://www.amazon.in/dp/B000000001'}
    html='<script type="application/ld+json">'+json.dumps(product)+'</script><input id="ASIN" value="B000000001"><div id="corePriceDisplay_desktop_feature_div"><span class="priceToPay"><span class="a-offscreen">₹1,299</span></span></div>'
    row=extract_listing(html,'https://www.amazon.in/dp/B000000001')
    assert row.price==1299 and row.evidence['price']=='1299.0'
    with pytest.raises(ValueError,match='ASIN differs'):
        extract_listing(html.replace('value="B000000001"','value="B000000002"'),'https://www.amazon.in/dp/B000000001')
    assert extract_listing(html.replace('<input id="ASIN" value="B000000001">',''),'https://www.amazon.in/dp/B000000001').price is None


@pytest.mark.parametrize('url',[
 'http://www.amazon.in/s?k=clock','https://amazon.in.evil.test/s?k=clock',
 'https://user:pass@www.amazon.in/s?k=clock','https://www.amazon.in:443/s?k=clock',
 'https://www.amazon.in/s','https://www.amazon.in/s?k=clock&k=shirt',
 'https://www.amazon.in/ap/signin?k=clock'])
def test_discovery_rejects_unsafe_or_ambiguous_seed_urls(catalog,url):
    collector=Collector(catalog)
    collector.session.get=lambda *a,**k:pytest.fail('No network call should occur')
    with pytest.raises(ValueError):collector.discover_amazon(url)


def test_disallowed_discovery_does_not_fetch_products(catalog):
    from types import SimpleNamespace
    collector=Collector(catalog);calls=[]
    def get(url,**kwargs):
        calls.append(url)
        return SimpleNamespace(status_code=200,text='User-agent: *\nDisallow: /s')
    collector.session.get=get
    with pytest.raises(ValueError,match='disallowed'):collector.discover_amazon('https://www.amazon.in/s?k=clock')
    assert calls==['https://www.amazon.in/robots.txt']


def test_discovery_records_redirected_variant_under_its_own_url(catalog):
    collector=Collector(catalog)
    parent='https://www.amazon.in/dp/B000000001';child='https://www.amazon.in/dp/B000000002'
    class Response:
        status_code=200
        text='User-agent: *\nAllow: /'
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,*args):
            yield b'<div data-component-type="s-search-result" data-asin="B000000001"><a href="/dp/B000000001">Shirt</a></div>'
    collector.session.get=lambda *a,**k:Response()
    calls=[]
    def refresh(url):
        calls.append(url)
        if url==parent:raise ProductRedirect(child)
        return SimpleNamespace(url=child,price=500,availability='in_stock',category='clothing')
    collector.refresh=refresh
    r=collector.discover_amazon('https://www.amazon.in/s?k=shirt',1)
    assert calls==[parent,child]
    assert r['results'][0]['url']==child and r['results'][0]['discovered_url']==parent
    assert r['recent_priced']==1


def test_direct_refresh_does_not_replace_parent_with_different_asin(catalog):
    collector=Collector(catalog)
    parent='https://www.amazon.in/dp/B000000001';child='https://www.amazon.in/dp/B000000002'
    class Redirect:
        status_code=301
        headers={'Location':child}
        def close(self):pass
    def get(url,**kwargs):
        if url.endswith('robots.txt'):return SimpleNamespace(status_code=200,text='User-agent: *\nAllow: /')
        return Redirect()
    collector.session.get=get
    with pytest.raises(ProductRedirect) as caught:collector.refresh(parent)
    assert caught.value.url==child and not catalog.records()
