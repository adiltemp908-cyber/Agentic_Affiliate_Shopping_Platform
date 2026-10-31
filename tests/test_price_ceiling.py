from types import SimpleNamespace
import pytest
from shortlist.preferences import extract
from shortlist.interpretation import explicit_price_ceiling
from shortlist.schema import Preferences
from shortlist.search import Search
from shortlist.workflow import ShoppingWorkflow
from test_core import catalog,listing

@pytest.mark.parametrize('message,value,exclusive',[
    ('less than 1000',1000,True),('less than ₹1,000.50',1000.50,True),
    ('under 1k',1000,True),('below INR 25,000',25000,True),
    ('less than one thousand rupees',1000,True),('under sixty thousand',60000,True),
    ('up to 1000',1000,False),('at most Rs. 1000',1000,False),
    ('no more than 1000',1000,False),('not more than 1000',1000,False),
    ('price < 1000',1000,True),('price <= 1000',1000,False),
])
def test_original_amount_and_comparison_preserved(message,value,exclusive):
    p,_,_=extract(message)
    assert p['max_price']==value and p['max_price_exclusive']==exclusive
    assert not p['any_budget'] and 'max_price' not in p['assumptions']

@pytest.mark.parametrize('message',['less than 2kg','under 16GB RAM','under 1.5 kg','less than 10 hours','not less than 1000','no less than 1000'])
def test_non_price_or_negated_comparisons_are_not_ceilings(message):
    assert explicit_price_ceiling(message) is None

def test_model_subtracting_one_cannot_convert_limit_to_assumption():
    q='less than 1000'
    m=SimpleNamespace(interpret=lambda *args:dict(intent='search',changes=[dict(field='max_price',value=999,basis='inferred',evidence=q,reason='Strictly below 1000')],unsupported=[],clarification=None))
    previous=Preferences(price_preference='budget',assumptions={'max_price':{'value':5000,'reason':'Earlier suggestion'}}).model_dump()
    p,_,_=extract(q,previous,m)
    assert p['max_price']==1000 and p['max_price_exclusive'] and 'max_price' not in p['assumptions']

def test_strict_boundary_includes_paise_and_checks_shipping(catalog):
    for n,price,shipping in [(1,999,0),(2,999.5,0),(3,999.99,0),(4,1000,0),(5,900,100),(6,1001,0)]:
        catalog.upsert(listing(n,price=price,shipping=shipping))
    p,_,_=extract('laptop less than 1000')
    result=Search(catalog).run(p,method='bm25')
    assert {o['source_id'] for r in result['products'] for o in r['offers']}=={'B000000001','B000000002','B000000003'}
    p,_,_=extract('up to 1000',p)
    result=Search(catalog).run(p,method='bm25')
    assert len(result['products'])==5

def test_limit_persists_and_updates_from_strict_to_inclusive(catalog,tmp_path):
    catalog.upsert(listing(1,price=999.5));catalog.upsert(listing(2,price=1000))
    w=ShoppingWorkflow(Search(catalog),None,tmp_path/'chat.sqlite3')
    try:
        r=w.run('limit','laptop less than 1000',False,False,'bm25')
        assert 'below INR 1,000' in r['history'][-1]['content']
        assert 'starting' not in r['history'][-1]['content']
        r=w.run('limit','only Lenovo',False,False,'bm25')
        assert r['preferences']['max_price']==1000 and r['preferences']['max_price_exclusive']
        r=w.run('limit','actually up to 2000',False,False,'bm25')
        assert r['preferences']['max_price']==2000 and not r['preferences']['max_price_exclusive']
    finally:w.conn.close()

def test_empty_search_still_explains_firm_limit(catalog,tmp_path):
    catalog.upsert(listing(price=2000))
    w=ShoppingWorkflow(Search(catalog),None,tmp_path/'chat.sqlite3')
    try:
        r=w.run('empty','laptop less than 1000',False,False,'bm25')
        assert not r['results']['products']
        assert 'below INR 1,000' in r['history'][-1]['content']
        assert not r['results']['assumptions']
    finally:w.conn.close()
