"""Grounded semantic changes, rather than a model-generated replacement form."""
import re
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .schema import Preferences
from .taxonomy import CATEGORIES,COLORS,MATERIALS,normalize_gpu

Editable=Literal['category','product_type','gpu_requirement','gpu_models','min_vram_gb',
 'attributes','allow_partial_matches','sort_by','max_price','min_price','any_budget',
 'min_ram_gb','min_storage_gb','max_weight_kg','brands','excluded_brands','exclude_gaming',
 'require_upgradeable_ram','required_features','use_cases','priorities','price_preference','release_preference','max_price_exclusive']

class Change(BaseModel):
    model_config=ConfigDict(extra='forbid')
    field:Editable
    value:str|float|bool|list[str]|dict[str,str]|None=Field(description='The typed new preference value. Use a JSON string for enums, number for amounts, boolean for flags, array for lists, object for attributes.')
    evidence:str=Field(min_length=1,max_length=1000,description='Exact quote from the latest USER message supporting this change. Never quote assistant messages.')
    basis:Literal['stated','inferred']='stated'
    reason:str=Field(default='',max_length=500,description='For inferred values, briefly explain the working assumption to the shopper.')

class Unsupported(BaseModel):
    model_config=ConfigDict(extra='forbid')
    requirement:str=Field(min_length=1,max_length=100,description='One specific requested capability not represented by supported fields, e.g. Linux compatibility. Never the complete shopping request.')
    evidence:str=Field(min_length=1,max_length=300)

class Interpretation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    intent:Literal['search','discuss','proceed']='search'
    changes:list[Change]=Field(max_length=16)
    unsupported:list[Unsupported]=Field(max_length=6)
    clarification:str|None=Field(max_length=250,description='Use null unless a requirement is genuinely ambiguous. Do not ask for missing optional specifications or budget here.')

def normalized(text):
    return re.sub(r'\s+',' ',str(text).casefold().replace('’',"'").replace('–','-').replace('—','-')).strip()

NUMBER_WORDS=dict(zip('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen'.split(),range(20)))
NUMBER_WORDS.update(dict(zip('twenty thirty forty fifty sixty seventy eighty ninety'.split(),range(20,100,10))))

def numeric_values(text,field):
    values=set()
    for m in re.finditer(r'\d[\d,]*(?:\.\d+)?',text):
        n=float(m[0].replace(',',''));tail=text[m.end():].lstrip().lower()
        if field in {'max_price','min_price'}:
            scale=100000 if re.match(r'lakhs?|lacs?',tail) else 1000 if re.match(r'k\b|thousand',tail) else 1
        elif field=='min_storage_gb':scale=1024 if re.match(r'tb|terabytes?',tail) else 1
        else:scale=1
        values.add(n*scale)
    total=part=0;active=False
    for word in re.findall(r'[a-z]+',text.lower())+['END']:
        if word in NUMBER_WORDS:part+=NUMBER_WORDS[word];active=True
        elif word=='hundred' and active:part=max(part,1)*100
        elif word in {'thousand','lakh','lakhs','lac'} and active:
            total+=part*(1000 if word=='thousand' else 100000);part=0
        elif word=='and' and active:continue
        elif active:
            n=total+part
            if field=='min_storage_gb' and word in {'tb','terabyte','terabytes'}:n*=1024
            values.add(float(n));total=part=0;active=False
    return values

def explicit_price_ceiling(message):
    """Keep a stated comparison's operand and operator; never subtract a rupee."""
    text=normalized(message)
    words='|'.join(NUMBER_WORDS)+r'|hundred|thousand|lakhs?|lacs?|and'
    number=r'(?:\d[\d,]*(?:\.\d+)?\s*(?:k\b|thousands?\b|lakhs?\b|lacs?\b)?|(?:(?:'+words+r')\b[\s-]*)+)'
    pattern=r'(?P<op>no more than|not more than|less than|at most|up to|upto|under|below|maximum|max|<=|<)\s*(?:(?:₹|inr\b|rs\.?|rupees\b)\s*)?(?P<amount>'+number+r')'
    found=None
    for match in re.finditer(pattern,text):
        if match.start() and text[match.start()-1].isalnum():continue
        if re.search(r'\b(?:not|no)\s*$',text[:match.start()]):continue
        tail=text[match.end():].lstrip()
        if re.match(r'(?:kg|kilograms?|grams?|gb|tb|mb|ram|vram|hours?|inches|inch|cm|hz|mah)\b',tail):continue
        values=numeric_values(match['amount'],'max_price')
        if len(values)!=1:continue
        value=next(iter(values))
        if 0<value<=10_000_000:
            found={'max_price':value,'max_price_exclusive':match['op'] in {'less than','under','below','<'}}
    return found

def enforce_price_ceiling(result,message):
    ceiling=explicit_price_ceiling(message)
    if ceiling:
        result.update(ceiling,any_budget=False)
        if result.get('min_price',0)>=ceiling['max_price']:result['min_price']=0
        for field in ('max_price','min_price','max_price_exclusive'):result['assumptions'].pop(field,None)
    return result

def apply_interpretation(message,base,interpretation):
    """Validate quoted changes without requiring the user's grammar to match regexes."""
    plan=Interpretation.model_validate(interpretation)
    result=Preferences.model_validate(base).model_dump();warnings=[];accepted=[]
    quote_source=normalized(message)
    numeric={'max_price','min_price','min_ram_gb','min_storage_gb','max_weight_kg','min_vram_gb'}
    pending=[];inferred={};ceiling=explicit_price_ceiling(message)
    for change in plan.changes:
        if ceiling and change.field in {'max_price','max_price_exclusive','any_budget'}:continue
        if ceiling and change.field=='min_price' and not re.search(r'\b(?:above|over|greater than|at least|minimum)\b',message,re.I):continue
        evidence=normalized(change.evidence)
        value=change.value
        if change.field in numeric and isinstance(value,bool):continue
        if change.field in numeric and value is not None:
            try:value=Preferences.model_validate({change.field:value}).model_dump()[change.field]
            except (ValueError,TypeError):continue
        is_inferred=change.basis=='inferred'
        if change.field in numeric and value is not None and value not in numeric_values(change.evidence,change.field):is_inferred=True
        semantic_fields={'category','product_type','price_preference','release_preference','priorities','sort_by'}
        if evidence not in quote_source and not is_inferred and change.field not in semantic_fields:
            if value==result.get(change.field):continue
            if change.field in numeric and value in numeric_values(message,change.field):evidence=quote_source
            else:
                warnings.append('One proposed explicit filter could not be linked to your request and was left unchanged.');continue
        if is_inferred:
            try:value=Preferences.model_validate({change.field:value}).model_dump()[change.field]
            except (ValueError,TypeError):continue
            if change.field=='sort_by':continue  # sorting commands need a user request; suggestions already influence ranking
            # Navigation and qualitative preferences describe meaning; inferred
            # amounts/specs are separate, reversible ranking suggestions.
            if change.field in {'category','product_type','price_preference','release_preference','use_cases','priorities','sort_by'}:
                pending.append((change.field,value));accepted.append(change.model_dump())
            elif value in (None,False,[],{},'any'):
                inferred[change.field]=None
            else:
                inferred[change.field]={'value':value,'reason':change.reason or 'A starting assumption based on your request; you can change it.'}
            continue
        if change.field=='gpu_requirement' and value!='any' and re.search(r'(?:do not need|don.t need|no need for|ignore|forget)\b[^.!;,]{0,45}\b(?:gpu|graphics)\b',evidence):
            continue
        if change.field in {'gpu_models','brands','excluded_brands'} and isinstance(value,list):
            compact=re.sub(r'\s+','',evidence)
            if any(re.sub(r'\s+','',normalized(v)) not in compact for v in value):continue
            if change.field=='gpu_models':value=[normalize_gpu(v) for v in value]
        if change.field=='required_features' and isinstance(value,list):
            supported={'touchscreen','oled','backlit keyboard','anc','wireless','bluetooth','5g','waterproof','induction'}
            value=[v for v in value if v in supported and (re.search(r'\b'+re.escape(v)+r'\b',evidence) or v=='anc' and re.search(r'noise cancel',evidence))]
        if change.field in numeric and value is not None:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or value not in numeric_values(change.evidence,change.field):
                warnings.append('An inferred numeric requirement was ignored; only stated amounts are used.');continue
            units={'min_ram_gb':r'\b(?:ram|memory|gigs)\b','min_storage_gb':r'\b(?:storage|ssd|hdd|disk|tb|terabytes?)\b',
                   'max_weight_kg':r'\b(?:weight|weigh|kg|kilograms?)\b','min_vram_gb':r'\b(?:vram|graphics memory)\b'}
            if change.field in units and not re.search(units[change.field],evidence):
                warnings.append('A number attached to a different requirement was ignored.');continue
            if change.field in {'max_price','min_price'} and re.search(r'\b(?:gb|tb|kg|hours?|inches)\b',evidence) and not re.search(r'₹|\b(?:rs|inr|rupees|budget|price|thousand|lakh|spend)\b',evidence):
                continue
        if change.field=='category' and value is not None and value not in CATEGORIES:continue
        if change.field=='attributes' and isinstance(value,dict):
            value={k:v for k,v in value.items() if k in {'material','color','size','audience','shape','display'}}
            # A quoted color/fabric need not belong to a small preset vocabulary.
            # The evidence check below still rejects unstated hard attributes.
            value={k:v for k,v in value.items() if not (k=='color' and normalized(v) in MATERIALS) and not (k=='material' and normalized(v) in COLORS)}
            # A copied audience label is not evidence of a color or fabric.
            audiences={normalized(v) for v in [value.get('audience',''),result.get('attributes',{}).get('audience','')] if v}
            value={k:v for k,v in value.items() if not (k in {'color','material'} and normalized(v) in audiences)}
            if not value and change.value:continue
            value={k:({'small':'S','medium':'M','large':'L','extra large':'XL'}.get(normalized(v),v.upper()) if k=='size' else normalized(v)) for k,v in value.items()}
            aliases={'S':['small'],'M':['medium'],'L':['large'],'XL':['extra large'],'men':['mens','male','man','husband','him'],
                     'women':['womens','woman','female','wife','her'],'gray':['grey'],'grey':['gray'],'wood':['wooden'],'round':['circular'],'analog':['analogue']}
            value={k:v for k,v in value.items() if any(re.search(r'\b'+re.escape(normalized(term))+r'\b',evidence) for term in [v]+aliases.get(v,[]))}
            if not value and change.value:continue
        try:
            # A malformed field must not discard unrelated valid changes.
            value=Preferences.model_validate({change.field:value}).model_dump()[change.field]
        except (ValueError,TypeError):
            warnings.append('An invalid interpreted filter was ignored.');continue
        pending.append((change.field,value));accepted.append(change.model_dump())
    # Clear incompatible constraints for an actual semantic category change.
    category=next((value for field,value in pending if field=='category'),result['category'])
    if category!=result['category']:
        result=Preferences(category=category,any_budget=result['any_budget'],query=message).model_dump()
    for field,value in pending:
        result[field]={**result['attributes'],**value} if field=='attributes' and isinstance(value,dict) and value else value
        result['assumptions'].pop(field,None)
        if field=='price_preference' and value!=base.get('price_preference','any'):
            result['assumptions'].pop('max_price',None);result['assumptions'].pop('min_price',None)
    for field,assumption in inferred.items():
        current=result.get(field)
        if assumption is None:result['assumptions'].pop(field,None)
        elif current in (None,False,0,[],{},'any') and not any(f==field for f,v in pending):result['assumptions'][field]=assumption
    if any(field=='any_budget' and value is True for field,value in pending):result.update(max_price=None,min_price=0)
    if result['any_budget']:
        result['assumptions'].pop('max_price',None);result['assumptions'].pop('min_price',None)
    if result['price_preference']=='budget':result['assumptions'].pop('min_price',None)
    if any(field=='max_price' and value is not None for field,value in pending):result['any_budget']=False
    if any(field=='max_price' for field,value in pending) and not any(field=='max_price_exclusive' for field,value in pending):result['max_price_exclusive']=False
    if result['any_budget']:result['max_price_exclusive']=False
    if any(field=='gpu_requirement' and value=='any' for field,value in pending):
        result.update(gpu_models=[],min_vram_gb=None)
        if not any(field=='priorities' for field,value in pending):result['priorities']=[p for p in result['priorities'] if p!='gpu']
        if base['gpu_requirement']!='any':result['query']=message
    unsupported=[]
    rejected_ambiguity=False
    for item in plan.unsupported:
        evidence=normalized(item.evidence);requirement=normalized(item.requirement)
        if evidence not in quote_source:continue
        # A supported concept or a restatement of the whole brief is a parsing
        # uncertainty, not evidence that the catalog lacks the requested product.
        broad=(len(requirement.split())>10 or (requirement==quote_source and len(requirement.split())>5) or
               re.search(r'\b(?:most important|high[ -]?end)\b',requirement))
        if broad:
            if not any(c['field'] not in {'category','product_type','any_budget','max_price','min_price'} for c in accepted):rejected_ambiguity=True
            continue
        if requirement not in evidence:continue
        unsupported.append(item.requirement)
    # Preserve independent unresolved requirements. Supported GPU interpretation
    # must not erase a separate request for measured battery life.
    carried=[s for s in result['unverified_requirements'] if not (result['gpu_requirement']!='any' and re.search(r'gpu|graphics',s,re.I))]
    result['unverified_requirements']=list(dict.fromkeys(carried+unsupported))
    if result['price_preference']!='any':
        result['unverified_requirements']=[s for s in result['unverified_requirements'] if normalized(s) not in {'cheap','affordable','inexpensive','budget friendly','budget-friendly'}]
    if result['release_preference']!='any':
        result['unverified_requirements']=[s for s in result['unverified_requirements'] if re.fullmatch(r'(?:latest|recent|new(?:est)?)(?:\s+(?:release|launch|model|phone)s?)*',normalized(s)) is None]
    clarification=plan.clarification if normalized(plan.clarification) not in {'none','null','','n/a'} else None
    result['clarification_needed']=clarification or ('Which specific requirement should I focus on? I could not reliably interpret that part of your request.' if rejected_ambiguity else None)
    result=enforce_price_ceiling(result,message)
    result=Preferences.model_validate(result).model_dump()
    return result,list(dict.fromkeys(warnings)),accepted
