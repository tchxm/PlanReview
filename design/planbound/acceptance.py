from playwright.sync_api import sync_playwright
from pathlib import Path
import json,time,hashlib
root=Path(__file__).resolve().parents[1];out=root/'evidence'
result={}; logs=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 page=b.new_page(viewport={'width':1440,'height':900})
 page.on('console',lambda m:logs.append({'type':m.type,'text':m.text}))
 page.on('pageerror',lambda e:logs.append({'type':'pageerror','text':str(e)}))
 url=(root/'planbound.html').as_uri()
 def ready(pg):
  pg.goto(url,wait_until='networkidle');pg.wait_for_function('window.PB?.ready');pg.click('#start-button');pg.wait_for_timeout(800)
 ready(page)
 result['boot']=page.evaluate('PB.boot.steps')
 result['continuity']=page.evaluate('PB.checkContinuity()')
 signature=page.evaluate('JSON.stringify(PB.tree.nodes.map(n=>n.p.toArray()))')
 result['tree']={'segments':page.evaluate('PB.tree.segments'),'sha256':hashlib.sha256(signature.encode()).hexdigest()}
 page.evaluate('PB.go(.6)');page.wait_for_timeout(2200)
 page.locator('.station-rail button').nth(2).click();page.wait_for_timeout(2200)
 result['station']=page.evaluate('({text:document.querySelector("#station-number").textContent,active:document.querySelector(".node.active h3").textContent,p:PB.P})')
 page.screenshot(path=str(out/'verdict-fork.png'))
 page.locator('.node.active button').click();result['dialog']=page.locator('#feature-detail').evaluate('(e)=>e.open');page.click('#detail-close')
 page.locator('#unit').scroll_into_view_if_needed();page.wait_for_timeout(1300)
 page.mouse.move(1100,300,steps=15);page.wait_for_timeout(200)
 result['robotTrack']=page.evaluate('({state:PB.robot.state,yaw:PB.robot.headPivot.rotation.y,cables:PB.robot.cables.length,triangles:PB.robot.renderer.info.render.triangles,calls:PB.robot.renderer.info.render.calls,cursor:document.querySelector(".cur-label").textContent})')
 page.mouse.move(200,650);page.wait_for_timeout(80)
 result['robotFlick']=page.evaluate('PB.robot.state')
 page.mouse.click(720,450);page.wait_for_timeout(80)
 result['robotClick']=page.evaluate('PB.robot.state')
 page.wait_for_timeout(3200);result['robotIdle']=page.evaluate('PB.robot.state')
 page.screenshot(path=str(out/'unit-final.png'))
 def memory():return page.evaluate('({hero:{...PB.globe.renderer.info.memory},robot:{...PB.robot.renderer.info.memory}})')
 page.evaluate('window.scrollTo({top:PB.travel*.95,behavior:"instant"})');page.wait_for_timeout(2000)
 result['memoryBefore']=memory();start=time.monotonic();samples=[]
 for i in range(30):
  page.evaluate('(i)=>window.scrollTo({top:i%2?document.querySelector("#unit").offsetTop:PB.travel*(.4+(i%6)*.08),behavior:"instant"})',i)
  page.wait_for_timeout(2000)
  samples.append(page.evaluate('PB.perf.average'))
 result['scrollSeconds']=time.monotonic()-start;result['memoryAfter']=memory();result['frameMsSamples']=samples
 cdp=page.context.new_cdp_session(page);cdp.send('Emulation.setCPUThrottlingRate',{'rate':4})
 page.evaluate('window.scrollTo({top:PB.travel*.58,behavior:"instant"})');page.wait_for_timeout(12000)
 result['cpu4x']=page.evaluate('({average:PB.perf.average,tiers:PB.perf.tiers,quality:PB.quality})');cdp.send('Emulation.setCPUThrottlingRate',{'rate':1})
 result['hardware']=page.evaluate('(()=>{const gl=PB.globe.renderer.getContext(),e=gl.getExtension("WEBGL_debug_renderer_info");return e?gl.getParameter(e.UNMASKED_RENDERER_WEBGL):gl.getParameter(gl.RENDERER)})()')
 result['errors']=page.evaluate('PB.errors');result['console']=logs
 ready(page);signature2=page.evaluate('JSON.stringify(PB.tree.nodes.map(n=>n.p.toArray()))');result['deterministic']=signature==signature2;page.close()
 reduced=b.new_page(viewport={'width':1440,'height':900},reduced_motion='reduce');ready(reduced)
 result['reduced']=reduced.evaluate('({reduced:PB.reduced,items:document.querySelectorAll(".feature-mirror li").length,overflow:document.documentElement.scrollWidth>innerWidth,errors:PB.errors})');reduced.locator('.feature-mirror').scroll_into_view_if_needed();reduced.screenshot(path=str(out/'reduced.png'));reduced.close()
 mobile=b.new_page(viewport={'width':390,'height':844},is_mobile=True,has_touch=True);ready(mobile);mobile.evaluate('window.scrollTo({top:PB.travel*.6,behavior:"instant"})');mobile.wait_for_timeout(2200);mobile.screenshot(path=str(out/'mobile.png'));result['mobile']=mobile.evaluate('({overflow:document.documentElement.scrollWidth>innerWidth,errors:PB.errors})');mobile.close()
 fallback=b.new_page();fallback.add_init_script('const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return /webgl/.test(type)?null:original.call(this,type,...args)}');ready(fallback);result['fallback']=fallback.evaluate('({webgl:PB.webgl,ready:PB.ready,started:PB.started,errors:PB.errors})');fallback.screenshot(path=str(out/'fallback.png'))
 (out/'verification.json').write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));b.close()
