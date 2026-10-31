from types import SimpleNamespace
from shortlist.schema import Preferences
from shortlist.preferences import extract
from shortlist.search import Search
from shortlist.workflow import ShoppingWorkflow
from shortlist.taxonomy import infer_category
from shortlist.ingest import specs
from test_core import catalog,listing

def change(field,value,basis='stated',evidence='cheap',reason='A useful starting point'):
    return dict(field=field,value=value,basis=basis,evidence=evidence,reason=reason)
def model(*changes):
    return SimpleNamespace(interpret=lambda *args:dict(intent='search',changes=list(changes),unsupported=[],clarification=None))

def test_inferred_budget_is_soft_and_does_not_block_other_prices(catalog):
    catalog.upsert(listing(1,price=9000));catalog.upsert(listing(2,price=18000))
    p,_,w=extract('cheap laptop',model=model(change('max_price',10000,'inferred')))
    assert p['max_price'] is None and p['assumptions']['max_price']['value']==10000
    r=Search(catalog).run(p,method='bm25')
    assert len(r['products'])==2 and r['products'][0]['offers'][0]['price']==9000
    assert not any('inferred numeric requirement was ignored' in s for s in w)

def test_explicit_budget_clears_assumption_and_stays_hard(catalog):
    catalog.upsert(listing(1,price=9000));catalog.upsert(listing(2,price=18000))
    old=Preferences(assumptions={'max_price':{'value':10000,'reason':'Budget suggestion'}}).model_dump()
    p,_,_=extract('under 12000',old,model(change('max_price',12000,evidence='under 12000')))
    assert p['max_price']==12000 and 'max_price' not in p['assumptions']
    assert len(Search(catalog).run(p,method='bm25')['products'])==1

def test_inference_cannot_override_an_explicit_limit():
    p,_,_=extract('something nicer',Preferences(max_price=12000).model_dump(),model(change('max_price',25000,'inferred',evidence='something nicer')))
    assert p['max_price']==12000 and 'max_price' not in p['assumptions']

def test_inferred_ram_prefers_but_does_not_require_known_ram(catalog):
    catalog.upsert(listing(1,ram_gb=8));catalog.upsert(listing(2,ram_gb=32));catalog.upsert(listing(3,ram_gb=None))
    p,_,_=extract('laptop for heavy multitasking',model=model(change('min_ram_gb',32,'inferred',evidence='heavy multitasking')))
    assert p['min_ram_gb'] is None
    r=Search(catalog).run(p,method='bm25')
    assert len(r['products'])==3 and r['products'][0]['specs']['ram_gb']==32

def test_model_search_does_not_require_numeric_budget(catalog,tmp_path):
    catalog.upsert(listing())
    w=ShoppingWorkflow(Search(catalog),model(),tmp_path/'chat.sqlite3')
    try:
        r=w.run('natural','I want a laptop',True,False,'bm25')
        assert not r['pending'] and r['results']['products']
    finally:w.conn.close()

def test_cheap_and_latest_returns_honestly_labeled_alternatives(catalog,tmp_path):
    catalog.upsert(listing(1,category='smartphone',product_type=None,title='Test Android smartphone 128GB',price=10000))
    catalog.upsert(listing(2,category='smartphone',product_type=None,title='Another Android smartphone 256GB',price=20000))
    m=model(change('category','smartphone',evidence='phone'),change('product_type','smartphone',evidence='phone'),change('price_preference','budget'),change('release_preference','latest',evidence='latest release'))
    w=ShoppingWorkflow(Search(catalog),m,tmp_path/'chat.sqlite3')
    try:
        r=w.run('phone','A want a cheap phone latest release',True,False,'bm25')
        assert not r['pending'] and r['preferences']['product_type'] is None
        assert len(r['results']['products'])==2 and r['results']['match_status']=='partial'
        assert r['results']['assumptions']['max_price']['value']>0
        assert 'cannot verify' in r['history'][-1]['content']
    finally:w.conn.close()

def test_old_budget_interrupt_resumes_without_reasking(catalog,tmp_path):
    catalog.upsert(listing())
    w=ShoppingWorkflow(Search(catalog),model(change('price_preference','budget')),tmp_path/'chat.sqlite3')
    try:
        first=w.run('old','laptop',False,False,'bm25')
        assert first['pending']['kind']=='budget'
        second=w.run('old','I said cheap',True,False,'bm25')
        assert not second['pending'] and second['results']['products']
    finally:w.conn.close()

def test_phone_category_does_not_include_toys_or_accessories():
    assert infer_category('Educational Mobile Phone Toy for Kids')=='toy'
    assert infer_category('realme Buds Wireless Bluetooth')=='headphones'
    assert infer_category('Racing Sticker for Phone, laptop and bag')=='accessory'
    assert infer_category('Case Cover Compatible with OnePlus Buds Pro 2')=='accessory'
    assert infer_category('Ni-MH AAA Battery For Cordless Phone And Toys')=='accessory'
    assert infer_category('24 inch Full HD LED Backlit VA Panel with HDMI')=='monitor'
    assert infer_category('Wood Portable Laptop Table')=='furniture'

def test_changing_price_segment_discards_old_price_assumption():
    old=Preferences(price_preference='budget',assumptions={'max_price':{'value':10000,'reason':'Cheap starting point'}}).model_dump()
    p,_,_=extract('I want premium now',old,model(change('price_preference','premium',evidence='premium')))
    assert p['price_preference']=='premium' and 'max_price' not in p['assumptions']

def test_budget_and_inferred_specs_balance_instead_of_always_maximizing_ram(catalog):
    catalog.upsert(listing(1,price=30000,ram_gb=16));catalog.upsert(listing(2,price=400000,ram_gb=64))
    p=Preferences(price_preference='budget',priorities=['ram'],assumptions={'max_price':{'value':35000,'reason':'Starting budget'},'min_ram_gb':{'value':16,'reason':'Multitasking'}})
    r=Search(catalog).run(p.model_dump(),method='bm25')
    assert r['products'][0]['offers'][0]['price']==30000 and len(r['products'])==2

def test_cheap_does_not_infer_a_minimum_spend():
    p,_,_=extract('cheap laptop',model=model(change('price_preference','budget'),change('min_price',15000,'inferred')))
    assert p['min_price']==0 and 'min_price' not in p['assumptions']

def test_phone_rom_is_internal_storage_not_expandable_capacity():
    p=specs('Phone 4 GB RAM | 128 GB ROM | Expandable Upto 1 TB')
    assert p['ram_gb']==4 and p['storage_gb']==128
