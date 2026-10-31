from types import SimpleNamespace
from shortlist.preferences import extract
from shortlist.interpretation import apply_interpretation
from shortlist.schema import Preferences
from shortlist.search import Search
from shortlist.workflow import ShoppingWorkflow
from test_core import catalog,listing

def plan(message,**changes):
    return dict(changes=[dict(field=k,value=v,evidence=message) for k,v in changes.items()],unsupported=[],clarification=None)

def model(value):return SimpleNamespace(interpret=lambda *args:value)


def test_audience_cannot_be_copied_into_color_or_material():
    q='A cotton shirt for men under 1500'
    for attrs in [{'audience':'men','material':'cotton','color':'men'}, {'color':'men'}, {'material':'men'}]:
        p,_,_=extract(q,model=model(plan(q,attributes=attrs)))
        assert p['attributes']['audience']=='men'
        assert p['attributes']['material']=='cotton'
        assert 'color' not in p['attributes']


def test_quoted_colors_and_fabrics_outside_presets_remain_hard_filters(catalog):
    q='I want a maroon velvet sofa'
    p,_,_=extract(q,model=model(plan(q,attributes={'color':'maroon','material':'velvet'})))
    assert p['attributes']=={'color':'maroon','material':'velvet'}
    for n,attrs in [(1,{'color':'maroon','material':'velvet'}),(2,{'color':'red','material':'velvet'}),(3,{'color':'maroon','material':'leather'})]:
        catalog.upsert(listing(n,title='Test furniture sofa',category='furniture',product_type='sofa',attributes=attrs))
    result=Search(catalog).run(p,method='bm25')
    assert [o['source_id'] for x in result['products'] for o in x['offers']]==['B000000001']

def test_semantic_change_survives_literal_guards_and_search(catalog):
    q='A highend laptop with the most important spec being gpu, any budget is fine'
    p,engine,_=extract(q,model=model(plan(q,gpu_requirement='high_end',any_budget=True,priorities=['gpu'])))
    catalog.upsert(listing(1,gpu=None));catalog.upsert(listing(2,gpu='RTX 5080'))
    r=Search(catalog).run(p,method='bm25')
    assert engine=='local_qwen' and not p['unverified_requirements']
    assert len(r['products'])==1 and r['products'][0]['specs']['gpu']=='RTX 5080'

def test_semantic_numbers_require_user_evidence():
    q='Premium laptop, whatever it costs'
    p,_,w=extract(q,model=model(plan(q,any_budget=True,min_ram_gb=32,max_price=100000)))
    assert p['max_price'] is None and p['min_ram_gb'] is None and p['any_budget']
    assert p['assumptions']['min_ram_gb']['value']==32
    assert 'max_price' not in p['assumptions']  # explicit open budget wins

def test_spelled_out_budget_and_ram():
    q='Laptop under sixty thousand with sixteen GB RAM'
    p,_,_=extract(q,model=model(plan(q,max_price=60000,min_ram_gb=16)))
    assert p['max_price']==60000 and p['min_ram_gb']==16

def test_model_cannot_quote_earlier_assistant_to_invent_constraints():
    q='Whatever you think'
    payload=plan('32GB RAM under 60000',min_ram_gb=32,max_price=60000)
    p,_,_=apply_interpretation(q,Preferences().model_dump(),payload)
    assert p['max_price'] is None and p['min_ram_gb'] is None

def test_full_sentence_is_not_a_catalog_requirement():
    q='A highend laptop with the most important spec being gpu, any budget is fine'
    payload=plan(q,gpu_requirement='high_end',any_budget=True)
    payload['unsupported']=[dict(requirement=q,evidence=q)]
    p,_,_=extract(q,model=model(payload))
    assert not p['unverified_requirements']

def test_supported_gpu_and_independent_battery_requirement():
    q='Top-tier graphics on my laptop with 10 hours of battery life, any budget'
    payload=plan(q,gpu_requirement='high_end',any_budget=True)
    payload['unsupported']=[dict(requirement='10 hours of battery life',evidence='10 hours of battery life')]
    p,_,_=extract(q,model=model(payload))
    assert p['gpu_requirement']=='high_end' and any('battery' in s for s in p['unverified_requirements'])

def test_semantic_category_change_clears_old_filters():
    q='Something cotton to wear to work for less than two thousand'
    old=Preferences(category='laptop',gpu_requirement='high_end',min_ram_gb=32,attributes={'color':'black'}).model_dump()
    p,_,_=extract(q,old,model(plan(q,category='clothing',product_type='shirt',max_price=2000,attributes={'material':'cotton'})))
    assert p['category']=='clothing' and p['gpu_requirement']=='any' and p['min_ram_gb'] is None
    assert p['attributes']=={'material':'cotton'} and p['query']==q

def test_negation_clears_previous_gpu_requirement():
    q='Actually fancy graphics are unnecessary; keep the budget open'
    p,_,_=extract(q,Preferences(gpu_requirement='high_end',gpu_models=['RTX 5080'],min_vram_gb=16,priorities=['gpu']).model_dump(),model(plan(q,gpu_requirement='any',any_budget=True)))
    assert p['gpu_requirement']=='any' and not p['gpu_models'] and p['min_vram_gb'] is None
    assert not p['priorities'] and p['query']==q

def test_ambiguity_asks_question_instead_of_empty_search(catalog,tmp_path):
    q='I need the other kind of laptop, any budget'
    payload=plan(q,any_budget=True);payload['clarification']='Which kind of laptop do you mean?'
    w=ShoppingWorkflow(Search(catalog),model(payload),tmp_path/'chat.sqlite3')
    try:
        r=w.run('ambiguous',q,True,False,'bm25')
        assert r['pending']['kind']=='requirement' and not r.get('results')
    finally:w.conn.close()

def test_performance_is_not_an_anc_feature():
    p,_,_=extract('A laptop with great graphics performance, any budget')
    assert 'anc' not in p['required_features']

def test_negation_overrides_incorrect_positive_model_interpretation():
    q='A laptop, but I do not need a high-end GPU, any budget'
    payload=plan('I do not need a high-end GPU',gpu_requirement='dedicated')
    p,_,_=extract(q,model=model(payload))
    assert p['gpu_requirement']=='any'

def test_material_cannot_become_an_invented_color():
    q='cotton shirt under 2000'
    p,_,_=extract(q,model=model(plan(q,attributes={'material':'cotton','color':'cotton'})))
    assert p['attributes']=={'material':'cotton'}

def test_real_color_cannot_be_added_when_not_requested():
    q='a cotton shirt for the office under 2000'
    p,_,_=extract(q,model=model(plan(q,attributes={'material':'cotton','color':'white','size':'M'})))
    assert p['attributes']=={'material':'cotton'}

def test_question_can_refine_instead_of_reusing_previous_results(catalog,tmp_path):
    catalog.upsert(listing(1,gpu=None,price=50000));catalog.upsert(listing(2,gpu='RTX 5080',price=150000))
    q='Which would you suggest under 60000 instead?'
    m=model(plan(q,max_price=60000))
    w=ShoppingWorkflow(Search(catalog),m,tmp_path/'chat.sqlite3')
    try:
        w.run('refine','laptop any budget',False,False,'bm25')
        r=w.run('refine',q,True,False,'bm25')
        assert r['intent']=='search' and r['preferences']['max_price']==60000
        assert len(r['results']['products'])==1 and r['results']['products'][0]['offers'][0]['price']==50000
    finally:w.conn.close()

def test_gpu_priority_ranks_recorded_tiers_without_claiming_benchmarks(catalog):
    catalog.upsert(listing(1,gpu=None));catalog.upsert(listing(2,gpu='RTX 4050'));catalog.upsert(listing(3,gpu='RTX 5080'))
    r=Search(catalog).run(Preferences(any_budget=True,priorities=['gpu']).model_dump(),method='bm25')
    assert [p['specs']['gpu'] for p in r['products']]==['RTX 5080','RTX 4050',None]
    assert 'not a measured performance' in r['ranking']

def test_battery_hours_are_not_memory_or_price():
    q='A laptop with 10 hours of battery life'
    p,_,_=extract(q,model=model(plan(q,min_ram_gb=10,max_price=10)))
    assert p['min_ram_gb'] is None and p['max_price'] is None

def test_one_invalid_field_does_not_discard_a_valid_budget():
    q='laptop under 60000'
    p,_,_=extract(q,model=model(plan(q,max_price=60000,gpu_requirement=None)))
    assert p['max_price']==60000 and p['gpu_requirement']=='any'
