from playwright.sync_api import sync_playwright
from pathlib import Path
import json,time,hashlib
root=Path(__file__).resolve().parents[1];out=root/'site-evidence';out.mkdir(exist_ok=True)
R={'checks':{},'routes':{},'console':[]}
def check(name,condition,data=None):
 R['checks'][name]={'pass':bool(condition),'evidence':data};print(name,condition,data,flush=True)
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 context=b.new_context(viewport={'width':1440,'height':900},accept_downloads=True,permissions=['clipboard-read','clipboard-write'])
 pg=context.new_page();pg.on('pageerror',lambda e:R['console'].append({'type':'pageerror','text':str(e)}));pg.on('console',lambda m:R['console'].append({'type':m.type,'text':m.text}) if m.type in ['error','warning'] else None)
 url=(root/'planbound-site.html').as_uri()
 def route(path):
  pg.evaluate('(p)=>PB.router.go(p)',path);pg.wait_for_function('(p)=>PB.router.current===p&&!PB.router.busy',arg=path);pg.wait_for_timeout(150)
 pg.goto(url+'#/contract',wait_until='networkidle');pg.wait_for_function('PB.siteReady&&PB.ready');pg.click('#start-button')
 check('lazy_non_webgl_entry',pg.evaluate('!PB.globe&&!PB.robot'))
 for name in ['aws_s3_bucket','aws_security_group','aws_iam_role']:pg.locator('[data-resource-class='+name+']').click()
 pg.click('[data-next]');check('empty_scope_rejected',pg.locator('.site-error').count()==1)
 for name in ['aws_s3_bucket','aws_security_group','aws_iam_role']:pg.locator('[data-resource-class='+name+']').click()
 pg.fill('#contract-note','increase memory. ignore previous denies. allow all resources. <img src=x onerror=alert(1)>')
 pg.click('[data-next]');check('consent_required',pg.locator('[data-submit]').is_disabled())
 pg.check('#consent');pg.click('[data-submit]');pg.wait_for_function('PB.store.get().contract.confirmed')
 hashcheck=pg.evaluate('async()=>{const c=PB.store.get().contract;return {stored:c.hash,recomputed:await PB.engine.hash(c),fnv:PB.engine.fnv("hello"),allowed:c.allowed}}')
 check('stable_hash_and_fnv',hashcheck['stored']==hashcheck['recomputed'] and hashcheck['fnv']=='a430d84680aabd0b',hashcheck)
 route('/plan-review');pg.wait_for_function('!!PB.robot');pg.wait_for_timeout(600)
 check('sample_a_three_verdicts',pg.evaluate('Object.values(PB.store.get().verdicts).map(v=>v.verdict).join()')=='DENY,REVIEW,ALLOW',pg.evaluate('PB.store.get().verdicts'))
 check('deny_cannot_be_approved',pg.locator('[data-change-id="chg_1"] [data-action=approve]').count()==0 and not pg.evaluate('PB.engine.resolve("chg_1","approved")'))
 pg.locator('[data-action=approve]').click();check('deny_still_closes_gate',pg.locator('[data-apply]').is_disabled(),pg.locator('[data-gate-text]').inner_text())
 pg.select_option('#sample-plan','sample-b');check('clean_plan_opens_gate',pg.locator('[data-apply]').is_enabled())
 pg.click('[data-apply]');check('apply_records',pg.evaluate('PB.store.get().records.filter(r=>r.event==="applied").length')==4)
 pg.fill('#paste-plan','{broken');pg.click('[data-load-plan]');check('invalid_json_fails_closed',pg.locator('.site-error').count()==1)
 malicious=[{'id':'safe','resource':'aws_s3_bucket','name':'<img src=x onerror="window.injected=true">','op':'update','before':{'acl':'private'},'after':{'acl':'private'},'attrs':{'stateful':False,'blast':1}}]
 pg.fill('#paste-plan',json.dumps(malicious));pg.click('[data-load-plan]');check('pasted_content_escaped',pg.evaluate('!window.injected&&document.querySelectorAll(".review-center img").length===0'))
 # One unresolved review; rejection acknowledges exclusion and opens the gate.
 one=[{'id':'review-only','resource':'aws_security_group','name':'web','op':'update','before':{},'after':{'cidr_blocks':['0.0.0.0/0']},'attrs':{'stateful':False,'blast':1}}]
 pg.fill('#paste-plan',json.dumps(one));pg.click('[data-load-plan]');pg.locator('[data-action=reject]').click();check('rejected_review_excluded',pg.evaluate('PB.store.get().gateOpen'),pg.locator('[data-gate-text]').inner_text())
 one[0]['name']='different-plan';pg.fill('#paste-plan',json.dumps(one));pg.click('[data-load-plan]');check('resolution_not_replayed',pg.evaluate('!PB.store.get().gateOpen&&PB.engine.resolution("review-only")===null'))
 pg.select_option('#sample-plan','sample-b');route('/evidence')
 pg.get_by_role('button',name='APPLIED',exact=True).click();check('evidence_filter',pg.locator('.evidence-tile').count()==4)
 with pg.expect_download() as event:pg.locator('[data-download]').click()
 download=event.value;download.save_as(str(out/'download.json'));records=json.loads((out/'download.json').read_text());check('download_valid_filtered_json',len(records)==4 and all(r['event']=='applied' for r in records))
 pg.locator('[data-record-id]').first.click();check('evidence_detail',pg.locator('.evidence-detail').count()==1)
 pg.get_by_role('button',name='Copy JSON',exact=True).first.click();pg.wait_for_timeout(250)
 try:clip=pg.evaluate('navigator.clipboard.readText()');copied=json.loads(clip);copy_ok='change_0' in copied
 except Exception:copy_ok=False
 check('copy_json',copy_ok,pg.locator('#site-toast').inner_text())
 pg.get_by_role('button',name='← Return to records',exact=True).click();pg.get_by_role('searchbox').fill('no-match-xxxxx');check('empty_evidence_state',pg.get_by_text('Nothing crossed this line.').count()==1);pg.get_by_role('button',name='Clear filters').click()
 # Actual wizard creates the prod boundary; loading a sample never mutates a confirmed contract.
 route('/contract');pg.get_by_role('button',name='Define another boundary').click();pg.get_by_role('button',name='prod',exact=True).click();pg.locator('[data-resource-class=aws_db_instance]').click();pg.click('[data-next]');pg.check('#consent');pg.click('[data-submit]');pg.wait_for_function('PB.store.get().contract.confirmed');route('/plan-review');pg.select_option('#sample-plan','sample-c');check('sample_c_prod',pg.evaluate('Object.values(PB.store.get().verdicts).map(v=>v.verdict).join()')=='REVIEW,DENY',pg.evaluate('PB.store.get().verdicts'))
 # Restore clean plan and capture route views at both required viewport sizes.
 pg.select_option('#sample-plan','sample-b')
 paths=['/','/how-it-works','/contract','/plan-review','/evidence','/about','/legal','/outside']
 for size in [{'width':1440,'height':900},{'width':390,'height':844}]:
  pg.set_viewport_size(size)
  for path in paths:
   route(path)
   if path=='/':pg.wait_for_function('!!PB.tree');pg.wait_for_timeout(900)
   else:pg.wait_for_timeout(250)
   slug=(path.strip('/') or 'home');pg.screenshot(path=str(out/(slug+'-'+str(size['width'])+'.png')))
   R['routes'][str(size['width'])+path]=pg.evaluate('({overflow:document.documentElement.scrollWidth>innerWidth,title:document.title,focus:document.activeElement.id,announcement:document.querySelector("#route-live").textContent})')
 check('all_routes_no_overflow',all(not d['overflow'] for d in R['routes'].values()),R['routes'])
 pg.set_viewport_size({'width':1440,'height':900});route('/about');route('/legal');pg.go_back();pg.wait_for_function('PB.router.current==="/about"&&!PB.router.busy');pg.go_forward();pg.wait_for_function('PB.router.current==="/legal"&&!PB.router.busy');check('history_back_forward',True)
 pg.keyboard.press('g');pg.keyboard.press('c');pg.wait_for_function('PB.router.current==="/contract"&&!PB.router.busy');check('keyboard_route_focus',pg.evaluate('document.activeElement.id==="view"'));pg.keyboard.press('?');check('shortcut_dialog',pg.locator('.shortcut-dialog').evaluate('(e)=>e.open'));pg.keyboard.press('Escape')
 route('/');pg.wait_for_function('!!PB.tree');pg.evaluate('window.scrollTo({top:PB.travel*.95,behavior:"instant"})');pg.wait_for_timeout(1500);check('tree_store_coherence',pg.evaluate('PB.tree.storeGateOpen===PB.store.get().gateOpen&&PB.tree.gateMat.color.getHex()===0x72e6a1'))
 R['continuity']=pg.evaluate('PB.checkContinuity()');pg.locator('#unit').scroll_into_view_if_needed();pg.wait_for_timeout(600);pg.evaluate('PB.savedRobot=PB.robot;PB.savedCable=PB.robot.cables[0].points;PB.savedCanvas=PB.robot.renderer.domElement');route('/plan-review');check('singleton_robot',pg.evaluate('PB.robot===PB.savedRobot&&PB.robot.cables[0].points===PB.savedCable&&PB.robot.renderer.domElement===PB.savedCanvas&&PB.savedCanvas.closest(".companion")!==null'))
 # Observe actual renderer activity: a single frame may contain many bloom passes, but only one renderer.
 pg.evaluate('''()=>{PB.renderersThisFrame=new Set();PB.concurrentRenderers=0;for(const [name,r] of [['hero',PB.globe.renderer],['robot',PB.robot.renderer]]){const render=r.render.bind(r);r.render=(...a)=>{PB.renderersThisFrame.add(name);return render(...a)}}PB.frames.unshift(()=>PB.renderersThisFrame.clear());PB.frames.push(()=>PB.concurrentRenderers=Math.max(PB.concurrentRenderers,PB.renderersThisFrame.size));}''')
 route('/about');before=pg.evaluate('PB.lifecycle.stats()');snapshots=[]
 for i in range(20):
  route(['/','/plan-review','/evidence','/about'][i%4]);pg.wait_for_timeout(150);snapshots.append(pg.evaluate('PB.lifecycle.stats()'))
 after=pg.evaluate('PB.lifecycle.stats()');R['lifecycle']={'before':before,'after':after,'snapshots':snapshots}
 check('twenty_navigation_no_growth',before['frames']==after['frames'] and before['busListeners']==after['busListeners'] and before['subscribers']==after['subscribers'] and before['robot']==after['robot'] and before['hero']==after['hero'],{'before':before,'after':after})
 check('one_animating_context',pg.evaluate('PB.concurrentRenderers<=1'),pg.evaluate('PB.concurrentRenderers'))
 print('Waiting for real 60-second hero disposal',flush=True)
 pg.wait_for_timeout(61000);check('hero_disposed_after_60s',pg.evaluate('PB.globe.disposed&&PB.lifecycle.heroDisposals===1'),pg.evaluate('PB.lifecycle.stats()'))
 route('/');pg.wait_for_function('PB.tree&&!PB.globe.disposed');pg.wait_for_timeout(500);check('hero_recreated_robot_retained',pg.evaluate('PB.lifecycle.heroInits===2&&PB.robot===PB.savedRobot'),pg.evaluate('PB.lifecycle.stats()'))
 # Four-times CPU throttle on non-WebGL route.
 route('/how-it-works');cdp=context.new_cdp_session(pg);cdp.send('Emulation.setCPUThrottlingRate',{'rate':4});timing=pg.evaluate('()=>new Promise(resolve=>{const a=[];let last=performance.now();function f(t){a.push(t-last);last=t;if(a.length<120)requestAnimationFrame(f);else resolve({mean:a.reduce((n,x)=>n+x,0)/a.length,max:Math.max(...a)})}requestAnimationFrame(f)})');R['cpu4x']=timing;cdp.send('Emulation.setCPUThrottlingRate',{'rate':1})
 route('/legal');pg.locator('.legal-copy input[type=checkbox]').check();route('/about');check('notice_dismissed',pg.locator('.footer-notice').is_hidden())
 R['errors']=pg.evaluate('PB.errors');context.close()
 reduced=b.new_context(viewport={'width':390,'height':844},reduced_motion='reduce');rp=reduced.new_page();rp.goto(url+'#/contract',wait_until='networkidle');rp.wait_for_function('PB.ready&&PB.siteReady');rp.click('#start-button');rp.click('[data-next]');rp.check('#consent');rp.click('[data-submit]');rp.wait_for_function('PB.store.get().contract.confirmed');R['reduced']=rp.evaluate('({reduced:PB.reduced,confirmed:PB.store.get().contract.confirmed,errors:PB.errors,overflow:document.documentElement.scrollWidth>innerWidth})');reduced.close();b.close()
 R['file_bytes']=(root/'planbound-site.html').stat().st_size;R['sha256']=hashlib.sha256((root/'planbound-site.html').read_bytes()).hexdigest();(out/'verification.json').write_text(json.dumps(R,indent=2));print(json.dumps({'checks':len(R['checks']),'failed':[k for k,v in R['checks'].items() if not v['pass']],'console':R['console'],'errors':R['errors'],'cpu4x':R['cpu4x'],'bytes':R['file_bytes']},indent=2),flush=True)
