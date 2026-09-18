"""Assemble the requested standalone HTML by extending the supplied editorial base."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
BASE = Path(r'C:\Users\kario\Downloads\planbound_globe_scroll_editorial.html')
html = BASE.read_text(encoding='utf-8')
html = html.replace('</style>', '\n' + (ROOT/'extension.css').read_text(encoding='utf-8') + '\n</style>',1)
html = html.replace('<canvas id="globe-canvas">','<canvas id="globe-canvas" aria-hidden="true">')
html = html.replace('From change<br>to <em>confidence.</em>', '<span class="word-wrap"><span class="word">From</span></span> <span class="word-wrap"><span class="word">change</span></span><br><span class="word-wrap"><span class="word">to</span></span> <em class="word-wrap"><span class="word">confidence.</span></em>')
html = html.replace('</div></section>\n\n<section class="paths', '''<div class="tree-hud"><div class="caption" id="station-number">ROOT / 00</div><h2 id="station-title">Intent takes shape.</h2><p>ONE AUTHORIZED PATH THROUGH POSSIBILITY</p></div>
<svg class="leaders" aria-hidden="true"></svg><nav class="station-rail" aria-label="Feature stations"></nav><span class="sr-only" aria-live="polite" id="station-live"></span>
</div></section>
<ol id="feature-mirror" class="sr-only feature-mirror"></ol>
<section id="unit" class="studio" data-cursor="LOOK"><div class="studio-sticky"><div class="studio-head"><span class="caption">PB-01 / BOUNDARY REVIEWER</span><span class="caption">STATUS: <span id="robot-status">BOOT</span></span></div><div id="studio-word" class="studio-word" aria-hidden="true">Intent</div><canvas id="robot-canvas" aria-hidden="true"></canvas><div class="studio-bottom"><p>MOVE TO MEET THE REVIEWER.<br><button id="studio-ack" class="studio-ack">CLICK TO ACKNOWLEDGE.</button></p><p><b>A human stays in the loop.</b><br>Even when the agent moves fast.</p></div></div></section>
<section class="paths''',1)
overlay='''<div id="boot" class="boot"><span class="boot-brand caption">PLANBOUND / BOUNDARY ENGINE / v0.9</span><h2 class="boot-word">PLANBOUND</h2><div id="boot-log" class="boot-log" role="status" aria-live="polite"></div><div class="boot-progress"><i></i></div><button id="start-button" class="start-button" disabled>INITIALIZING</button><button id="boot-skip" class="boot-skip">Skip ↵ / Esc</button></div>
<button id="sound-toggle" class="sound" aria-pressed="false">SOUND OFF</button>
<div id="curDot" class="cur-dot" aria-hidden="true"></div><div id="curRing" class="cur-ring" aria-hidden="true"></div><div id="curLabel" class="cur-label" aria-hidden="true"></div>
<dialog id="feature-detail" class="detail"><button id="detail-close">← Return to tree</button><h2 id="detail-title"></h2><p class="demo-caption">INTERACTIVE DESIGN DEMONSTRATION · NOT A LIVE PLAN</p><pre id="detail-json"></pre></dialog>
'''
html=html.replace('</head><body>','</head><body>\n'+overlay)
html=html.replace('<footer>', '<div class="footer-word" aria-hidden="true">PLANBOUND</div><footer>')
html=html.replace('<div class="review-head">','<p class="demo-caption">ILLUSTRATIVE PLAN · INTERACTIVE DESIGN PREVIEW</p><div class="review-head">')
html=html.replace('Open security group allows unrestricted access. Consider restricting to specific IP ranges.','This restriction is outside the confirmed scope and needs human resolution.')
# Correct the supplied illustrative diff direction: the DENY must describe a weakening.
html=html.replace('- acl = "public-read"','- acl = "private"').replace('+ acl = "private"\n+ block_public_access = true','+ acl = "public-read"\n+ block_public_access = false')
html=html.replace('class="badge deny"','class="badge deny" data-verdict="deny" tabindex="0"').replace('class="badge review-b"','class="badge review-b" data-verdict="review" tabindex="0"').replace('class="badge allow"','class="badge allow" data-verdict="allow" tabindex="0"')
html=html.replace('class="stat"><b data-count="1800"','class="stat"><b data-count="1800"')
# Replace the base immediate counters/review script, retaining its reveal behaviour in PB.core.
first=html.index('<script>');first_end=html.index('</script>',first)+len('</script>')
def module(name):
    return '<script>\n'+(ROOT/(name+'.js')).read_text(encoding='utf-8')+'\n</script>\n'
html=html[:first]+module('core')+module('boot')+html[first_end:]
# Preserve the original globe geometry source verbatim, changing only startup and loop hooks.
last=html.rindex('<script>');end=html.index('</script>',last)
globe=html[last+len('<script>'):end]
globe=globe[:globe.index(' var reduced=')]+(ROOT/'globe-end.js').read_text(encoding='utf-8')
globe=globe.replace(" if(!canvas||typeof THREE==='undefined')return;", " if(!canvas||typeof THREE==='undefined'){PB.fail('Three.js unavailable — readable fallback');return;}")
globe=globe.replace(" var renderer=new THREE.WebGLRenderer({canvas:canvas,alpha:true,antialias:true,powerPreference:'high-performance'});", " var renderer;try{renderer=new THREE.WebGLRenderer({canvas:canvas,alpha:true,antialias:true,powerPreference:'high-performance'});}catch(error){window.PB.fail('WebGL unavailable — readable fallback');return;}")
globe=globe.replace("{PB.fail(","{window.PB.fail(")
globe=globe.replace("lg.setDrawRange(0,Math.floor(totalLineVerts*.18));", "lg.setDrawRange(0,Math.floor(totalLineVerts*.18/2)*2);")
html=html[:last]+'<script>\n'+globe+'\n</script>\n'+''.join(module(name) for name in ['tree','robot','audio','cursor','perf'])+'\n</body></html>'
destination=ROOT.parent/'planbound.html'
destination.write_text(html,encoding='utf-8')
print(f'{destination}: {len(html):,} characters')
