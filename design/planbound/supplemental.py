from pathlib import Path
from playwright.sync_api import sync_playwright
import json
root=Path(__file__).resolve().parents[1];out=root/'evidence';results={};logs=[]
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 pg=b.new_page(viewport={'width':1440,'height':900});pg.on('pageerror',lambda e:logs.append(str(e)))
 pg.goto((root/'planbound.html').as_uri(),wait_until='networkidle');pg.wait_for_function('PB.ready');pg.keyboard.press('Escape');pg.wait_for_timeout(800);results['escape']=pg.evaluate('PB.started')
 pg.evaluate('PB.go(.95)');pg.wait_for_timeout(2200);pg.screenshot(path=str(out/'canopy-closed.png'))
 pg.evaluate('PB.globe.renderer.info.autoReset=false;PB.frames.unshift(()=>PB.globe.renderer.info.reset());PB.frames.push(()=>{PB.measuredCalls=PB.globe.renderer.info.render.calls})');pg.wait_for_timeout(200)
 results['heroCallsIncludingBloom']=pg.evaluate('PB.measuredCalls')
 pg.evaluate('PB.go(.605)');pg.wait_for_timeout(2200);pg.locator('.node.active [data-verdict="deny"]').hover()
 pg.locator('#unit').scroll_into_view_if_needed();pg.wait_for_timeout(700);pg.screenshot(path=str(out/'unit-deny.png'))
 for verdict in ['allow','review']:
  pg.evaluate('PB.go(.605)');pg.wait_for_timeout(2000);pg.locator('.node.active [data-verdict="'+verdict+'"]').hover();pg.locator('#unit').scroll_into_view_if_needed();pg.wait_for_timeout(700);pg.screenshot(path=str(out/('unit-'+verdict+'.png')))
 pg.mouse.move(950,380,steps=30);pg.wait_for_timeout(700);results['track']=pg.evaluate('({state:PB.robot.state,rotation:PB.robot.headPivot.rotation.toArray()})')
 cdp=pg.context.new_cdp_session(pg);cdp.send('Emulation.setCPUThrottlingRate',{'rate':4});pg.wait_for_timeout(14000);results['robotCpu4x']=pg.evaluate('({average:PB.perf.average,quality:PB.quality,tiers:PB.perf.tiers})');cdp.send('Emulation.setCPUThrottlingRate',{'rate':1})
 # Controlled slow-frame input verifies tier logic separately from natural browser performance.
 results['controlledSlowSampleTiers']=pg.evaluate('(()=>{for(let i=0;i<700;i++)PB.perf.sample(40,.04);return PB.perf.tiers})()')
 pg.wait_for_timeout(100);results['errors']=logs;pg.close()
 rm=b.new_page(viewport={'width':1440,'height':900},reduced_motion='reduce');rm.goto((root/'planbound.html').as_uri(),wait_until='networkidle');rm.wait_for_function('PB.ready');rm.click('#start-button');rm.wait_for_timeout(500);before=rm.evaluate('PB.globe.camera.position.toArray()');rm.mouse.move(1300,800);rm.wait_for_timeout(500);results['reducedCameraStatic']=before==rm.evaluate('PB.globe.camera.position.toArray()');rm.close();b.close()
 (out/'supplemental.json').write_text(json.dumps(results,indent=2));print(json.dumps(results,indent=2))
