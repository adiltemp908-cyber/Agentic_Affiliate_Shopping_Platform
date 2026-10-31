"""Category routing and literal attributes. No generated product specifications."""
import re

CATEGORIES={
 'laptop':'Laptops','smartphone':'Phones','tablet':'Tablets','headphones':'Headphones & earbuds',
 'smartwatch':'Smartwatches','monitor':'Monitors','television':'Televisions','camera':'Cameras',
 'clothing':'Clothing','footwear':'Footwear','bag':'Bags & luggage','furniture':'Furniture',
 'bedding':'Bedding & bath','cookware':'Kitchen & dining','appliance':'Appliances','decor':'Home decor',
 'beauty':'Beauty & personal care','sports':'Sports & fitness','book':'Books','toy':'Toys & games',
 'grocery':'Groceries','accessory':'Electronics accessories','other':'Other products',
}
PATTERNS=[
 ('appliance',r'\b(?:room|space|fan) heaters?\b'),
 ('accessory',r'\b(?:case\s+(?:silicone\s+)?cover|silicone\s+cover|dashboard\s+mat|battery\s+for\s+cordless\s+phone)\b'),
 ('toy',r'\b(?:toy|toys|educational phone)\b'),
 ('accessory',r'\bstickers?\s+for\s+(?:phone|laptop|mobile)\b'),
 ('other',r'\b(?:chair\s+(?:hydraulic\s+pump|gas\s+lift)|(?:hydraulic\s+pump|gas\s+lift)\s+for\s+(?:office\s+)?chairs?)\b'),
 ('decor',r'^(?!.*\b(?:spy|camera|watch|watches)\b).*\bclocks?\b'),
 ('furniture',r'\b(?:study|laptop)\s+tables?\b'),
 ('accessory',r'\b(?:laptop|phone|mobile|tablet|camera)\s*(?:sleeve|case|cover|stand|charger|adapter)|\b(?:power bank|screen protector|usb hub|charging cable)\b'),
 ('bag',r'\b(?:backpacks?|handbags?|suitcases?|rucksacks?|luggage|messenger bag|tote bag|wallets?)\b'),
 ('furniture',r'\b(?:furniture|chairs?|sofas?|couches?|desks?|dining tables?|wardrobes?|bookshelves|bookcases|recliners?|beds?|mattresses)\b'),
 ('bedding',r'\b(?:bedding|bedsheets?|bed sheets?|bedspread|duvet|quilts?|comforters?|blankets?|pillows?|towels?|curtains?)\b'),
 ('cookware',r'\b(?:cookware|cookers?|frying pans?|saucepans?|kadai|tawa|handi|serving set|cook and serve set|dinner sets?|cutlery|casserole|utensils?|water bottles?|lunch box)\b'),
 ('appliance',r'\b(?:appliances?|refrigerators?|fridge|washing machine|air conditioners?|split ac|microwaves?|air fryers?|vacuum cleaners?|mixer grinder|induction cooktop|dishwashers?|ceiling fans?|water purifiers?|geysers?)\b'),
 ('decor',r'\b(?:wall art|wall clock|vases?|planters?|lamps?|wallpaper|home decor|candles?|figurines|rugs?|carpets?)\b'),
 ('clothing',r'\b(?:t[ -]?shirts?|shirts?|jeans|trousers?|pants|sarees?|saris?|kurtas?|kurtis?|dresses|dress|jackets?|hoodies|hoodie|sweaters?|leggings|shorts|bras?|underwear|socks|clothing)\b'),
 ('footwear',r'\b(?:shoes?|sneakers?|sandals?|slippers?|heels|loafers?|boots|footwear)\b'),
 ('headphones',r'\b(?:headphones?|earphones?|earbuds?|buds|bassbuds|airdopes|headsets?|airpods)\b'),
 ('smartwatch',r'\b(?:smartwatch(?:es)?|smart watches?|fitness bands?)\b'),
 ('television',r'\btelevisions?\b|\b(?:smart|oled|qled|led)\b.{0,100}\btv\b'),
 ('monitor',r'\bmonitors?\b|\b(?:ips|va|tn)\s+panel\b.*\bhdmi\b'),
 ('camera',r'\b(?:dslr|mirrorless|digital camera|action camera)\b'),
 ('tablet',r'\b(?:tablets?|ipad|galaxy tab|redmi pad|oneplus pad)\b'),
 ('smartphone',r'\b(?:smartphones?(?!\s+app\b)|mobile phones?|mobiles?(?!\s+app\b)|phones?|iphone|galaxy [masfz]\d+|redmi|poco|realme|oneplus|pixel \d+)\b'),
 ('camera',r'\bcameras?\b'),
 ('laptop',r'\b(?:laptops?|notebooks?|macbooks?|chromebooks?|ideapad|vivobook|thinkpad)\b'),
 ('beauty',r'\b(?:shampoos?|conditioner|face wash|sunscreen|lipstick|moisturi[sz]er|serum|perfume|deodorant|makeup|beauty|skin care|trimmer|shaver)\b'),
 ('sports',r'\b(?:dumbbells?|treadmills?|yoga mat|cricket bats?|badminton|tennis rackets?|bicycles?|football|basketball|fitness equipment)\b'),
 ('toy',r'\b(?:toys?|lego|puzzles?|board games?|dolls?|action figures?|building blocks)\b'),
 ('book',r'\b(?:books?|novels?|paperback|hardcover|textbooks?)\b'),
 ('grocery',r'\b(?:groceries|grocery|coffee|tea|rice|atta|flour|cooking oil|biscuits?|cereals?|chocolates?)\b'),
]
SUBTYPES={
 'decor':{'alarm clock':r'\balarm(?:\s+wall|\s+table)?\s+clocks?\b','wall clock':r'\bwall clocks?\b','table clock':r'\b(?:table|desk) clocks?\b'},
 'clothing':{'tshirt':r'\bt[ -]?shirts?\b','shirt':r'\bshirts?\b','jeans':r'\bjeans\b','saree':r'\b(?:sarees?|saris?)\b','kurta':r'\b(?:kurtas?|kurtis?)\b','dress':r'\b(?:dress|dresses)\b','jacket':r'\bjackets?\b','hoodie':r'\bhoodies?\b'},
 'footwear':{'sneakers':r'\bsneakers?\b','running shoes':r'\brunning shoes?\b','sandals':r'\bsandals?\b','boots':r'\bboots\b'},
 'furniture':{'chair':r'\bchairs?\b','sofa':r'\b(?:sofas?|couches?)\b','desk':r'\bdesks?\b','wardrobe':r'\bwardrobes?\b','mattress':r'\bmattress(?:es)?\b','bed':r'\bbeds?\b'},
 'bedding':{'bedsheet':r'\bbed\s?sheets?\b','pillow':r'\bpillows?\b','towel':r'\btowels?\b','curtain':r'\bcurtains?\b'},
 'cookware':{'pressure cooker':r'\bpressure cookers?\b','frying pan':r'\bfrying pans?\b','dinner set':r'\bdinner sets?\b','water bottle':r'\bwater bottles?\b'},
 'appliance':{'refrigerator':r'\b(?:fridge|refrigerators?)\b','washing machine':r'\bwashing machines?\b','air conditioner':r'\b(?:air conditioners?|split ac)\b','microwave':r'\bmicrowaves?\b','air fryer':r'\bair fryers?\b'},
 'headphones':{'earbuds':r'\b(?:earbuds?|airpods|tws)\b','headphones':r'\bheadphones?\b'},
}
COLORS=['black','white','blue','red','green','pink','yellow','purple','grey','gray','silver','gold','brown','beige','navy']
MATERIALS=['cotton','linen','silk','wool','polyester','leather','wood','steel','aluminium','aluminum','ceramic','glass','plastic']

def is_product_component(text):
    text=re.sub(r'\bairfryer\b','air fryer',text,flags=re.I)
    if not re.search(r'\b(?:air fryer|pressure cooker|chair|mixer grinder|vacuum cleaner|refrigerator|washing machine)\b',text,re.I):return False
    # A part named as the sold item differs from a complete product *with* that part.
    head=re.split(r'\b(?:with|includes|including|suitable for|compatible with)\b',text,maxsplit=1,flags=re.I)[0]
    return bool(re.search(r'\b(?:gaskets?|spare parts?|replacement (?:parts?|filters?)|paper liners?|air fryer\s+(?:baking\s+)?paper|baking (?:tray|paper)|silicone (?:basket|tray|liner)|handle set|hydraulic pump|gas lift|base\s+for\s+(?:revolving|office)\s+chair|base wheel|covers?|(?:refrigerator|washing machine)\s+stand)\b',head,re.I))


def infer_category(text,hint=''):
    aliases={'furniture':'furniture','home decor':'decor','cookware':'cookware','beauty and grooming':'beauty','makeup':'beauty','smart watches':'smartwatch','sports shoes':'footwear'}
    if text.lower().strip() in aliases:return aliases[text.lower().strip()]
    head=re.split(r'\b(?:with|includes|including)\b',text,maxsplit=1,flags=re.I)[0]
    if re.search(r'\b(?:tv|television|screen)\b',text,re.I) and re.search(r'\b(?:remote control|tv remote|remote suitable|remote original|remote cover|tv cover|screen cleaner|cleaner kit|remote case)\b',head,re.I):return 'accessory'
    if re.search(r'\b(?:camera|dslr|laptop|phone)\b',text,re.I) and re.search(r'\bbatter(?:y|ies)\s+for\b',head,re.I):return 'accessory'
    if re.search(r'\b(?:usb|type[- ]?c)\b.{0,35}\b(?:adaptor|adapter|charger|cable)\b',head,re.I):return 'accessory'
    if is_product_component(text):return 'other'
    for category,pattern in PATTERNS:
        if re.search(pattern,text,re.I):return category
    if hint:
        for category,pattern in PATTERNS:
            if re.search(pattern,hint,re.I):return category
    return None


def catalog_category(title,department=None):
    """A known retailer department outranks incidental title words, with explicit parts excluded."""
    if department=='book':return 'book'
    inferred=infer_category(title)
    if department in CATEGORIES and department!='other':
        if is_product_component(title):return 'other'
        if department in {'laptop','smartphone','tablet','television','monitor','camera','smartwatch','headphones'} and inferred in {'accessory','toy'}:return inferred
        return department
    return inferred or department or 'other'

def product_type(text,category):
    if category=='clothing' and re.search(r'\b(?:dress|dresses)\b',text,re.I):return 'dress'
    if category=='headphones' and re.search(r'headphones',text,re.I) and re.search(r'earbuds',text,re.I):return None
    return next((name for name,pattern in SUBTYPES.get(category,{}).items() if re.search(pattern,text,re.I)),None)

def literal_attributes(text,category):
    attrs={}
    if category=='book':return attrs  # Title words do not establish cover color/material.
    if category in {'decor','furniture','cookware'}:
        for shape,pattern in [('round',r'\b(?:round|circular)\b'),('square',r'\bsquare\b'),('rectangular',r'\brectangular\b'),('oval',r'\boval\b')]:
            if re.search(pattern,text,re.I):attrs['shape']=shape;break
        if re.search(r'\b(?:half[ -]round|semi[ -]?circular)\b',text,re.I):attrs['shape']='semicircular'
    if category=='decor' and re.search(r'\bclocks?\b',text,re.I):
        if re.search(r'\bdigital\b',text,re.I):attrs['display']='digital'
        elif re.search(r'\banalog(?:ue)?\b',text,re.I):attrs['display']='analog'
    if category in {'television','monitor','laptop','smartphone','tablet','smartwatch'}:
        # Specific panel names precede LED/LCD; QLED must never satisfy OLED.
        for display,pattern in [('amoled',r'\b(?:super\s+)?amoled\b'),('oled',r'\b(?:qd[- ]?)?oled\b'),
                                ('qled',r'\b(?:neo\s+)?qled\b'),('mini led',r'\bmini[- ]?led\b'),
                                ('led',r'\bled\b'),('lcd',r'\blcd\b')]:
            if re.search(pattern,text,re.I):attrs['display']=display;break
    for kind,options in [('color',COLORS),('material',MATERIALS)]:
        for option in options:
            if re.search(r'\b'+option+r'\b',text,re.I):attrs[kind]=option;break
    if re.search(r'\bcotton blend\b',text,re.I):attrs['material']='cotton blend'
    if re.search(r'\bpolycotton\b',text,re.I):attrs['material']='polycotton'
    if re.search(r'\b(?:women|woman|womens|women.s|ladies|female)\b',text,re.I):attrs['audience']='women'
    elif re.search(r'\b(?:men|mens|men.s|male)\b',text,re.I):attrs['audience']='men'
    if category in {'clothing','footwear'}:
        size=re.search(r'\bsize\s*[:\-]?\s*(XXXL|XXL|XL|XS|S|M|L|\d{1,2})\b',text,re.I)
        if size:attrs['size']=size[1].upper()
    return attrs

# Transparent application policy, not a benchmark ranking. TGP/thermals still matter.
HIGH_END_GPUS={'RTX 4080','RTX 4090','RTX 5080','RTX 5090','RX 7900M'}
def normalize_gpu(value):return re.sub(r'\s+',' ',str(value or '').upper()).strip()

def matches_attribute(actual,wanted):
    return str(actual or '').casefold().strip()==str(wanted).casefold().strip()
