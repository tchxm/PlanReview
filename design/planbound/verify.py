from playwright.sync_api import sync_playwright
from pathlib import Path
import json
root=Path(__file__).resolve().parents[1]
out=root/'evidence';out.mkdir(exist_ok=True)
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True,args=['--allow-file-access-from-files'])
 page=browser.new_page(viewport={'width':1440,'height':900},device_scale_factor=1)
 logs=[];evidence={"poses":[]}
 page.on('console',lambda m:logs.append({'type':m.type,'text':m.text}))
 page.on('pageerror',lambda e:logs.append({'type':'pageerror','text':str(e)}))
 page.goto((root/'planbound.html').as_uri(),wait_until='networkidle')
 try:page.wait_for_function('window.PB && PB.ready',timeout=60000)
 except Exception as e:print(str(e))
 print(json.dumps(page.evaluate('({ready:window.PB?.ready,steps:window.PB?.boot.steps,errors:window.PB?.errors})')))
 print(json.dumps(logs))
 page.screenshot(path=str(out/'boot.png'))
 if page.evaluate('!!window.PB?.ready'):
  page.click('#start-button');page.wait_for_timeout(1800)
  for v in [0,.30,.50,.90]:
   page.evaluate('(v)=>window.scrollTo({top:PB.heroTop+PB.travel*v,behavior:"instant"})',v);page.wait_for_timeout(2200)
   page.screenshot(path=str(out/f'p-{v:.2f}.png'))
   evidence['poses'].append(page.evaluate('({p:PB.P,position:PB.globe.camera.position.toArray()})'))
  page.locator('#unit').scroll_into_view_if_needed();page.wait_for_timeout(2000)
  page.screenshot(path=str(out/'unit.png'))
  evidence['continuity']=page.evaluate('PB.checkContinuity()')
  print('STATE',page.evaluate('({errors:PB.errors,tree:Object.keys(PB.tree),robot:Object.keys(PB.robot),perf:PB.perf})'))
 (out/'screenshots.json').write_text(json.dumps(evidence,indent=2))
 (out/'console.json').write_text(json.dumps(logs,indent=2))
 browser.close()
