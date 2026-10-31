"""Read only specifications whose widget identity matches the main product."""
import json,re
from .taxonomy import literal_attributes

def flipkart_details(html,expected_pid=None):
    marker=re.search(r'window\.__INITIAL_STATE__\s*=\s*',html)
    if not marker:return {},{}
    try:
        state,_=json.JSONDecoder().raw_decode(html[marker.end():]);state=state['multiWidgetState']
        pid=state['pageDataResponse']['pageContext']['productId']
        if expected_pid and not expected_pid.startswith('itm') and expected_pid!=pid:return {},{}
        pairs={}
        def walk(n):
            if isinstance(n,dict):
                try:
                    label=n['label_0']['value']['text'];value=n['label_1']['value']['text']
                    if isinstance(label,str) and isinstance(value,list) and all(isinstance(v,str) for v in value):pairs.setdefault(label,set()).add(', '.join(value))
                except (KeyError,TypeError):pass
                for v in n.values():walk(v)
            elif isinstance(n,list):
                for v in n:walk(v)
        for slot in state.get('widgetsData',{}).get('slots',[]):
            widget=slot.get('slotData',{}).get('widget',{});tracking=widget.get('tracking',{})
            if tracking.get('productId')==pid and tracking.get('widgetType') in {'atlas_product_details','atlas_rich_product_details'}:walk(widget.get('data',{}))
        fields={k:next(iter(v)) for k,v in pairs.items() if len(v)==1}
        attrs={};evidence={}
        for label,key in [('Fabric','material'),('Primary Material','material'),('Material','material'),('Color','color'),('Colour','color'),('Ideal For','audience'),('Size','size')]:
            if label in fields:
                value=fields[label];attrs[key]=value.casefold();evidence[key]=f'{label}: {value}'
                if key=='material':
                    if value.casefold() in {'pure cotton','100% cotton'}:attrs[key]='cotton'
                if key=='audience':attrs[key]=literal_attributes(value,'clothing').get('audience',value.casefold())
        return attrs,evidence
    except (ValueError,KeyError,TypeError):return {},{}
