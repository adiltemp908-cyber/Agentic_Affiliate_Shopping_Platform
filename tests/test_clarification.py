import sqlite3
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from langgraph.graph import StateGraph,START,END
from langgraph.types import interrupt
from langgraph.checkpoint.sqlite import SqliteSaver
from shortlist.preferences import extract
from shortlist.schema import Preferences
from shortlist.search import Search
from shortlist.workflow import ShoppingWorkflow,State
from shortlist.taxonomy import infer_category
from test_core import catalog,listing


BRIEF='I want a digital alarm clock that is round in shape'


def test_clock_requirements_survive_and_exclude_wrong_shapes(catalog):
    p,_,_=extract(BRIEF,Preferences(category=None).model_dump())
    assert p['category']=='decor' and p['product_type']=='alarm clock'
    assert p['attributes']=={'shape':'round','display':'digital'}
    for n,attrs in [(1,{'shape':'round','display':'digital'}),(2,{'shape':'square','display':'digital'}),(3,{'shape':'round','display':'analog'}),(4,{})]:
        catalog.upsert(listing(n,title='Test alarm clock',category='decor',product_type='alarm clock',attributes=attrs))
    products=Search(catalog).run(p,method='bm25')['products']
    assert [o['source_id'] for x in products for o in x['offers']]==['B000000001']
    assert infer_category('Digital alarm clock for office desk')=='decor'
    assert infer_category('Digital alarm clock for study table')=='decor'
    assert infer_category('Hidden spy camera alarm clock')!='decor'


def test_semantic_clock_attributes_accept_paraphrase():
    message='A circular clock with a digital display'
    plan={'intent':'search','changes':[{'field':'attributes','value':{'shape':'round','display':'digital'},'evidence':message}], 'unsupported':[],'clarification':None}
    p,_,_=extract(message,Preferences(category=None).model_dump(),SimpleNamespace(interpret=lambda *args:plan))
    assert p['attributes']=={'shape':'round','display':'digital'}


def test_required_question_cannot_be_rewritten_as_anything_else(catalog,tmp_path):
    plan={'intent':'search','changes':[],'unsupported':[],'clarification':None}
    model=SimpleNamespace(interpret=lambda *args:plan,reply=lambda *args:'Anything else?')
    w=ShoppingWorkflow(Search(catalog),model,tmp_path/'chat.sqlite3')
    try:
        r=w.run('missing','I need a gift',True,method='bm25')
        assert r['pending']['kind']=='category'
        assert 'What are you shopping for' in r['pending']['question']
    finally:w.conn.close()


def test_unresolved_clarification_cannot_loop_forever(catalog,tmp_path):
    w=ShoppingWorkflow(Search(catalog),None,tmp_path/'chat.sqlite3')
    try:
        assert w.run('missing','I need a gift',False,method='bm25')['pending']
        assert w.run('missing','yes',False,method='bm25')['pending']
        r=w.run('missing','No',False,method='bm25')
        assert not r['pending'] and r['intent']=='clarification_failed'
        assert not r['results'] and 'item name' in r['history'][-1]['content']
        r=w.run('missing','A shirt under 1000',False,method='bm25')
        assert not r['pending'] and r['preferences']['category']=='clothing'
    finally:w.conn.close()


def test_proceed_preserves_hard_limits_and_soft_assumptions(catalog,tmp_path):
    plan={'intent':'proceed','changes':[],'unsupported':[],'clarification':None}
    model=SimpleNamespace(interpret=lambda *args:plan)
    w=ShoppingWorkflow(Search(catalog),model,tmp_path/'chat.sqlite3')
    try:
        p=Preferences(category='decor',product_type='alarm clock',query=BRIEF,max_price=1000,max_price_exclusive=True,
                      attributes={'shape':'round','display':'digital'},assumptions={'max_weight_kg':{'value':.5,'reason':'Portable'}}).model_dump()
        state={'message':'That covers everything, go ahead','preferences':p,'history':[], 'use_model':True}
        update=w.understand(state)
        assert update['preferences']==p and update['stop_followups'] and not update['pending_kind']
    finally:w.conn.close()


def test_misclassified_confirmation_cannot_swallow_explicit_budget_correction():
    previous=Preferences(max_price=1000,max_price_exclusive=True,query='cheap phone',category='smartphone').model_dump()
    plan={'intent':'proceed','changes':[],'unsupported':[],'clarification':None}
    p,_,_=ShoppingWorkflow.extract_turn('any budget',previous,None,{},plan,True)
    assert p['any_budget'] and p['max_price'] is None and not p['max_price_exclusive']
    assert p['query']==previous['query']
    p,_,_=ShoppingWorkflow.extract_turn('less than 5000',previous,None,{},plan,True)
    assert p['max_price']==5000 and p['max_price_exclusive']


def test_nothing_else_confirmation_is_not_a_brand_request():
    p=Preferences(category='decor',product_type='alarm clock',query=BRIEF,attributes={'shape':'round','display':'digital'}).model_dump()
    plan={'intent':'proceed','changes':[],'unsupported':[],'clarification':None}
    result,_,_=ShoppingWorkflow.extract_turn('Nothing else, just show me the options',p,None,{},plan,True)
    assert result==p


def test_old_clock_interrupt_recovers_on_confirmation(catalog,tmp_path):
    path=tmp_path/'old.sqlite3';conn=sqlite3.connect(str(path),check_same_thread=False)
    graph=StateGraph(State)
    def old_understand(state):
        return {'preferences':Preferences(category=None,query=BRIEF).model_dump(),'history':[{'role':'user','content':BRIEF}], 'workflow_version':2}
    def old_clarify(state):
        interrupt({'question':'Anything else you want me to consider?','kind':'category','preferences':state['preferences']})
        return {}
    graph.add_node('understand',old_understand);graph.add_node('clarify',old_clarify)
    graph.add_edge(START,'understand');graph.add_edge('understand','clarify');graph.add_edge('clarify',END)
    graph.compile(checkpointer=SqliteSaver(conn)).invoke({'message':BRIEF},{'configurable':{'thread_id':'old'}})
    conn.close()
    w=ShoppingWorkflow(Search(catalog),None,path)
    try:
        r=w.run('old','No',False,method='bm25')
        assert not r['pending'] and r['stop_followups']
        assert r['preferences']['product_type']=='alarm clock'
        assert r['preferences']['attributes']=={'shape':'round','display':'digital'}
        assert r['preferences']['query']==BRIEF
    finally:w.conn.close()


def test_coverage_distinguishes_searchable_prices_from_catalog_size(catalog):
    catalog.upsert(listing(1))
    catalog.upsert(listing(2,price=None))
    catalog.upsert(listing(3,availability='out_of_stock'))
    catalog.upsert(listing(4,source_kind='historical',observed_at=None))
    catalog.upsert(listing(5,observed_at=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()))
    c=catalog.stats()['retailer_coverage']['Amazon']
    assert c=={'total':5,'recent':3,'recent_priced':1,'recent_out_of_stock':1,'recent_unknown_price':1}


def test_cross_retailer_offers_survive_price_ranking(catalog):
    catalog.upsert(listing(1,price=900))
    catalog.upsert(listing(2,retailer='Flipkart',source_id='COMPUTER001',url='https://www.flipkart.com/example/p/itm123456789?pid=COMPUTER001',price=800))
    r=Search(catalog).run(Preferences(any_budget=True,sort_by='price_asc').model_dump(),method='bm25')
    assert [p['offers'][0]['retailer'] for p in r['products']]==['Flipkart','Amazon']
