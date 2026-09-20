"""Record each animated scene in scenes.html to a webm (Playwright). Usage: python render_scenes.py"""
import json, sys, urllib.parse, shutil
from pathlib import Path
from playwright.sync_api import sync_playwright
H=Path(__file__).resolve().parent; A=H.parent/'assets'
M=json.load(open(A/'marks.json')) if (A/'marks.json').exists() else {}
verd=[v.split(' :: ',1)[1] for v in M.get('verdicts',[]) if v.startswith('deny')][:1]
D={'2':20,'3':12,'5':22,'6':28,'7a':6,'7b':7}
with sync_playwright() as p:
    b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
    for s,d in D.items():
        ctx=b.new_context(viewport={'width':1920,'height':1080},record_video_dir=str(A/'raw'),record_video_size={'width':1920,'height':1080})
        pg=ctx.new_page(); pg.goto((H/'scenes.html').as_uri()+'?s=%s&v=%s'%(s,urllib.parse.quote(json.dumps(verd))))
        pg.wait_for_timeout(int(d*1000)+400)
        if s in('2','5','6'): pg.screenshot(path=str(A/('architecture' if s=='5' else 'aws' if s=='6' else 'product')/f'scene{s}.png'))
        v=pg.video.path(); ctx.close(); shutil.copy(v,A/f'raw/scene{s}.webm'); print('scene',s)
    b.close()
