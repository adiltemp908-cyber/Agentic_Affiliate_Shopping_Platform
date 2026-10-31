// Capture actual local-model results; no mocked responses or replaced product cards.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..');
const cases=[
 {id:'round-digital-alarm-clock',messages:['I want a digital alarm clock that is round in shape','Nothing else, just show me the options'],category:'decor',attributes:{shape:'round',display:'digital'}},
 {id:'oled-televisions',messages:['I want a oled TV'],category:'television',attributes:{display:'oled'}},
 {id:'laptop-budget-specifications',messages:['I need a laptop under 60000 with at least 16 GB RAM and 512 GB SSD'],category:'laptop',ram:16,storage:512,max:60000},
];
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const reportPath=path.join(root,'reports/showcase-run.json');
 const summary=process.argv[2]&&fs.existsSync(reportPath)?JSON.parse(fs.readFileSync(reportPath,'utf8')).filter(e=>e.id!==process.argv[2]):[];
 fs.mkdirSync(path.join(root,'docs/screenshots'),{recursive:true});
 fs.mkdirSync(path.join(root,'reports'),{recursive:true});
 try{
  for(const example of cases.filter(e=>!process.argv[2]||e.id===process.argv[2])){
   const page=await browser.newPage({viewport:{width:1600,height:1100},deviceScaleFactor:1});
   const errors=[];page.on('pageerror',e=>errors.push(e.message));
   await page.goto(process.env.SHORTLIST_URL||'http://127.0.0.1:8777');
   await page.locator('#retailer-coverage').waitFor();
   let state;
   for(const message of example.messages){
    await page.locator('#query').fill(message);
    const response=page.waitForResponse(r=>r.url().endsWith('/api/search')&&r.request().method()==='POST',{timeout:240000});
    await page.locator('#search-button').click();state=await(await response).json();
    await page.locator('#search-button:not([disabled])').waitFor({timeout:240000});
   }
   const products=state.results?.products||[];
   if(state.engine!=='local_qwen'||state.pending||!products.length||errors.length)throw Error(example.id+': expected successful local-model search');
   if(state.results.method!=='hybrid')throw Error(example.id+': rebuild the semantic index first');
   for(const [key,value] of Object.entries(example.attributes||{}))if(state.preferences.attributes?.[key]!==value)throw Error(example.id+': preference not recorded: '+key);
   if(example.max&&(state.preferences.max_price!==example.max||!state.preferences.max_price_exclusive))throw Error(example.id+': ceiling not recorded');
   for(const p of products){
    if(p.category!==example.category)throw Error(example.id+': incorrect category');
    for(const [key,value] of Object.entries(example.attributes||{}))if(p.specs.attributes?.[key]!==value)throw Error(example.id+': missing '+key);
    if(example.ram&&p.specs.ram_gb<example.ram)throw Error('RAM constraint');
    if(example.storage&&p.specs.storage_gb<example.storage)throw Error('Storage constraint');
    if(example.max&&p.offers.some(o=>o.price==null||o.price+(o.shipping||0)>=example.max))throw Error('Budget constraint');
   }
   await page.evaluate(()=>window.scrollTo(0,document.querySelector('.workspace').getBoundingClientRect().top+window.scrollY-20));
   await page.screenshot({path:path.join(root,'docs/screenshots',example.id+'.png')});
   const firstLink=page.locator('.product-card').first().locator('a.visit');
   const productUrl=await firstLink.getAttribute('href');
   const popupPromise=page.waitForEvent('popup',{timeout:30000});
   await firstLink.click();
   const retailerPage=await popupPromise;
   await retailerPage.waitForLoadState('domcontentloaded',{timeout:60000}).catch(()=>{});
   await retailerPage.waitForTimeout(6000);
   const retailerText=await retailerPage.locator('body').innerText({timeout:30000});
   fs.writeFileSync(path.join(root,'reports',example.id+'-retailer.txt'),retailerText);
   const blocked=/enter the characters you see|sorry, we just need to make sure|service unavailable|access denied|verify you are human/i.test(retailerText);
   const retailerScreenshot=path.join(root,blocked?'reports':'docs/screenshots',example.id+'-product.png');
   await retailerPage.screenshot({path:retailerScreenshot});
   summary.push({id:example.id,messages:example.messages,results:products.length,engine:state.engine,
    retrieval:state.results.method,retailers:[...new Set(products.flatMap(p=>p.offers.map(o=>o.retailer)))],
    criteria:await page.locator('#criteria').innerText(),top_product:products[0].title,
    product_url:productUrl,retailer_page_title:await retailerPage.title(),retailer_final_url:retailerPage.url(),
    retailer_page_blocked:blocked,captured_at:new Date().toISOString()});
   fs.writeFileSync(path.join(root,'reports/showcase-run.json'),JSON.stringify(summary,null,2));
   if(blocked)throw Error(example.id+': retailer page unavailable; diagnostic capture saved in reports');
   console.log(JSON.stringify(summary.at(-1)));await retailerPage.close();await page.close();
  }
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
