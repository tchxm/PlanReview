from playwright.sync_api import sync_playwright
from pathlib import Path
import json
root=Path(__file__).resolve().parents[1];R={}
with sync_playwright() as p:
 b=p.chromium.launch(executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',headless=True)
 page=b.new_page(viewport={'width':390,'height':844},reduced_motion='reduce')
 page.goto((root/'planbound-site.html').as_uri()+'#/contract',wait_until='networkidle');page.wait_for_function('PB.ready&&PB.siteReady');page.keyboard.press('Escape')
 def tab_to(selector):
  for i in range(200):
   if page.evaluate('(s)=>document.activeElement.matches(s)',selector):return
   page.keyboard.press('Tab')
  raise AssertionError('Could not reach '+selector)
 def go(key):
  # A focused input intentionally suppresses shortcuts. Tab out first.
  while page.evaluate('/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)'):page.keyboard.press('Tab')
  page.keyboard.press('g');page.keyboard.press(key);page.wait_for_function('!PB.router.busy');page.wait_for_timeout(100)
 tab_to('[data-next]');page.keyboard.press('Enter');tab_to('#consent');page.keyboard.press('Space');tab_to('[data-submit]');page.keyboard.press('Enter');page.wait_for_function('PB.store.get().contract.confirmed');R['keyboard_confirm']=True
 go('p');page.wait_for_function('PB.router.current==="/plan-review"');page.keyboard.press('j');page.keyboard.press('j');page.keyboard.press('a');R['keyboard_review_approve']=page.evaluate('PB.engine.resolution("chg_2")==="approved"')
 tab_to('#sample-plan');page.keyboard.press('ArrowDown');page.wait_for_function('PB.store.get().planId==="sample-b"');tab_to('[data-apply]');page.keyboard.press('Enter');R['keyboard_mobile_apply']=page.evaluate('PB.store.get().records.some(r=>r.event==="applied")')
 go('e');tab_to('[data-record-id]');page.keyboard.press('Enter');R['keyboard_evidence_detail']=page.locator('.evidence-detail').count()==1
 go('a');tab_to('.faq summary');page.keyboard.press('Enter');R['keyboard_faq']=page.locator('.faq details').first.evaluate('(e)=>e.open')
 tab_to('[aria-label="Open site menu"]');page.keyboard.press('Enter');tab_to('.menu-links a[href="#/legal"]');page.keyboard.press('Enter');page.wait_for_function('PB.router.current==="/legal"&&!PB.router.busy');tab_to('.legal-copy input');page.keyboard.press('Space');R['keyboard_legal_notice']=page.evaluate('PB.store.get().noticeDismissed')
 tab_to('[aria-label="Open site menu"]');page.keyboard.press('Enter');tab_to('.menu-links a[href="#/how-it-works"]');page.keyboard.press('Enter');page.wait_for_function('PB.router.current==="/how-it-works"&&!PB.router.busy');tab_to('.how-steps button:nth-child(2)');page.keyboard.press('Enter');R['keyboard_story_step']=page.locator('.how-copy h2').inner_text()=='Every change is visible.'
 go('h');page.wait_for_function('PB.router.current==="/"&&!PB.router.busy');R['keyboard_home_focus']=page.evaluate('document.activeElement.id==="view"');R['errors']=page.evaluate('PB.errors');b.close()
 (root/'site-evidence/keyboard.json').write_text(json.dumps(R,indent=2));print(json.dumps(R,indent=2))
