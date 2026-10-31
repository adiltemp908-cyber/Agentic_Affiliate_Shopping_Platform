import re
from .schema import Preferences
from .ingest import BRANDS
from .taxonomy import infer_category,product_type,literal_attributes,normalize_gpu,MATERIALS,COLORS,CATEGORIES
from .interpretation import apply_interpretation,enforce_price_ceiling

def amount(text):
    text=text.lower().replace(',','').strip()
    m=re.search(r'(\d+(?:\.\d+)?)\s*(k|lakh|lac)?',text)
    if not m:return None
    return float(m[1])*({'k':1000,'lakh':100000,'lac':100000}.get(m[2],1))

def has_unsupported_terms(phrase):
    # Model output occasionally repeats an already represented RAM/use-case
    # clause as "unverified". Keep only phrases containing additional terms.
    represented={'at','least','minimum','maximum','min','max','under','below','above','up','to','with','and','or','for','of','a','the','laptop','laptops',
                 'gb','tb','kg','ram','memory','ssd','hdd','storage','weight','gaming','non','upgradeable','upgradable','touchscreen','touch','screen',
                 'oled','backlit','keyboard','programming','coding','study','office','travel','editing','work','use','required','need','want'}
    represented.update(b.lower() for b in BRANDS)
    represented.update(MATERIALS+COLORS)
    represented.update({'local','ai','machine','learning','design','3d','rendering'})
    represented.update({'shirt','shirts','tshirt','dress','dresses','jeans','kurta','saree','chair','sofa','headphones','earbuds','phone','smartphone','tablet','monitor','television','smartwatch','cotton','blend','size','men','women','xl','xxl','s','m','l','anc','active','noise','cancellation','cancelling','wireless','bluetooth','5g','waterproof','induction'})
    return any(t not in represented for t in re.findall(r'[a-z]+',phrase.lower()))

def extract(message,previous=None,model=None,context=None,interpretation=None):
    previous=Preferences.model_validate(previous or {}).model_dump()
    # Recover a concrete brief in older saved chats whose category was missed.
    if not previous['category'] and previous.get('query'):
        recovered=infer_category(previous['query'])
        if recovered:
            previous['category']=recovered
            previous['product_type']=product_type(previous['query'],recovered)
            previous['attributes']={**literal_attributes(previous['query'],recovered),**previous['attributes']}
    if previous['gpu_requirement']=='any' and any(re.search(r'high[ -]?end.*(?:gpu|graphics)',s,re.I) for s in previous['unverified_requirements']):
        previous['gpu_requirement']='high_end'
    result=dict(previous);warnings=[];engine='rules';semantic_plan=interpretation
    previous['clarification_needed']=None
    lower=message.lower()
    contextual_budget=bool(context and context.get('pending_kind')=='budget' and re.fullmatch(r'\s*(?:(?:any(?: budget)?|anything|no|none|nope|not sure|whatever|doesn.t matter|no preference|open|flexible|no limit)|(?:₹|inr|rs\.?)?\s*\d[\d,.]*\s*(?:k|lakh|lac)?)\s*[.!]?\s*',lower))
    category=infer_category(message)
    if category and category!=previous['category']:
        # A new category starts a new product brief; laptop RAM/GPU constraints
        # must never leak into a shirt search. Keep only an explicitly open budget.
        previous=Preferences(category=category,any_budget=previous['any_budget'],query='').model_dump()
        result=dict(previous)
    if re.search(r'\$|\busd\b|\beur\b|€|\bgbp\b',lower):
        raise ValueError('This first catalog uses INR. Please specify a rupee budget; currencies are never silently converted.')
    if model and not contextual_budget:
        try:
            if hasattr(model,'interpret'):
                if semantic_plan is None:semantic_plan=model.interpret(message,previous,context)
            else:
                result=model.preferences(message,previous,context) if context is not None else model.preferences(message,previous)
                result=Preferences.model_validate(result).model_dump()
            engine='local_qwen'
        except Exception as exc:
            warnings.append(f'Local model unavailable: {str(exc)[:180]}. Explicit rules were used; please review the filters.')
    elif contextual_budget:engine='context_rules'
    else:warnings.append('Rule-based interpretation selected; review the filters for unsupported requirements.')
    # Budget values must come from the user, never from model defaults.
    for field in ['max_price','min_price','any_budget','min_ram_gb','min_storage_gb','max_weight_kg','min_vram_gb','gpu_requirement','gpu_models','attributes','allow_partial_matches','sort_by']:
        result[field]=previous[field]
    result['category']=category or previous['category']
    result['product_type']=product_type(message,result['category']) or previous['product_type']
    if result['category']=='headphones' and result['product_type']=='headphones' and not re.search(r'over[ -]ear|on[ -]ear',lower):result['product_type']=None
    # A model may infer requirements from a use case. Only explicit mentions may
    # change hard filters; otherwise keep the user's prior values.
    mentions={
        'min_ram_gb':r'\b(ram|memory)\b',
        'min_storage_gb':r'\b(storage|ssd|hdd|disk)\b',
        'max_weight_kg':r'\b(weight|weigh|kg|kilograms?|lightweight|light)\b',
        'exclude_gaming':r'\bgaming\b',
        'require_upgradeable_ram':r'\b(upgrad\w*|expand\w*)\b',
    }
    for field,pattern in mentions.items():
        if not re.search(pattern,lower):result[field]=previous[field]
    for field in ['brands','excluded_brands']:
        allowed={b.lower() for b in previous[field]}|{b.lower() for b in BRANDS if re.search(r'\b'+re.escape(b.lower())+r'\b',lower)}
        result[field]=list(dict.fromkeys(previous[field]+[b for b in result.get(field,[]) if b.lower() in allowed]))
    result['required_features']=list(dict.fromkeys(previous['required_features']+[f for f in result.get('required_features',[]) if f in lower or f=='touchscreen' and re.search(r'touch[ -]screen',lower)]))
    # Unsupported requirements must be verbatim user phrases, not suggestions.
    result['unverified_requirements']=list(dict.fromkeys(previous['unverified_requirements']+[s for s in result.get('unverified_requirements',[]) if s.strip() and s.casefold() in lower and has_unsupported_terms(s)]))
    # Literal hard constraints override model output. Existing values are retained.
    if re.search(r'\b(no budget|any budget|unlimited budget|no limit|skip budget)\b',lower):
        result.update(max_price=None,min_price=0,any_budget=True)
    if context and context.get('pending_kind')=='budget' and re.fullmatch(r'\s*(?:any|anything|no|none|nope|not sure|whatever|doesn.t matter|no preference|open|flexible)\s*[.!]?\s*',lower):
        result.update(max_price=None,min_price=0,any_budget=True)
    number=r'(\d[\d,]*(?:\.\d+)?\s*(?:k|lakh|lac)?)(?![\w.]|\s*(?:kg|gb|tb)\b)'
    budget=re.search(r'(?:under|below|up to|upto|at most|budget(?:\s+of)?|maximum|max)\s*(?:rs\.?|inr|₹)?\s*'+number,lower)
    if not budget:
        budget=re.search(r'(?:₹|inr|rs\.)\s*'+number,lower)
    if not budget and (previous.get('max_price') is None and not previous.get('any_budget')):
        budget=re.fullmatch(r'\s*(?:₹|inr|rs\.?)?\s*'+number+r'\s*',lower)
    if budget:
        result.update(max_price=amount(budget[1]),max_price_exclusive=False,any_budget=False)
    range_match=re.search(r'between\s*(?:₹|rs\.?|inr)?\s*'+number+r'\s+and\s*(?:₹|rs\.?|inr)?\s*'+number,lower)
    if range_match:result.update(min_price=amount(range_match[1]),max_price=amount(range_match[2]),max_price_exclusive=False,any_budget=False)
    ram=re.search(r'(\d+)\s*gb\s*(?:of\s*)?(?:ram|memory)',lower)
    storage=re.search(r'(\d+(?:\.\d+)?)\s*(gb|tb)\s*(?:ssd|storage)',lower)
    weight=re.search(r'(?:under|below|less than|at most)\s*(\d(?:\.\d+)?)\s*kg',lower)
    if ram:result['min_ram_gb']=int(ram[1])
    if storage:result['min_storage_gb']=int(float(storage[1])*(1024 if storage[2]=='tb' else 1))
    if weight:result['max_weight_kg']=float(weight[1])
    if re.search(r'\b(?:high[ -]?end|top[ -]?end|flagship|powerful)\s*(?:dedicated\s*)?(?:gpu|graphics)',lower):result['gpu_requirement']='high_end'
    elif re.search(r'\b(?:dedicated|discrete)\s*(?:gpu|graphics)',lower):result['gpu_requirement']='dedicated'
    if re.search(r'(?:any|no need for|do not need|don.t need|ignore)\s*(?:a\s*)?(?:high[ -]?end\s*)?(?:gpu|graphics)',lower):
        result.update(gpu_requirement='any',gpu_models=[],min_vram_gb=None)
    gpu_matches=re.findall(r'\b(?:RTX|GTX)\s*\d{3,4}(?:\s*Ti)?\b|\bRX\s*\d{4}M?\b',message,re.I)
    if gpu_matches:result.update(gpu_models=[normalize_gpu(g) for g in gpu_matches],gpu_requirement='dedicated')
    vram=re.search(r'(\d+)\s*gb\s*(?:of\s*)?(?:vram|graphics memory)',lower)
    if vram:result['min_vram_gb']=int(vram[1])
    attrs=literal_attributes(message,result['category']);result['attributes']={**previous['attributes'],**attrs}
    if context and context.get('followup_kind')=='size' and result['category'] in {'clothing','footwear'} and re.fullmatch(r'\s*(?:XXXL|XXL|XL|XS|S|M|L|\d{1,2})\s*',message,re.I):
        result['attributes']['size']=message.strip().upper()
    for attr in ['color','size','material','audience']:
        if re.search(r'\b(?:any|ignore|no preference for)\s+'+attr+r'\b',lower):result['attributes'].pop(attr,None)
    if re.search(r'\b(?:partial matches|approximate matches|relax unsupported|show alternatives)\b',lower):result['allow_partial_matches']=True
    if re.search(r'\b(?:exact matches|strict matches|no compromises)\b',lower):result['allow_partial_matches']=False
    if re.search(r'\b(?:cheaper|cheapest|lowest price|price low to high)\b',lower):result['sort_by']='price_asc'
    if re.search(r'\b(?:most expensive|highest price|price high to low)\b',lower):result['sort_by']='price_desc'
    if re.search(r'\b(?:sort by relevance|best matches)\b',lower):result['sort_by']='relevance'
    if 'cheaper' in lower and context and context.get('previous_results'):
        price=context['previous_results'][0].get('price')
        if price and price>0:
            if result['max_price'] is None or price<=result['max_price']:result.update(max_price=price,max_price_exclusive=True)
            result['any_budget']=False
    if re.search(r'(?:no|not|avoid|exclude|non[- ]?)\s*gaming',lower):result['exclude_gaming']=True
    if re.search(r'(?:allow|include|okay with)\s*gaming',lower):result['exclude_gaming']=False
    if 'upgradeable ram' in lower or 'upgradable ram' in lower:
        result['require_upgradeable_ram']=not bool(re.search(r'(?:no need|don.t need|not required).*upgrad',lower))
    for brand in BRANDS:
        b=brand.lower()
        if re.search(r'\b(?:avoid|exclude|not|no)\s+'+b+r'\b',lower):
            result['excluded_brands']=list(set(result.get('excluded_brands',[])+[brand]))
            result['brands']=[v for v in result.get('brands',[]) if v.lower()!=b]
        elif re.search(r'\b'+b+r'\b',lower):
            # Explicit named brands in rule mode form a whitelist.
            if engine=='rules':result['brands']=list(set(result.get('brands',[])+[brand]))
    if 'any brand' in lower:result.update(brands=[],excluded_brands=[])
    elif re.search(r'\b(?:only|instead|switch to|what about|prefer)\b',lower):
        named=[b for b in BRANDS if re.search(r'\b'+re.escape(b)+r'\b',message,re.I) and not re.search(r'(?:avoid|exclude|not|no)\s+'+re.escape(b),message,re.I)]
        if named:result['brands']=named
    for feature in ['touchscreen','oled','backlit keyboard','anc','wireless','bluetooth','5g','waterproof','induction']:
        if re.search(r'\b'+re.escape(feature)+r'\b',lower) and not re.search(r'(?:no|without|avoid)\s+'+feature,lower):
            result['required_features']=list(set(result.get('required_features',[])+[feature]))
        if re.search(r'(?:remove|ignore|don.t need|no need for)\s+(?:the\s+)?'+feature,lower):
            result['required_features']=[f for f in result['required_features'] if f!=feature]
    if re.search(r'active noise cancell?ation|noise cancell?ing',lower):result['required_features']=list(set(result['required_features']+['anc']))
    cases=[s for s in ['programming','gaming','study','office','travel','editing','ai','machine learning','3d','design'] if re.search(r'\b'+re.escape(s)+r'\b',lower)]
    if result.get('exclude_gaming'):cases=[s for s in cases if s!='gaming']
    if cases:result['use_cases']=list(set(result.get('use_cases',[])+cases))
    if result.get('exclude_gaming'):result['use_cases']=[s for s in result.get('use_cases',[]) if s!='gaming']
    if result['category']=='laptop' and not result['exclude_gaming'] and result['gpu_requirement']=='any' and re.search(r'gaming laptop|laptop for gaming',lower):result['gpu_requirement']='dedicated'
    # Retrieval keeps the brief, not the literal short answer to a clarification.
    # Never let a model replace "high-end GPU laptop" with "any budget laptop".
    if context and context.get('pending_kind') in {'budget','category'} and len(message.split())<=5 and not category:
        result['query']=previous.get('query') or result['category'] or 'product'
    else:
        initial=previous.get('query','') if category==previous['category'] or not category else ''
        result['query']=(initial+' '+message).strip()[-2000:]
    result['clarification_needed']=None
    if semantic_plan is not None:
        try:
            result,semantic_warnings,_=apply_interpretation(message,result,semantic_plan)
            warnings.extend(semantic_warnings)
        except Exception as exc:
            warnings.append(f'Could not validate the conversation interpretation: {str(exc)[:140]}. Explicit filters were retained.')
            engine='rules'
    supported_gpu=result['gpu_requirement']!='any' or result['gpu_models']
    result['unverified_requirements']=[s for s in result['unverified_requirements'] if not (supported_gpu and re.search(r'gpu|graphics',s,re.I))]
    # These cannot currently be proved by catalog text; do not silently ignore
    # them even when the model is disabled or fails.
    for pattern in [r'(?:long|good|all.day)\s+battery(?:\s+life)?',r'linux(?:\s+compatibility)?',r'\d+\s*hours?\s*(?:of\s*)?battery',r'color accurate',r'\b(?:ergonomic|orthopedic|water resistant)\b']:
        found=re.search(pattern,lower)
        if found:result['unverified_requirements'].append(found[0])
    if re.search(r'(?:ignore|remove|don.t need|no need for)\s+(?:the\s+)?(?:battery|linux|unverified|unsupported)',lower):result['unverified_requirements']=[]
    unique={}
    for phrase in result['unverified_requirements']:unique.setdefault(phrase.casefold(),phrase)
    result['unverified_requirements']=list(unique.values())
    result=enforce_price_ceiling(result,message)
    if not result['category'] and result.get('product_type'):result['category']='other'
    if result['max_price'] is None:result['max_price_exclusive']=False
    result=Preferences.model_validate(result).model_dump()
    for field in list(result['assumptions']):
        if result.get(field) not in (None,False,0,[],{},'any'):result['assumptions'].pop(field,None)
    if result['any_budget']:
        result['assumptions'].pop('max_price',None);result['assumptions'].pop('min_price',None)
    # A small catalog cannot establish suitability for every natural-language wish.
    if any(s in lower for s in ['battery','linux','repair','warranty','delivery','color accurate']):
        warnings.append('Battery life, Linux compatibility, repairability, warranty and delivery are not verified filters in this catalog. Check the source before purchase.')
    if result.get('unverified_requirements'):
        warnings.append('Requirements needing manual verification: '+', '.join(result['unverified_requirements']))
    return result,engine,warnings
