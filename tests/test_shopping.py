import json
from datetime import datetime,timezone
from shortlist.schema import Preferences
from shortlist.preferences import extract
from shortlist.search import Search
from shortlist.workflow import ShoppingWorkflow
from shortlist.acquisition import category_cards
from shortlist.taxonomy import infer_category
from shortlist.detail_specs import flipkart_details
from test_core import catalog,listing

def test_high_end_gpu_is_a_hard_requirement(catalog):
    catalog.upsert(listing(1,gpu=None))
    catalog.upsert(listing(2,gpu='RTX 4050'))
    catalog.upsert(listing(3,gpu='RTX 5080'))
    p,_,_=extract('A laptop with a high end GPU, any budget')
    result=Search(catalog).run(p,method='bm25')
    assert p['gpu_requirement']=='high_end'
    assert [o['source_id'] for x in result['products'] for o in x['offers']]==['B000000003']

def test_no_high_end_gpu_means_no_matches(catalog):
    catalog.upsert(listing(1,gpu='RTX 3050'))
    p,_,_=extract('high-end GPU laptop any budget')
    assert not Search(catalog).run(p,method='bm25')['products']

def test_any_answers_pending_budget_once(catalog,tmp_path):
    catalog.upsert(listing(1,gpu='RTX 5080'))
    w=ShoppingWorkflow(Search(catalog),None,tmp_path/'chat.sqlite3')
    first=w.run('gpu','A laptop with high end GPU',use_model=False,method='bm25')
    assert first['pending']['kind']=='budget'
    second=w.run('gpu','any',use_model=False,method='bm25')
    assert not second['pending'] and second['preferences']['any_budget']
    assert second['preferences']['gpu_requirement']=='high_end'
    assert len(second['warnings'])==len(set(second['warnings']))
    assert second['results']['products'][0]['specs']['gpu']=='RTX 5080'
    assert 'high end GPU' in second['preferences']['query']
    w.conn.close()

def test_any_does_not_remove_budget_without_context():
    p,_,_=extract('any',Preferences(max_price=60000).model_dump())
    assert p['max_price']==60000

def test_clothing_attributes_are_filtered(catalog):
    catalog.upsert(listing(1,category='clothing',product_type='shirt',title='Mens blue cotton shirt for everyday wear',attributes={'color':'blue','material':'cotton','audience':'men'},price=999))
    catalog.upsert(listing(2,category='clothing',product_type='shirt',title='Mens red polyester shirt for everyday wear',attributes={'color':'red','material':'polyester','audience':'men'},price=799))
    catalog.upsert(listing(3))
    p,_,_=extract('blue cotton shirt for men under 1500')
    r=Search(catalog).run(p,method='bm25')
    assert p['category']=='clothing' and p['product_type']=='shirt'
    assert len(r['products'])==1 and r['products'][0]['offers'][0]['source_id']=='B000000001'

def test_category_change_clears_inapplicable_gpu_ram():
    previous=Preferences(category='laptop',min_ram_gb=32,gpu_requirement='high_end',any_budget=True).model_dump()
    p,_,_=extract('Now a cotton shirt under 2000',previous)
    assert p['category']=='clothing' and p['min_ram_gb'] is None and p['gpu_requirement']=='any'
    assert p['max_price']==2000 and not p['any_budget']

def test_subtypes_do_not_match_different_fashion_items(catalog):
    catalog.upsert(listing(1,category='clothing',product_type='jeans',title='Mens blue cotton jeans',attributes={'material':'cotton'},price=1000))
    p,_,_=extract('cotton shirt under 2000')
    assert not Search(catalog).run(p,method='bm25')['products']

def test_unverified_need_blocks_recommendations_until_explicit_opt_in(catalog):
    catalog.upsert(listing())
    p,_,_=extract('laptop with long battery life under 60000')
    assert not Search(catalog).run(p,method='bm25')['products']
    p,_,_=extract('show partial matches',p)
    r=Search(catalog).run(p,method='bm25')
    assert r['products'] and r['match_status']=='partial'
    assert any('Partial match' in c for c in r['products'][0]['caveats'])

def test_old_saved_gpu_requirement_migrates():
    old=Preferences(unverified_requirements=['high end gpu'],query='laptop high end gpu').model_dump()
    p,_,_=extract('any',old,context={'pending_kind':'budget'})
    assert p['gpu_requirement']=='high_end' and not p['unverified_requirements']

def test_category_listing_uses_base_price_and_exact_pid():
    html='''<div data-id="SHTPRIMARY1"><a href="/shirt/p/itm123456789?pid=SHTPRIMARY1"><img alt="Mens blue cotton casual shirt"><div class="hZ3P6w">₹999</div><div class="kRYCnD">₹1,999</div><span>Exchange up to ₹300</span></a></div>'''
    r=category_cards(html,'https://www.flipkart.com/shirts/pr?sid=clo',category_hint='clothing')
    assert len(r)==1 and r[0].price==999 and r[0].category=='clothing'
    assert r[0].availability=='unknown' and r[0].attributes['material']=='cotton'
    assert not category_cards(html.replace('SHTPRIMARY1"><a','WRONGPID1"><a'),'https://www.flipkart.com/shirts/pr?sid=clo')

def test_unknown_price_markup_is_not_guessed():
    html='<div data-id="SHTPRIMARY1"><a href="/shirt/p/itm123456789?pid=SHTPRIMARY1"><img alt="Mens cotton shirt"><span>₹200</span></a></div>'
    assert not category_cards(html,'https://www.flipkart.com/shirts/pr?sid=clo')

def test_product_question_uses_previous_candidates(catalog,tmp_path):
    catalog.upsert(listing())
    w=ShoppingWorkflow(Search(catalog),None,tmp_path/'chat.sqlite3')
    first=w.run('discussion','laptop under 60000',False,False,'bm25')
    second=w.run('discussion','Why the first one?',False,False,'bm25')
    assert second['intent']=='discuss' and second['results']==first['results']
    assert second['preferences']==first['preferences']
    w.conn.close()

def test_unknown_category_is_clarified(catalog,tmp_path):
    w=ShoppingWorkflow(Search(catalog),None,tmp_path/'chat.sqlite3')
    r=w.run('unknown','I need a gift',False,False,'bm25')
    assert r['pending']['kind']=='category'
    r=w.run('unknown','a cotton shirt under 1500',False,False,'bm25')
    assert not r['pending'] and r['preferences']['category']=='clothing'
    w.conn.close()

def test_short_budget_reply_cannot_become_an_unverified_requirement():
    class BadModel:
        def preferences(self,*args):raise AssertionError('A contextual any answer needs no model call')
    p,_,_=extract('any',Preferences(gpu_requirement='high_end').model_dump(),BadModel(),{'pending_kind':'budget'})
    assert p['any_budget'] and not p['unverified_requirements'] and p['gpu_requirement']=='high_end'

def test_shirt_dress_is_not_a_shirt():
    from shortlist.taxonomy import product_type
    assert product_type('Women Shirt Below Knee Dress','clothing')=='dress'

def test_detail_specs_ignore_recommended_product_widgets():
    def widget(pid,fabric):return {'slotData':{'widget':{'tracking':{'productId':pid,'widgetType':'atlas_product_details'},'data':{'value':{'label_0':{'value':{'text':'Fabric'}},'label_1':{'value':{'text':[fabric]}}}}}}}
    state={'multiWidgetState':{'pageDataResponse':{'pageContext':{'productId':'SHTPRIMARY1'}},'widgetsData':{'slots':[widget('SHTPRIMARY1','Pure Cotton'),widget('SHTOTHER11','Silk')]}}}
    attrs,evidence=flipkart_details('window.__INITIAL_STATE__ = '+json.dumps(state),'SHTPRIMARY1')
    assert attrs['material']=='cotton' and evidence['material']=='Fabric: Pure Cotton'
    assert flipkart_details('window.__INITIAL_STATE__ = '+json.dumps(state),'SHTWRONG11')==({}, {})

def test_bare_size_reply_uses_conversation_context():
    previous=Preferences(category='clothing',product_type='shirt',max_price=1500,attributes={'material':'cotton'}).model_dump()
    p,_,_=extract('M',previous,context={'followup_kind':'size'})
    assert p['attributes']=={'material':'cotton','size':'M'} and p['max_price']==1500

def test_cheaper_followup_uses_actual_previous_price():
    previous=Preferences(max_price=100000).model_dump()
    p,_,_=extract('Something cheaper please',previous,context={'previous_results':[{'price':60000}]})
    assert p['sort_by']=='price_asc' and p['max_price']==60000 and p['max_price_exclusive']

def test_brand_correction_replaces_prior_whitelist():
    p,_,_=extract('Only ASUS instead',Preferences(brands=['Lenovo']).model_dump())
    assert p['brands']==['ASUS']

def test_previous_version_results_are_hidden_until_rechecked(catalog,tmp_path):
    catalog.upsert(listing(1,gpu='RTX 5080'))
    w=ShoppingWorkflow(Search(catalog),None,tmp_path/'chat.sqlite3')
    cfg={'configurable':{'thread_id':'old'}}
    w.run('old','laptop with high end gpu any budget',False,False,'bm25')
    w.graph.update_state(cfg,{'workflow_version':1})
    assert not w.snapshot('old')['results']
    result=w.run('old','any budget',False,False,'bm25')
    assert result['workflow_version']==2 and result['results']['products']
    w.conn.close()

def test_previously_saved_budget_interrupt_can_resume(catalog,tmp_path):
    import sqlite3
    from langgraph.graph import StateGraph,START,END
    from langgraph.types import interrupt
    from langgraph.checkpoint.sqlite import SqliteSaver
    from shortlist.workflow import State
    catalog.upsert(listing(1,gpu='RTX 5080'))
    path=tmp_path/'old-chat.sqlite3';conn=sqlite3.connect(str(path),check_same_thread=False)
    g=StateGraph(State)
    def old_understand(state):return {'preferences':Preferences(query='high end GPU laptop',unverified_requirements=['high end gpu']).model_dump(),'history':[{'role':'user','content':'high end GPU laptop'}]}
    def old_clarify(state):interrupt({'question':'What is your budget?','preferences':state['preferences']});return {}
    g.add_node('understand',old_understand);g.add_node('clarify',old_clarify)
    g.add_edge(START,'understand');g.add_edge('understand','clarify');g.add_edge('clarify',END)
    graph=g.compile(checkpointer=SqliteSaver(conn));graph.invoke({'message':'high end GPU laptop'},{'configurable':{'thread_id':'old'}});conn.close()
    w=ShoppingWorkflow(Search(catalog),None,path)
    result=w.run('old','any',False,False,'bm25')
    assert not result['pending'] and result['preferences']['any_budget']
    assert result['preferences']['gpu_requirement']=='high_end' and result['results']['products']
    w.conn.close()
