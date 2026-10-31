import sqlite3
import threading
import re
from typing import TypedDict
from langgraph.graph import StateGraph, START, END
from langgraph.types import interrupt, Command
from langgraph.checkpoint.sqlite import SqliteSaver
from .preferences import extract
from .schema import Preferences
from .taxonomy import CATEGORIES,infer_category,product_type,literal_attributes

class State(TypedDict,total=False):
    message:str
    preferences:dict
    history:list
    use_model:bool
    include_historical:bool
    method:str
    engine:str
    warnings:list
    results:dict
    question:str
    pending_kind:str
    intent:str
    response_engine:str
    followup_kind:str
    workflow_version:int
    clarification_attempts:int
    stop_followups:bool

class ShoppingWorkflow:
    def __init__(self,search,model,path):
        self.search=search;self.model=model;self.lock=threading.RLock()
        self.conn=sqlite3.connect(str(path),check_same_thread=False)
        self.checkpointer=SqliteSaver(self.conn)
        graph=StateGraph(State)
        graph.add_node('understand',self.understand)
        graph.add_node('clarify',self.clarify)
        graph.add_node('retrieve',self.retrieve)
        graph.add_node('respond',self.respond)
        graph.add_edge(START,'understand')
        graph.add_conditional_edges('understand',self.route,{'clarify':'clarify','retrieve':'retrieve','respond':'respond'})
        graph.add_conditional_edges('clarify',self.route,{'clarify':'clarify','retrieve':'retrieve','respond':'respond'})
        graph.add_edge('retrieve','respond')
        graph.add_edge('respond',END)
        self.graph=graph.compile(checkpointer=self.checkpointer)

    def understand(self,state):
        history=state.get('history',[])+[{'role':'user','content':state['message']}]
        context={'history':history[-8:],'previous_results':self.candidates(state.get('results',{})),'followup_kind':state.get('followup_kind')}
        previous=self.recover_brief(state.get('preferences') or Preferences(category=None,query='').model_dump())
        model=self.model if state.get('use_model') else None
        plan=None;interpretation_warning=None
        if model and hasattr(model,'interpret'):
            context['catalog_prices']=self.search.market_context(infer_category(state['message']) or previous.get('category'))
            try:plan=model.interpret(state['message'],previous,context)
            except Exception as exc:
                interpretation_warning=f'Local conversation interpretation unavailable: {str(exc)[:140]}. Explicit rules used.'
                model=None
        # Questions can also refine a search. Use meaning before sentence prefixes.
        discusses=plan is not None and plan.get('intent')=='discuss'
        if plan is None:
            discusses=bool(re.match(r'\s*(why\b|compare\b|what(?:.s| is) the difference|what (?:is|does|are) (?:a |an |the )?(?:gpu|vram|ram|ssd|cotton)|tell me (?:more|about)|which (?:one|of|is|has|would)|does (?:it|the|this)|is (?:it|this|the)|how (?:does|do|is)|what about (?:the )?(?:first|second|third))',state['message'],re.I))
            if re.search(r'\b(?:under|below|instead|find|show|switch|budget|only)\b',state['message'],re.I):discusses=False
        if state.get('results') and discusses:
            return {'history':history,'intent':'discuss','question':'','pending_kind':''}
        proceed=self.proceed(plan,state['message'],previous)
        prefs,engine,warnings=self.extract_turn(state['message'],previous,model,context,plan,proceed)
        if interpretation_warning:warnings.append(interpretation_warning)
        update={'preferences':prefs,'engine':engine,'warnings':list(dict.fromkeys(warnings)),'results':{},'history':history,'intent':'search','workflow_version':2,
                'clarification_attempts':0,'stop_followups':proceed or (state.get('stop_followups',False) and prefs.get('category')==previous.get('category'))}
        return {**update,**self.prepare_question({**state,**update})}

    @staticmethod
    def recover_brief(previous):
        p=Preferences.model_validate(previous).model_dump()
        if not p['category']:
            p['category']=infer_category(p['query']) or ('other' if p.get('product_type') else None)
            if p['category']:
                p['product_type']=p['product_type'] or product_type(p['query'],p['category'])
                p['attributes']={**literal_attributes(p['query'],p['category']),**p['attributes']}
        return p

    @staticmethod
    def proceed(plan,message,previous):
        if plan is not None:return plan.get('intent')=='proceed'
        return bool(previous.get('query') and re.fullmatch(r'\s*(?:yes|yeah|yep|no|nope|nothing else|that.?s all|just show me (?:the )?options)[.!]?\s*',message,re.I))

    @staticmethod
    def extract_turn(message,previous,model,context,plan,proceed):
        if not proceed:return extract(message,previous,model,context,interpretation=plan)
        # A confirmation cannot change the brief or turn an assumption into a limit.
        p=ShoppingWorkflow.recover_brief(previous)
        # Price corrections still take precedence over a mistaken proceed intent.
        # Other literal guesses (e.g. "Nothing else" -> brand Nothing) must not
        # change a confirmed brief.
        explicit,_,_=extract(message,p,context=context)
        price_fields=('max_price','max_price_exclusive','min_price','any_budget')
        if any(explicit[key]!=p[key] for key in price_fields):
            for key in price_fields:p[key]=explicit[key]
            for key in ('max_price','min_price'):
                if key in explicit['assumptions']:p['assumptions'][key]=explicit['assumptions'][key]
                else:p['assumptions'].pop(key,None)
        return p,'local_qwen' if plan is not None else 'context_rules',[]

    def candidates(self,results):
        return [{'position':i+1,'title':p['title'],'specs':p['specs'],'price':p['offers'][0]['price'],
                 'retailer':p['offers'][0]['retailer'],'reasons':p['reasons'],'caveats':p['caveats']} for i,p in enumerate(results.get('products',[])[:4])]

    def prepare_question(self,state):
        p=state['preferences'];kind='';question=''
        if p.get('clarification_needed'):
            kind='requirement';question=p['clarification_needed']
        elif not p.get('category'):
            kind='category';question='What are you shopping for—electronics, something to wear, or something for your home?'
            last=state.get('history',[{}])[-1].get('content','').lower()
            if re.search(r'\bhome\b',last):question='What would you like for your home—for example, a chair, bedsheets, cookware or an appliance?'
            elif re.search(r'\b(?:fashion|clothes)\b',last):question='What are you looking to wear—a shirt, dress, shoes, or something else?'
            elif re.search(r'\belectronics\b',last):question='Which kind of electronics are you looking for—for example, a laptop, phone, headphones or a TV?'
        elif p.get('max_price') is None and not p.get('any_budget') and not state.get('use_model') and not state.get('stop_followups') and p.get('price_preference','any')=='any' and not p.get('assumptions',{}).get('max_price'):
            kind='budget'
            subject='a laptop with a high-end GPU' if p.get('gpu_requirement')=='high_end' else CATEGORIES.get(p['category'],'these products').lower()
            question=f'I’ll focus on {subject}. What price range feels comfortable, or should I keep the budget open?'
        # Bind required questions to their missing field; free rewriting used to
        # turn "which product?" into an unanswerable "anything else?".
        if kind and state.get('clarification_attempts',0)>=2:
            return {'pending_kind':'','question':'','intent':'clarification_failed'}
        return {'pending_kind':kind,'question':question}

    def route(self,state):
        if state.get('intent') in {'discuss','clarification_failed'}:return 'respond'
        return 'clarify' if state.get('pending_kind') else 'retrieve'

    def clarify(self,state):
        question=state.get('question') or 'What price range should I use, or is your budget open?'
        kind=state.get('pending_kind') or 'budget'  # older saved interrupts migrate safely
        answer=interrupt({'question':question,'kind':kind,'preferences':state['preferences']})
        history=state.get('history',[])+[{'role':'assistant','content':question},{'role':'user','content':answer}]
        context={'pending_kind':kind,'history':history[-8:]}
        previous=self.recover_brief(state['preferences'])
        if state.get('use_model'):context['catalog_prices']=self.search.market_context(infer_category(answer) or previous.get('category'))
        model=self.model if state.get('use_model') else None
        plan=None
        if model and hasattr(model,'interpret'):
            try:plan=model.interpret(answer,previous,context)
            except Exception:pass
        proceed=self.proceed(plan,answer,previous)
        prefs,engine,warnings=self.extract_turn(answer,previous,model,context,plan,proceed)
        no_change=all(prefs[k]==v for k,v in previous.items() if k not in {'query','clarification_needed'})
        update={'preferences':prefs,'engine':engine,'warnings':list(dict.fromkeys(warnings)),'history':history,'intent':'search','results':{},'workflow_version':2,
                'clarification_attempts':state.get('clarification_attempts',0)+1,'stop_followups':proceed or no_change or state.get('stop_followups',False)}
        return {**update,**self.prepare_question({**state,**update})}

    def retrieve(self,state):
        results=self.search.run(state['preferences'],state.get('include_historical',False),state.get('method','hybrid'))
        return {'results':results}

    def respond(self,state):
        results=state.get('results',{});products=results.get('products',[]);p=state['preferences']
        if state.get('intent')=='clarification_failed':
            message='I haven’t been able to identify the missing detail, so I’ve paused this search. '+('Tell me the item name, such as an alarm clock or a shirt, to start searching.' if not p.get('category') else 'Please restate the requirement you want me to use. Your other preferences are saved.')
        elif results.get('unresolved_requirements'):
            message='I can’t verify '+', '.join(results['unresolved_requirements'])+' from the catalog, so I haven’t called these matches. You can change that requirement, or ask for partial matches with the uncertainty shown.'
        elif not products and p.get('gpu_requirement')=='high_end':
            message='I don’t have a recently checked laptop with a qualifying high-end GPU in this catalog. I won’t substitute an ordinary laptop. We can check more retailer links or look at a dedicated GPU instead, if that would suit your workload.'
        elif not products:
            message='I couldn’t find a recently checked product that meets your recorded requirements. We can change a filter or check more products; your current requirements are still saved.'
        else:
            first=products[0];message=f"I found {len(products)} candidates that meet the recorded filters. The first is {first['title']}. "+' '.join(first['reasons'][:2])+' Stock and delivered cost still need a retailer check.'
        response_engine='grounded_template';warnings=list(state.get('warnings',[]))
        warnings=[w for w in warnings if not w.startswith('The conversational model')]
        facts=self.response_facts(results,p,message)
        if facts.get('price_limit'):message=facts['price_limit']+' '+message
        if facts.get('assumptions'):message=facts['assumptions']+' '+message
        if facts.get('release_gap'):message+=' '+facts['release_gap']
        latest=state.get('history',[{}])[-1].get('content','').lower()
        if state.get('intent')=='discuss':
            if re.search(r'what (?:is|does|are).*\b(?:gpu|vram|ram|ssd)\b',latest):
                facts['concept_gpu']='A GPU handles graphics and parallel computation. Dedicated GPU memory (VRAM) is separate from system RAM; the amount a workload needs depends on the workload.'
                facts['concept_memory']='RAM holds active working data, while an SSD stores files and applications. More storage does not substitute for RAM or GPU memory.'
        if state.get('intent')=='discuss':
            comparisons=[v for k,v in facts.items() if k.startswith('compare_')]
            if comparisons:message='Here are the recorded differences. '+' '.join(comparisons)+' '+facts['check']
        if state.get('use_model') and self.model and hasattr(self.model,'reply'):
            try:
                message=self.model.reply({'event':'results','intent':state.get('intent'),'history':state.get('history',[])[-8:],
                    'preferences':p,'candidates':self.candidates(results),'unresolved_requirements':results.get('unresolved_requirements',[]),
                    'excluded':results.get('excluded',{}),'gpu_policy':results.get('gpu_policy'),'match_status':results.get('match_status'),
                    'fallback_facts':message,'facts':facts,'stop_followups':state.get('stop_followups',False) or state.get('intent')=='clarification_failed'})
                response_engine='local_qwen'
            except Exception:
                warnings.append('The conversational draft could not be validated; this reply uses the recorded search facts.')
        followup='size' if 'What size should I look for?' in message else 'use_case' if 'Will you use it mainly for' in message else ''
        return {'history':state.get('history',[])+[{'role':'assistant','content':message}],'response_engine':response_engine,'followup_kind':followup,'warnings':list(dict.fromkeys(warnings))}

    def response_facts(self,results,p,fallback):
        products=results.get('products',[])
        facts={}
        if p.get('max_price') is not None:
            amount=f"{p['max_price']:,.2f}".rstrip('0').rstrip('.')
            comparison='below' if p.get('max_price_exclusive') else 'at or below'
            facts['price_limit']=f'I’ll keep prices {comparison} INR {amount}, including shipping where it’s recorded.'
        assumptions=results.get('assumptions',{})
        if assumptions:
            descriptions=[]
            for k,a in assumptions.items():
                v=a['value'];number=f'{v:,.0f}' if isinstance(v,(int,float)) else str(v)
                formats={'max_price':f'a budget around INR {number}','min_price':f'a starting price around INR {number}',
                         'min_ram_gb':f'{number}GB RAM','min_storage_gb':f'{number}GB storage',
                         'max_weight_kg':f'a weight target of {v}kg','min_vram_gb':f'{number}GB graphics memory'}
                descriptions.append(formats.get(k,f"{k.replace('_',' ')}: {v}"))
            facts['assumptions']='I’m starting with '+', '.join(descriptions)+'. You can adjust these suggestions; they won’t exclude other options.'
        if results.get('release_gap'):facts['release_gap']=results['release_gap']+' These are price-based alternatives, not confirmed latest releases.'
        if not products:return {**facts,'gap':fallback}
        def label(product):
            title=product['title'].split(' - ')[0]
            return title if len(title)<=95 else title[:92]+'…'
        for i,product in enumerate(products[:3],1):
            name=label(product);spec=product['specs'];offer=product['offers'][0]
            if offer['price'] is not None:facts[f'price_{i}']=f"{name} is listed at INR {offer['price']:,.0f} on {offer['retailer']}; shipping is {'unknown' if offer['shipping'] is None else 'INR '+str(offer['shipping'])}."
            if spec.get('gpu'):facts[f'gpu_{i}']=f"{name} records {spec['gpu']}"+(f" with {spec['vram_gb']}GB graphics memory" if spec.get('vram_gb') else '; graphics memory is not recorded')+'.'
            if spec.get('ram_gb'):facts[f'memory_{i}']=f"{name} records {spec['ram_gb']}GB RAM"+(f" and {spec['storage_gb']}GB storage" if spec.get('storage_gb') else '')+'.'
            if spec.get('attributes'):facts[f'attributes_{i}']=f"{name}: "+', '.join(f'{k}: {v}' for k,v in spec['attributes'].items())+'.'
        if len(products)>1:
            a,b=products[:2];sa,sb=a['specs'],b['specs']
            for key,label_text in [('gpu','GPU'),('ram_gb','RAM in GB'),('storage_gb','storage in GB')]:
                if sa.get(key) and sb.get(key):
                    if key=='gpu':facts['compare_'+key]=f"The first lists {sa[key]}; the second lists {sb[key]}. GPU names alone do not establish real workload performance."
                    else:facts['compare_'+key]=f"The first has {sa[key]}GB {'RAM' if key=='ram_gb' else 'storage'}, compared with {sb[key]}GB in the second."
            pa,pb=a['offers'][0]['price'],b['offers'][0]['price']
            if pa is not None and pb is not None:facts['compare_price']=f"The first listed price is INR {pa:,.0f}; the second is INR {pb:,.0f}. This excludes any unknown shipping."
        if p.get('gpu_requirement')=='high_end':facts['gpu_limit']='These meet the app’s stated high-end GPU model filter. GPU power limits, cooling and performance in your workload have not been verified.'
        if p.get('allow_partial_matches') and p.get('unverified_requirements'):facts['gap']='These are partial matches only. Still unverified: '+', '.join(p['unverified_requirements'])+'.'
        facts['check']='The observations have source timestamps. Confirm the selected variant, availability and delivered price with the retailer before deciding.'
        return facts

    def snapshot(self,session):
        snap=self.graph.get_state({'configurable':{'thread_id':session}})
        questions=[item.value for task in snap.tasks for item in task.interrupts]
        values=dict(snap.values)
        if values and values.get('workflow_version')!=2:
            values['results']={}
            values['warnings']=['This chat predates the matching update. Send a message to recheck its saved requirements; earlier product results are hidden.']
        return {**values,'session_id':session,'pending':questions[0] if questions else None}

    def run(self,session,message,use_model=True,include_historical=False,method='hybrid'):
        with self.lock:
            cfg={'configurable':{'thread_id':session}}
            old=self.snapshot(session)
            if old.get('pending'):
                # Options may change while answering. Update them before resuming the saved node.
                self.graph.update_state(cfg,{'use_model':use_model,'include_historical':include_historical,'method':method,
                                            'pending_kind':old['pending'].get('kind') or old.get('pending_kind') or 'budget',
                                            'question':old['pending']['question']})
                self.graph.invoke(Command(resume=message),cfg)
            else:
                updates={'message':message,'use_model':use_model,'include_historical':include_historical,'method':method}
                if old.get('workflow_version')!=2:updates['results']={}
                self.graph.invoke(updates,cfg)
            return self.snapshot(session)
