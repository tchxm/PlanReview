from playwright.sync_api import sync_playwright
from pathlib import Path
import json
root=Path(__file__).resolve().parents[1];out=root/'site-evidence';out.mkdir(exist_ok=True)
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 pg=b.new_page(viewport={'width':1440,'height':900});logs=[]
 pg.on('pageerror',lambda e:logs.append(str(e)))
 pg.on('console',lambda m:logs.append(m.type+': '+m.text) if m.type in ['error','warning'] else None)
 pg.goto((root/'planbound-site.html').as_uri()+'#/contract',wait_until='networkidle');pg.wait_for_timeout(1000)
 print('INITIAL',pg.evaluate('({ready:PB.ready,site:PB.siteReady,errors:PB.errors})'),logs,flush=True)
 pg.click('#start-button');pg.click('[data-next]');pg.check('#consent');pg.click('[data-submit]');pg.wait_for_timeout(500)
 print('CONTRACT',pg.evaluate('PB.store.get().contract'),flush=True)
 pg.evaluate('PB.router.go("/plan-review")');pg.wait_for_timeout(1500)
 print('REVIEW',pg.evaluate('({verdicts:PB.store.get().verdicts,life:PB.lifecycle.stats(),errors:PB.errors})'),logs,flush=True)
 pg.screenshot(path=str(out/'review-initial.png'))
 pg.locator('[data-action=approve]').click();pg.select_option('#sample-plan','sample-b');pg.click('[data-apply]');pg.wait_for_timeout(400)
 print('APPLY',pg.evaluate('({gate:PB.store.get().gateOpen,applied:PB.store.get().appliedScope,records:PB.store.get().records.length})'),flush=True)
 for path in ['/','/how-it-works','/contract','/plan-review','/evidence','/about','/legal','/missing']:
  pg.evaluate('(p)=>PB.router.go(p)',path);pg.wait_for_timeout(1300)
  print('ROUTE',path,pg.evaluate('({route:PB.router.current,errors:PB.errors,overflow:document.documentElement.scrollWidth>innerWidth})'),flush=True)
  pg.screenshot(path=str(out/((path.strip('/') or 'home')+'.png')))
 print('LOGS',logs,flush=True);b.close()
