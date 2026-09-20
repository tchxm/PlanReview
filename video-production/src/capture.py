"""Capture real footage from the running site (python run_site.py). Usage: python capture.py"""
import json, time, shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
HERE=Path(__file__).resolve().parent.parent; A=HERE/'assets'
CHROME=r'C:\Program Files\Google\Chrome\Application\chrome.exe'
M={}
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=CHROME,headless=True,args=['--use-gl=swiftshader','--enable-unsafe-swiftshader'])
    ctx=b.new_context(viewport={'width':1920,'height':1080},record_video_dir=str(HERE/'assets/raw'),record_video_size={'width':1920,'height':1080})
    t0=time.time(); mark=lambda k:M.__setitem__(k,round(time.time()-t0,2))
    pg=ctx.new_page(); pg.goto('http://127.0.0.1:8000/',wait_until='domcontentloaded')
    pg.wait_for_function('window.PB&&PB.ready&&PB.siteReady',timeout=90000); pg.wait_for_timeout(2500); mark('gate')
    for i in range(14): pg.mouse.move(700+i*45,380+(i%5)*40,steps=8); pg.wait_for_timeout(250)
    pg.screenshot(path=str(A/'robot/gate-robot.png')); mark('gate_end')
    pg.keyboard.press('Escape'); pg.wait_for_function('PB.phase==="site"',timeout=30000); mark('site'); pg.wait_for_timeout(2500)
    pg.screenshot(path=str(A/'globe/home.png'))
    for i in range(16):
        pg.mouse.wheel(0,260); pg.wait_for_timeout(650)
        if i in (5,11): pg.screenshot(path=str(A/f'globe/scroll-{i}.png'))
    mark('scrolled'); pg.wait_for_timeout(1200)
    pg.evaluate('PB.tour.start()'); steps=[]
    for i in range(12):
        pg.wait_for_function('PB.tour.active===false || !Array.from(document.querySelectorAll(".tour-actions button")).find(b=>b.textContent==="Next"||b.textContent==="Finish").disabled',timeout=300000)
        if not pg.evaluate('PB.tour.active'): break
        title=pg.evaluate('document.querySelector(".tour-card h2").innerText'); pg.wait_for_timeout(700)
        steps.append({'t':round(time.time()-t0,2),'title':title}); pg.screenshot(path=str(A/f'product/step{i}.png'))
        pg.wait_for_timeout(3800)
        pg.evaluate('Array.from(document.querySelectorAll(".tour-actions button")).find(b=>b.textContent==="Next"||b.textContent==="Finish").click()')
    M['steps']=steps
    M['verdicts']=pg.evaluate('[...document.querySelectorAll(".pipe-verdict")].map(e=>e.className.replace("pipe-verdict v-","")+" "+e.dataset.address+" :: "+e.querySelector(".rule-reason").innerText)')
    pg.evaluate('location.hash="#/"'); pg.wait_for_timeout(1500); pg.evaluate('window.scrollTo(0,0)'); mark('home_again'); pg.wait_for_timeout(6000); mark('end')
    pg.screenshot(path=str(A/'robot/home-end.png'))
    v=pg.video.path(); ctx.close(); b.close()
    shutil.copy(v,A/'raw/main.webm')
json.dump(M,open(HERE/'assets/marks.json','w'),indent=1); print(json.dumps(M,indent=1))
