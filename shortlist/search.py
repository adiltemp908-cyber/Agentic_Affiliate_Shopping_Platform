"""Our retrieval and ranking: BM25 + local embeddings, hard filters, RRF fusion."""
import hashlib
import json
import math
import re
import threading
from collections import Counter
import numpy as np
from . import config
from .catalog import freshness
from .schema import Preferences
from .taxonomy import HIGH_END_GPUS,normalize_gpu,matches_attribute

STOP={'a','an','the','i','need','want','for','with','and','or','of','to','my','me','please','under','below','budget','inr','rs','at','least','show','find','it','that','is','be','up','to','laptops'}
def tokens(text):
    return [t for t in re.findall(r'[a-z]+|\d+(?:\.\d+)?',text.lower()) if t not in STOP]

def document(row):
    return ' '.join(str(row.get(k) or '') for k in ['title','category','product_type','brand','model','cpu','gpu'])+' '+' '.join(row.get('features',[]))+' '+' '.join(row.get('attributes',{}).values())

def fingerprint(rows):
    return hashlib.sha256(json.dumps([(r['retailer'],r['source_id'],document(r)) for r in rows],ensure_ascii=False).encode()).hexdigest()

class Search:
    def __init__(self,catalog):
        self.catalog=catalog;self.model=None;self.lock=threading.Lock()
        self.index_path=config.DATA/'embeddings.npz'

    def encoder(self):
        if self.model is None:
            from sentence_transformers import SentenceTransformer
            import torch
            torch.set_num_threads(4)
            self.model=SentenceTransformer(str(config.EMBEDDING_PATH),device='cpu',local_files_only=True,trust_remote_code=False)
        return self.model

    def market_context(self,category):
        rows=[r for r in self.catalog.records() if r.get('category')==category and freshness(r)=='recent' and r.get('price') and r.get('availability')!='out_of_stock']
        prices=list({r['product_id']:r['price'] for r in rows}.values())
        affordable=float(np.quantile(prices,.25)) if prices else None
        step=10**max(0,int(math.log10(affordable))-1) if affordable else 1
        return {'category':category,'currency':'INR','source':'Recent catalog observations, not a representative survey of the Indian market',
                'affordable_starting_point':round(affordable/step)*step if affordable else None,
                'count':len(prices),'lower_quartile':round(float(np.quantile(prices,.25))) if prices else None,
                'median':round(float(np.median(prices))) if prices else None,
                'upper_quartile':round(float(np.quantile(prices,.75))) if prices else None}

    def build(self):
        rows=self.catalog.records()
        if not rows:raise ValueError('Import a catalog before building embeddings.')
        with self.lock:
            texts=[document(r) for r in rows]
            signatures=[hashlib.sha256(t.encode()).hexdigest() for t in texts];cached={}
            if self.index_path.exists():
                try:
                    with np.load(self.index_path,allow_pickle=False) as old:
                        if 'signatures' in old:cached={str(k):v for k,v in zip(old['signatures'],old['vectors'])}
                except (OSError,ValueError,KeyError):pass
            missing=list(dict.fromkeys(s for s in signatures if s not in cached))
            if missing:
                lookup=dict(zip(signatures,texts))
                vectors=self.encoder().encode([lookup[s] for s in missing],batch_size=32,normalize_embeddings=True,show_progress_bar=False)
                cached.update(zip(missing,vectors))
            matrix=np.asarray([cached[s] for s in signatures],dtype=np.float32)
            # Atomic replacement protects searches from a partial index write.
            temporary=self.index_path.with_suffix('.tmp.npz')
            np.savez_compressed(temporary,vectors=matrix,fingerprint=np.array(fingerprint(rows)),signatures=np.array(signatures))
            temporary.replace(self.index_path)
        return {'records':len(rows),'dimensions':matrix.shape[1],'encoded':len(missing),'reused':len(rows)-len(missing),'fingerprint':fingerprint(rows)}

    def bm25(self,rows,query):
        docs=[Counter(tokens(document(r))) for r in rows]
        lens=np.array([sum(d.values()) for d in docs]);average=max(float(lens.mean()),1) if len(rows) else 1
        df=Counter(t for d in docs for t in d)
        scores=np.zeros(len(rows),dtype=float)
        for term in set(tokens(query)):
            idf=math.log(1+(len(rows)-df[term]+.5)/(df[term]+.5))
            for i,d in enumerate(docs):
                tf=d[term]
                if tf:scores[i]+=idf*tf*2.2/(tf+1.2*(.25+.75*lens[i]/average))
        return scores

    def run(self,prefs,include_historical=False,method='hybrid',limit=6):
        p=Preferences.model_validate(prefs)
        assumptions={k:v.model_dump() for k,v in p.assumptions.items()}
        rows=self.catalog.records();eligible=[];excluded=Counter()
        unresolved=p.unverified_requirements if not p.allow_partial_matches else []
        for i,r in enumerate(rows):
            reason=None
            state=freshness(r)
            if r.get('source_kind')=='fixture':reason='test fixture'
            elif not p.category or r.get('category','laptop')!=p.category:reason='different category'
            elif p.product_type and r.get('product_type')!=p.product_type:reason='different product type'
            elif unresolved:reason='requested capability not verified'
            elif state!='recent' and not include_historical:reason='not recently verified'
            elif r['availability']=='out_of_stock':reason='out of stock'
            elif r['currency']!=p.currency:reason='currency mismatch'
            elif p.brands and r['brand'].lower() not in {b.lower() for b in p.brands}:reason='brand preference'
            elif r['brand'].lower() in {b.lower() for b in p.excluded_brands}:reason='excluded brand'
            elif p.max_price is not None and r['price'] is None:reason='unknown price'
            elif r['price'] is not None and ((p.max_price is not None and (r['price']+(r.get('shipping') or 0)>p.max_price or p.max_price_exclusive and r['price']+(r.get('shipping') or 0)==p.max_price)) or r['price']<p.min_price):reason='outside budget'
            elif p.min_ram_gb and (r['ram_gb'] is None or r['ram_gb']<p.min_ram_gb):reason='RAM missing or insufficient'
            elif p.min_storage_gb and (r['storage_gb'] is None or r['storage_gb']<p.min_storage_gb):reason='storage missing or insufficient'
            elif p.max_weight_kg and (r['weight_kg'] is None or r['weight_kg']>p.max_weight_kg):reason='weight missing or excessive'
            elif p.exclude_gaming and r['gaming'] is not False:reason='non-gaming status not verified'
            elif p.require_upgradeable_ram and r['upgradeable_ram'] is not True:reason='RAM upgradeability not verified'
            elif p.gpu_requirement=='high_end' and normalize_gpu(r.get('gpu')) not in HIGH_END_GPUS:reason='high-end GPU not verified'
            elif p.gpu_requirement=='dedicated' and not re.match(r'^(RTX|GTX|RX)\s*\d',normalize_gpu(r.get('gpu'))):reason='dedicated GPU not verified'
            elif p.gpu_models and normalize_gpu(r.get('gpu')) not in {normalize_gpu(g) for g in p.gpu_models}:reason='requested GPU not verified'
            elif p.min_vram_gb and (r.get('vram_gb') is None or r['vram_gb']<p.min_vram_gb):reason='VRAM missing or insufficient'
            elif any(not matches_attribute(r.get('attributes',{}).get(k),v) for k,v in p.attributes.items()):reason='requested attribute not verified'
            elif not set(p.required_features).issubset(set(r['features'])):reason='required feature not verified'
            if reason:excluded[reason]+=1
            else:eligible.append(i)
        retrieval_query=' '.join(filter(None,[p.query,p.category,p.product_type]))
        bm=self.bm25(rows,retrieval_query);dense=None;warnings=[];actual='bm25'
        if method in {'hybrid','semantic'}:
            if self.index_path.exists():
                try:
                    with np.load(self.index_path,allow_pickle=False) as index:
                        if str(index['fingerprint'])!=fingerprint(rows):raise ValueError('Catalog changed; rebuild the semantic index.')
                        with self.lock:
                            vector=self.encoder().encode([retrieval_query],normalize_embeddings=True,show_progress_bar=False)[0]
                        dense=index['vectors']@vector
                    actual=method
                except Exception as exc:warnings.append(f'Semantic retrieval unavailable: {str(exc)[:160]}. BM25 used.')
            else:warnings.append('Semantic index is not built. BM25 retrieval used.')
        lexical_order=sorted(eligible,key=lambda i:(-bm[i],rows[i]['source_id']))
        semantic_order=sorted(eligible,key=lambda i:-dense[i]) if dense is not None else []
        lr={i:rank+1 for rank,i in enumerate(lexical_order)};sr={i:rank+1 for rank,i in enumerate(semantic_order)}
        ranked=[]
        for i in eligible:
            if bm[i]<=0 and (dense is None or dense[i]<.22):continue
            if actual=='hybrid':score=1/(60+lr[i])+1/(60+sr[i])
            elif actual=='semantic':score=float(dense[i])
            else:score=float(bm[i])
            ranked.append((score,i))
        ranked.sort(key=lambda x:(-x[0],rows[x[1]]['source_id']))
        # Inferred specifications prefer candidates, but never exclude them.
        def assumption_fit(item):
            row=rows[item[1]];scores=[]
            for field,a in assumptions.items():
                value=a['value']
                actual=row.get({'max_price':'price','min_price':'price','min_ram_gb':'ram_gb','min_storage_gb':'storage_gb','min_vram_gb':'vram_gb','max_weight_kg':'weight_kg'}.get(field,field))
                if isinstance(value,(int,float)) and not isinstance(value,bool) and value>0:
                    scores.append(0 if not isinstance(actual,(int,float)) or actual<=0 else min(1,value/actual if field.startswith('max_') else actual/value))
                elif field=='attributes' and isinstance(value,dict):scores.append(sum(matches_attribute((actual or {}).get(k),v) for k,v in value.items())/max(len(value),1))
                elif field=='gpu_requirement':scores.append(float(normalize_gpu(row.get('gpu')) in HIGH_END_GPUS) if value=='high_end' else float(bool(re.match(r'^(RTX|GTX|RX)\s*\d',normalize_gpu(row.get('gpu'))))))
                elif field=='gpu_models' and isinstance(value,list):scores.append(float(normalize_gpu(row.get('gpu')) in {normalize_gpu(v) for v in value}))
                elif field in {'brands','excluded_brands'} and isinstance(value,list):
                    found=row.get('brand','').casefold() in {v.casefold() for v in value}
                    scores.append(float(not found if field=='excluded_brands' else found))
                elif field=='required_features' and isinstance(value,list):scores.append(len(set(value)&set(row.get('features',[])))/max(len(value),1))
                elif field=='exclude_gaming':scores.append(float(row.get('gaming') is False) if value else 1)
                elif field=='require_upgradeable_ram':scores.append(float(row.get('upgradeable_ram') is True) if value else 1)
            return sum(scores)/max(len(scores),1)
        if assumptions:ranked.sort(key=assumption_fit,reverse=True)
        if p.price_preference=='budget':
            priced=[rows[i]['price'] for i in eligible if rows[i].get('price')]
            if priced and p.max_price is None and not p.any_budget and 'max_price' not in assumptions:
                quartile=float(np.quantile(priced,.25));step=10**max(0,int(math.log10(quartile))-1)
                assumptions['max_price']={'value':round(quartile/step)*step, 'reason':'An adjustable starting point from the lower-priced quarter of matching catalog offers.'}
        elif p.price_preference in {'midrange','premium'}:
            priced=[rows[i]['price'] for i in eligible if rows[i].get('price')]
            if priced:
                target=float(np.quantile(priced,.5 if p.price_preference=='midrange' else .75))
        # Only documented specification tiers are used, never invented benchmarks.
        # Within a GPU tier, text relevance remains the tiebreaker.
        if p.sort_by=='relevance':
            for priority in reversed(p.priorities):
                if priority=='gpu':
                    def gpu_tier(item):
                        gpu=normalize_gpu(rows[item[1]].get('gpu'))
                        return 2 if gpu in HIGH_END_GPUS else 1 if re.match(r'^(RTX|GTX|RX)\s*\d',gpu) else 0
                    ranked.sort(key=gpu_tier,reverse=True)
                elif priority in {'ram','storage','weight','price'}:
                    field={'ram':'ram_gb','storage':'storage_gb','weight':'weight_kg','price':'price'}[priority]
                    direction=-1 if priority in {'ram','storage'} else 1
                    ranked.sort(key=lambda item:(rows[item[1]].get(field) is None,direction*(rows[item[1]].get(field) or 0)))
        if p.sort_by=='relevance' and p.price_preference=='budget':
            ranked.sort(key=lambda item:(rows[item[1]].get('price') is None,-assumption_fit(item),(rows[item[1]].get('price') or 0)+(rows[item[1]].get('shipping') or 0)))
        elif p.sort_by=='relevance' and p.price_preference in {'midrange','premium'} and priced:
            ranked.sort(key=lambda item:(rows[item[1]].get('price') is None,-assumption_fit(item),abs((rows[item[1]].get('price') or 0)-target)))
        if p.sort_by in {'price_asc','price_desc'}:
            ranked.sort(key=lambda x:(rows[x[1]]['price'] is None, ((rows[x[1]]['price'] or 0)+(rows[x[1]].get('shipping') or 0))*(1 if p.sort_by=='price_asc' else -1)))
        grouped={}
        for score,i in ranked:
            r=dict(rows[i]);r['freshness']=freshness(r)
            group=grouped.setdefault(r['product_id'],{'product_id':r['product_id'],'title':r['title'],'brand':r['brand'],'category':r.get('category','laptop'),
                'specs':{k:r.get(k) for k in ['model','ram_gb','storage_gb','cpu','gpu','vram_gb','attributes','weight_kg','gaming','upgradeable_ram','features']},
                'match_confidence':r['match_confidence'],'offers':[],'score':round(score,5),'bm25':round(float(bm[i]),3),
                'semantic':round(float(dense[i]),3) if dense is not None else None})
            group['offers'].append(r)
        results=list(grouped.values())[:limit]
        for r in results:
            r['offers'].sort(key=lambda o:(o['price'] is None,(o['price'] or 0)+(o['shipping'] or 0)))
            best=r['offers'][0];evidence=[];caveats=[]
            if p.max_price and best['price']:
                amount=f'{p.max_price:,.2f}'.rstrip('0').rstrip('.')
                evidence.append(f"Listed price is {'below' if p.max_price_exclusive else 'at or below'} your INR {amount} limit.")
            for field,minimum,label in [('ram_gb',p.min_ram_gb,'GB RAM'),('storage_gb',p.min_storage_gb,'GB storage')]:
                if minimum:evidence.append(f"{r['specs'][field]} {label} meets your minimum of {minimum}.")
            if p.max_weight_kg:evidence.append(f"Listed weight {r['specs']['weight_kg']} kg meets your limit.")
            if p.require_upgradeable_ram:evidence.append('RAM upgradeability is explicitly recorded in the imported evidence.')
            if p.required_features:evidence.append('Recorded features: '+', '.join(p.required_features)+'.')
            if p.gpu_requirement!='any' or p.gpu_models:evidence.append('Recorded GPU: '+str(r['specs']['gpu'])+'.')
            if p.min_vram_gb:evidence.append(f"Recorded graphics memory: {r['specs']['vram_gb']}GB.")
            if p.attributes:evidence.append('Recorded attributes: '+', '.join(f'{k}: {v}' for k,v in p.attributes.items())+'.')
            if p.price_preference=='budget':evidence.append('Lower-priced option among the eligible catalog listings.')
            if p.release_preference!='any':caveats.append('Release date is not recorded; this is not a verified recent or latest launch.')
            if p.allow_partial_matches and p.unverified_requirements:caveats.append('Partial match only; not verified: '+', '.join(p.unverified_requirements)+'.')
            if not evidence:evidence.append('Selected by product-text relevance; suitability has not been independently tested.')
            if best['freshness']!='recent':caveats.append('Historical or unverified offer. Price and availability need a current check.')
            if best['shipping'] is None:caveats.append('Shipping cost is unknown; this is not a guaranteed delivered total.')
            if best['availability']=='unknown':caveats.append('Stock status is unknown.')
            if r['match_confidence']=='retailer_listing':caveats.append('Exact cross-store variant identity is incomplete; listings are kept separate.')
            r.update(reasons=evidence,caveats=caveats)
        return {'products':results,'eligible_offers':len(eligible),'total_offers':len(rows),
                'excluded':dict(excluded),'method':actual,'warnings':warnings,
                'unresolved_requirements':list(unresolved),'match_status':'partial' if p.release_preference!='any' or p.allow_partial_matches and p.unverified_requirements else 'verified_filters',
                'assumptions':assumptions,'release_gap':'Release dates are missing, so I cannot verify which of these is a recent or latest launch.' if p.release_preference!='any' else None,
                'sort_by':p.sort_by,'priorities':p.priorities,
                'gpu_policy':'High-end means recorded RTX 4080/4090/5080/5090 or RX 7900M in this application; TGP, cooling and real workload performance still need checking.' if p.gpu_requirement=='high_end' else None,
                'ranking':('Reciprocal-rank fusion of BM25 and local cosine similarity after hard constraints. No commission or sponsored-position signal.' if actual=='hybrid' else 'Product-text relevance after hard constraints.')+(' Adjustable assumptions influence ordering without excluding alternatives.' if assumptions else '')+(' Price preference orders the observed price segment; price does not establish quality.' if p.price_preference!='any' else '')+(' Stated priorities order recorded GPU tiers or numeric specifications; this is not a measured performance comparison.' if p.priorities and p.sort_by=='relevance' else ''),
                'include_historical':include_historical}

