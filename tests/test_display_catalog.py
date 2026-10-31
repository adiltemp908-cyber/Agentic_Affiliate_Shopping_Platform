import pytest
from shortlist.acquisition import category_cards
from shortlist.ingest import specs
from shortlist.schema import Preferences
from shortlist.search import Search
from shortlist.taxonomy import infer_category, literal_attributes, catalog_category
from test_core import catalog, listing


@pytest.mark.parametrize('title,display',[
    ('LG 55 inch OLED Smart TV','oled'),
    ('Samsung QLED LED Smart TV','qled'),
    ('Samsung Neo QLED Smart TV','qled'),
    ('Sony QD-OLED Smart TV','oled'),
    ('TCL Mini LED Smart TV','mini led'),
    ('Samsung AMOLED smartphone','amoled'),
    ('Samsung OLED Ultra HD Smart Tizen TV with AI Football Mode','oled'),
    ('LG OLED Smart TV with Magic Remote Control','oled'),
])
def test_panel_types_are_distinct(title,display):
    parsed=specs(title)
    assert parsed['attributes']['display']==display
    assert ('oled' in parsed['features'])==(display=='oled')


@pytest.mark.parametrize('title',[
    'Universal Remote Control for LG OLED Smart TV',
    'Waterproof TV Cover for LG OLED TV',
    'Deluxe Screen Cleaner Kit for OLED TV',
    'Compatible LG Smart TV Remote Suitable for Any LG LED OLED Television',
])
def test_tv_accessories_do_not_become_oled_televisions(title):
    assert infer_category(title)=='accessory'
    assert 'display' not in specs(title).get('attributes',{})


def test_card_specifications_supply_display_when_title_does_not():
    html='''<div data-id="TV123456"><a href="/smart-tv/p/itm12345678?pid=TV123456">
    <img alt="LG 55 inch Smart Television"></a><span class="Nx9bqj">₹99,000</span>
    <ul><li>Ultra HD (4K) | OLED</li></ul></div>'''
    row=category_cards(html,'https://www.flipkart.com/televisions/pr?sid=ckf,czl','television')[0]
    assert row.attributes['display']=='oled' and 'oled' in row.features
    assert 'OLED' in row.evidence['specifications']


def test_oled_search_excludes_qled_and_unknown_panels(catalog):
    for n,title in enumerate(['LG OLED Smart TV','Samsung QLED Smart TV','Sony Smart TV'],1):
        catalog.upsert(listing(n,title=title,category='television',
            attributes=literal_attributes(title,'television'),features=specs(title)['features']))
    prefs=Preferences(category='television',query='I want an OLED TV',
        attributes={'display':'oled'},required_features=['oled'],any_budget=True)
    results=Search(catalog).run(prefs.model_dump(),method='bm25')
    assert [p['title'] for p in results['products']]==['LG OLED Smart TV']


def test_refreshed_product_labels_use_the_sold_item():
    assert infer_category('Havells Comforter 2000 Watt Room Heater')=='appliance'
    assert infer_category('Digitek Rechargeable Lithium-ion Battery for Canon DSLR Camera')=='accessory'
    assert infer_category('Canon DSLR Camera with Rechargeable Battery for Travel')=='camera'
    assert infer_category('Samsung Original USB Type-C Travel Adaptor for Galaxy Tab')=='accessory'
    assert infer_category('Samsung Galaxy Tab Tablet with USB Type-C Charger')=='tablet'


@pytest.mark.parametrize('title,department',[
    ('Thermosteel Tea/Coffee Dispenser Steel Flask','cookware'),
    ('Fridge Bottle Set for Refrigerator','cookware'),
    ('Airtight Rice Storage Container','cookware'),
    ('Cotton T-Shirt with Toy Dinosaur Print','clothing'),
    ('Smart Tizen TV with Football Mode','television'),
])
def test_department_keeps_containers_and_feature_words_out_of_wrong_categories(title,department):
    assert catalog_category(title,department)==department


def test_department_still_excludes_parts():
    assert catalog_category('Air Fryer Paper Liners','appliance')=='other'
    assert catalog_category('TV Remote Control for OLED Smart TV','television')=='accessory'
