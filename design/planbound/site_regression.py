from playwright.sync_api import sync_playwright
from pathlib import Path
import json,hashlib
root=Path(__file__).resolve().parents[1];out=root/'site-evidence';result={};logs=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 ctx=b.new_context(viewport={'width':1440,'height':900});page=ctx.new_page();page.on('pageerror',lambda e:logs.append(str(e)));page.on('console',lambda m:logs.append(m.type+': '+m.text) if m.type in ['error','warning'] else None)
 url=(root/'planbound-site.html').as_uri();page.goto(url+'#/contract',wait_until='networkidle');page.wait_for_function('PB.siteReady&&PB.ready');page.click('#start-button');result['boot_main_focus']=page.evaluate('document.activeElement.id==="view"')
 page.click('[data-next]');page.check('#consent');page.click('[data-submit]');page.wait_for_function('PB.store.get().contract.confirmed')
 def route(path):
  page.evaluate('(p)=>PB.router.go(p)',path);page.wait_for_function('(p)=>PB.router.current===p&&!PB.router.busy',arg=path);page.wait_for_timeout(150)
 route('/plan-review');one=[{'id':'r','resource':'aws_security_group','name':'web','op':'update','before':{},'after':{'cidr_blocks':['0.0.0.0/0']},'attrs':{'stateful':False,'blast':1}}];page.fill('#paste-plan',json.dumps(one));page.click('[data-load-plan]');page.locator('[data-action=reject]').click();page.click('[data-apply]');result['empty_apply_event']=page.evaluate('PB.store.get().records.at(-1)');page.select_option('#sample-plan','sample-b');page.click('[data-apply]');result['normal_apply_count']=page.evaluate('PB.store.get().records.filter(r=>r.event==="applied"&&r.change.resource!=="apply_set").length')
 # Screen every final route at the requested dimensions.
 for width,height in [(1440,900),(390,844)]:
  page.set_viewport_size({'width':width,'height':height})
  for path in ['/','/how-it-works','/contract','/plan-review','/evidence','/about','/legal','/outside']:
   route(path)
   if path=='/':page.wait_for_function('PB.tree!==undefined&&PB.tree!==null');page.wait_for_timeout(650)
   page.screenshot(path=str(out/((path.strip('/') or 'home')+'-'+str(width)+'.png')))
   assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),path
 result['final_screenshots']=16
 page.set_viewport_size({'width':1440,'height':900});route('/')
 result['continuity']=page.evaluate('PB.checkContinuity()')
 result['leaf_colors']=page.evaluate('PB.tree.uniforms.uLeafColors.value.map(c=>c.getHexString())')
 result['seed_hashes_valid']=page.evaluate('async()=>{for(const r of PB.store.get().records.filter(r=>r.seed)){if(await PB.engine.hash(r.contract)!==r.contract.hash||r.plan.id!=="sample-a"||r.plan.hash!==PB.engine.fnv(JSON.stringify(PB.engine.plans["sample-a"])))return false}return true}')
 page.wait_for_timeout(600)
 result['home_timing']=page.evaluate('()=>new Promise(resolve=>{const samples=[];let last=performance.now();function f(t){samples.push(t-last);last=t;if(samples.length<180)requestAnimationFrame(f);else resolve({mean:samples.reduce((a,b)=>a+b,0)/samples.length,max:Math.max(...samples)})}requestAnimationFrame(f)})')
 route('/about');page.evaluate('PB.lifecycle.disposeHero();for(let i=0;i<100;i++)PB.perf.sample(40,.04)');route('/');page.wait_for_function('!!PB.tree&&!PB.globe.disposed');result['disposed_quality_recreation']=page.evaluate('({quality:PB.quality,dpr:PB.globe.renderer.getPixelRatio(),disposals:PB.lifecycle.heroDisposals,errors:PB.errors})')
 # Storage and Web Crypto fallback, in isolated contexts.
 ctx.close();fallback=b.new_context(viewport={'width':390,'height':844},reduced_motion='reduce');f=fallback.new_page();f.add_init_script("Storage.prototype.getItem=function(){throw Error('storage blocked')};Storage.prototype.setItem=function(){throw Error('storage blocked')};Object.defineProperty(window.crypto,'subtle',{value:undefined});")
 f.goto(url+'#/contract',wait_until='networkidle');f.wait_for_function('PB.siteReady&&PB.ready');f.click('#start-button');f.click('[data-next]');f.check('#consent');f.click('[data-submit]');f.wait_for_function('PB.store.get().contract.confirmed');result['no_storage_crypto_fallback']=f.evaluate('({confirmed:PB.store.get().contract.confirmed,hash:PB.store.get().contract.hash,storage:PB.storageUnavailable,errors:PB.errors})');fallback.close();b.close()
 result['console']=logs;result['bytes']=(root/'planbound-site.html').stat().st_size;result['sha256']=hashlib.sha256((root/'planbound-site.html').read_bytes()).hexdigest();(out/'final-regression.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2))
