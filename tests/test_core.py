import json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
from shortlist import config
from shortlist.catalog import Catalog,canonical_url,identity,freshness
from shortlist.schema import Listing,Preferences
from shortlist.search import Search
from shortlist.preferences import extract
from shortlist.ingest import extract_listing,import_jsonl,is_laptop
from shortlist.workflow import ShoppingWorkflow

def listing(n=1,**changes):
    data=dict(retailer='Amazon',source_id=f'B{n:09}',title='Test Brand Portable laptop 16GB RAM 512GB SSD',
        url=f'https://www.amazon.in/dp/B{n:09}',brand='Test Brand',model=f'P{n}',ram_gb=16,storage_gb=512,
        cpu='i5-1235U',gpu='integrated',color='silver',weight_kg=1.4,gaming=False,upgradeable_ram=True,
        price=50000,shipping=0,availability='in_stock',condition='new',source_kind='manual',
        observed_at=datetime.now(timezone.utc).isoformat(),evidence={'title':'Test fixture, not a real commercial offer'})
    data.update(changes)
    return Listing(**data)

@pytest.fixture
def catalog(tmp_path,monkeypatch):
    monkeypatch.setattr(config,'DATA',tmp_path)
    return Catalog(tmp_path/'catalog.sqlite3')

def test_budget_and_shipping_enforced(catalog):
    catalog.upsert(listing(1,price=49000,shipping=2000))
    catalog.upsert(listing(2,price=49999,shipping=0))
    result=Search(catalog).run(Preferences(max_price=50000).model_dump(),method='bm25')
    assert len(result['products'])==1
    assert result['products'][0]['offers'][0]['source_id']=='B000000002'

def test_unknown_specs_never_satisfy_hard_requirement(catalog):
    catalog.upsert(listing(1,upgradeable_ram=None))
    catalog.upsert(listing(2,ram_gb=None))
    catalog.upsert(listing(3))
    result=Search(catalog).run(Preferences(max_price=60000,min_ram_gb=16,require_upgradeable_ram=True).model_dump(),method='bm25')
    assert len(result['products'])==1
    assert result['products'][0]['offers'][0]['source_id']=='B000000003'

def test_historical_not_default_and_out_of_stock_always_excluded(catalog):
    catalog.upsert(listing(1,source_kind='historical',observed_at=None))
    catalog.upsert(listing(2,availability='out_of_stock'))
    search=Search(catalog);p=Preferences(max_price=60000).model_dump()
    assert not search.run(p,method='bm25')['products']
    result=search.run(p,include_historical=True,method='bm25')
    assert len(result['products'])==1 and result['products'][0]['offers'][0]['freshness']=='historical'

def test_exact_variants_merge_different_variants_do_not(catalog):
    amazon=listing(1)
    flipkart=listing(2,retailer='Flipkart',source_id='COMPUTER001',url='https://www.flipkart.com/example/p/itm123456789?pid=COMPUTER001',model='P1',price=48000)
    wrong=listing(3,model='P1',ram_gb=8)
    for row in [amazon,flipkart,wrong]:catalog.upsert(row)
    result=Search(catalog).run(Preferences(max_price=60000).model_dump(),method='bm25')
    assert len(result['products'])==2
    merged=next(p for p in result['products'] if len(p['offers'])==2)
    assert merged['offers'][0]['retailer']=='Flipkart'

def test_incomplete_identity_does_not_merge():
    a=listing(1,cpu=None);b=listing(2,cpu=None,model='P1')
    assert identity(a)[0]!=identity(b)[0]

def test_old_import_cannot_overwrite_recent(catalog):
    catalog.upsert(listing(1,price=50000))
    assert not catalog.upsert(listing(1,price=20000,source_kind='historical',observed_at=None))
    assert catalog.records()[0]['price']==50000

def test_freshness_accounts_for_timezone():
    old=datetime.now(timezone.utc)-timedelta(days=2)
    assert freshness(listing(observed_at=old.isoformat()).model_dump())=='stale'
    assert freshness(listing(source_kind='historical').model_dump())=='historical'

@pytest.mark.parametrize('url',['http://127.0.0.1/a','https://amazon.in.evil.com/dp/B000000001','https://user@www.amazon.in/dp/B000000001','https://www.amazon.in:9000/dp/B000000001','https://www.amazon.in/s?k=laptop','https://www.flipkart.com/x/p/itm1'])
def test_non_product_or_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):canonical_url(url)

def test_model_cannot_override_literal_budget():
    model=SimpleNamespace(preferences=lambda *args:Preferences(max_price=200000).model_dump())
    p,_,_=extract('laptop under 60k with 16GB RAM',model=model)
    assert p['max_price']==60000 and p['min_ram_gb']==16

def test_followup_preserves_prior_constraints():
    p,_,_=extract('laptop under 60000 with 16GB RAM')
    refined,_,_=extract('at least 1TB SSD',p)
    assert refined['max_price']==60000 and refined['min_ram_gb']==16 and refined['min_storage_gb']==1024

def test_unstated_budget_is_not_invented_by_model():
    model=SimpleNamespace(preferences=lambda *args:Preferences(max_price=80000,any_budget=True).model_dump())
    p,_,_=extract('laptop for programming',model=model)
    assert p['max_price'] is None and not p['any_budget']

def test_use_case_does_not_authorize_model_invented_constraints():
    model=SimpleNamespace(preferences=lambda *args:Preferences(min_ram_gb=32,min_storage_gb=1024,max_weight_kg=1.2,brands=['Apple'],required_features=['oled'],unverified_requirements=['battery life','Linux compatibility']).model_dump())
    p,_,warnings=extract('laptop for programming under 60000',model=model)
    assert p['min_ram_gb'] is None and p['min_storage_gb'] is None and p['max_weight_kg'] is None
    assert not p['brands'] and not p['required_features'] and not p['unverified_requirements']
    assert not warnings

def test_explicit_unsupported_requirement_remains_visible():
    model=SimpleNamespace(preferences=lambda *args:Preferences(unverified_requirements=['Linux compatibility','battery life']).model_dump())
    p,_,warnings=extract('laptop with Linux compatibility under 60000',model=model)
    assert p['unverified_requirements']==['Linux compatibility']
    assert any('Linux compatibility' in w for w in warnings)

def test_model_cannot_relabel_supported_ram_as_an_unsupported_requirement():
    model=SimpleNamespace(preferences=lambda *args:Preferences(unverified_requirements=['at least 16GB RAM for programming']).model_dump())
    p,_,warnings=extract('laptop with at least 16GB RAM for programming',model=model)
    assert p['min_ram_gb']==16 and not p['unverified_requirements']
    assert not warnings

def test_vague_specs_do_not_become_invented_numeric_filters():
    model=SimpleNamespace(preferences=lambda *args:Preferences(min_ram_gb=32,min_storage_gb=1024,max_weight_kg=1.2).model_dump())
    p,_,_=extract('a lightweight laptop with good RAM and lots of storage',model=model)
    assert p['min_ram_gb'] is None and p['min_storage_gb'] is None and p['max_weight_kg'] is None

def test_other_product_categories_are_routed():
    p,_,_=extract('headphones under 5000')
    assert p['category']=='headphones' and p['max_price']==5000

def test_flipkart_primary_product_state_does_not_read_recommendation_price():
    state={'multiWidgetState':{'pageDataResponse':{'pageContext':{'productId':'COMPRIMARY1','fdpEventTracking':{'events':{'psi':{'fsn':'COMPRIMARY1','bd':'Lenovo','ppd':{'fsp':54990,'finalPrice':49990},'pls':{'available':True}}}}},'seoData':{'seo':{'title':'Lenovo laptop 16GB RAM 512GB SSD Rs.59990 Price in India','canonical':'https://www.flipkart.com/a/p/itm123456789'}}},'recommendations':[{'price':999}]}}
    row=extract_listing('<script>window.__INITIAL_STATE__ = '+json.dumps(state)+';</script>','https://www.flipkart.com/a/p/itm123456789')
    assert row.price==54990 and row.source_id=='COMPRIMARY1' and 'pid=COMPRIMARY1' in row.url

def test_multiple_product_structured_data_is_not_silently_selected():
    data=[{'@type':'Product','name':'Lenovo laptop computer'},{'@type':'Product','name':'Acer laptop computer'}]
    with pytest.raises(ValueError):extract_listing('<script type="application/ld+json">'+json.dumps(data)+'</script>','https://www.amazon.in/dp/B000000001')

def test_amazon_unavailable_listing_updates_stock_without_inventing_price():
    html='<span id="productTitle">HP laptop 8GB RAM 512GB SSD Dual Speakers</span><input id="ASIN" value="B000000001"><div id="availability">Currently unavailable.</div>'
    row=extract_listing(html,'https://www.amazon.in/dp/B000000001')
    assert row.availability=='out_of_stock' and row.price is None and row.ram_gb==8

def test_weight_does_not_become_currency():
    p,_,_=extract('laptop under 1.5kg')
    assert p['max_price'] is None
    assert p['max_weight_kg']==1.5

def test_currency_never_silently_converted():
    with pytest.raises(ValueError):extract('laptop under $600')

def test_jsonld_extraction_keeps_exact_price_and_source():
    html='<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'Lenovo laptop 16GB RAM 512GB SSD','offers':{'@type':'Offer','price':'49990','priceCurrency':'INR','availability':'https://schema.org/InStock'}})+'</script>'
    row=extract_listing(html,'https://www.amazon.in/dp/B000000001',observed_at=datetime.now(timezone.utc).isoformat())
    assert row.price==49990 and row.ram_gb==16 and row.availability=='in_stock' and row.shipping is None

def test_aggregate_and_challenge_pages_rejected():
    html='<script type="application/ld+json">'+json.dumps({'@type':'Product','name':'Test laptop computer','offers':{'@type':'AggregateOffer','lowPrice':30000}})+'</script>'
    with pytest.raises(ValueError):extract_listing(html,'https://www.amazon.in/dp/B000000001')
    with pytest.raises(ValueError):extract_listing('<html>Verify you are human</html>','https://www.amazon.in/dp/B000000001')

def test_import_validates_all_before_writing(catalog,tmp_path):
    path=tmp_path/'bad.jsonl';path.write_text(listing().model_dump_json()+'\n{"bad":true}')
    with pytest.raises(ValueError):import_jsonl(catalog,path)
    assert not catalog.records()

def test_persistent_clarification_resume_after_recreation(catalog,tmp_path):
    catalog.upsert(listing())
    path=tmp_path/'conversations.sqlite3'
    workflow=ShoppingWorkflow(Search(catalog),None,path)
    first=workflow.run('test-session','I need a laptop with 16GB RAM',use_model=False,method='bm25')
    assert first['pending'] and not first.get('results')
    workflow.conn.close()
    workflow=ShoppingWorkflow(Search(catalog),None,path)
    answer=workflow.run('test-session','60000',use_model=False,method='bm25')
    assert not answer['pending'] and answer['preferences']['max_price']==60000
    assert answer['preferences']['min_ram_gb']==16 and len(answer['results']['products'])==1
    assert any(h['content']=='60000' for h in answer['history'])
    workflow.conn.close()

def test_specific_query_completes_without_uninitialized_ui_state(catalog,tmp_path):
    catalog.upsert(listing())
    workflow=ShoppingWorkflow(Search(catalog),None,tmp_path/'conversation.sqlite3')
    result=workflow.run('specific','laptop under 60000',use_model=False,method='bm25')
    assert not result['pending'] and result['results']['products']
    workflow.conn.close()

@pytest.mark.parametrize('title',['Laptop sleeve','Laptop charger 100W','Laptop cooling pad','Replacement battery for laptop'])
def test_accessories_are_not_computers(title):
    assert not is_laptop(title)

