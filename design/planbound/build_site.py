"""Wrap the v1 artifact with route, store and lifecycle extensions."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parent
html=(ROOT.parent/'planbound.html').read_text(encoding='utf-8')
def script(name): return '<script>\n'+(ROOT/(name+'.js')).read_text(encoding='utf-8')+'\n</script>\n'
# Preserve a persistent Home DOM; every other route mounts in its own disposable host.
begin=html.index('<section class="hero"')
end=html.index('<div class="footer-word"',begin)
html=html[:begin]+'<main id="view" tabindex="-1"><div id="home-view">'+html[begin:end]+'</div><div id="route-view" hidden></div></main>\n'+html[end:]
html=html.replace('</style>', '\n'+(ROOT/'site.css').read_text(encoding='utf-8')+'\n</style>',1)
html=html.replace('INTERACTIVE DESIGN DEMONSTRATION · NOT A LIVE PLAN','SAMPLE DATA · BROWSER SIMULATION · NOT A LIVE PLAN').replace('ILLUSTRATIVE PLAN · INTERACTIVE DESIGN PREVIEW','SAMPLE DATA · BROWSER SIMULATION')
# Definition-only factories keep the original algorithms intact and allow lazy creation.
scripts=list(re.finditer(r'<script>(.*?)</script>',html,re.S))
for match in reversed(scripts):
    code=match.group(1)
    if '// KEEP THE ORIGINAL GLOBE' in code:
        code=code.replace("addEventListener('resize',resize,{passive:true});",'')
        code='window.PB.initHero=function(){\n'+code+'\n};'
    elif 'const g=PB.globe,random=PB.rng' in code:
        code=code.replace('const uniforms={uProgress:', 'const uniforms={uLeafColors:{value:[new THREE.Color(0x72e6a1),new THREE.Color(0xf1c34f),new THREE.Color(0xff6f72)]},uProgress:')
        code=code.replace("const fragment='uniform float uTime,uHover;", "const fragment='uniform vec3 uLeafColors[3];uniform float uTime,uHover;")
        code=code.replace('col=vec3(.447,.902,.631)', 'col=uLeafColors[0]').replace('col=vec3(.945,.765,.31)', 'col=uLeafColors[1]').replace('col=vec3(1.,.435,.447)', 'col=uLeafColors[2]')
        code=code.replace('function finish(){','function finish(){\n PB.activeScope=PB.lifecycle.heroScope;')
        code=code.replace("document.getElementById('globe-canvas').addEventListener('click',", "PB.listen(document.getElementById('globe-canvas'),'click',")
        code=code.replace('PB.tree={nodes,','PB.tree={gate,gateMat,lock,ringGeo,uniforms,denyRing,nodes,')
        code=code.replace("g.renderer.compile(g.scene,g.camera);PB.boot.complete('shaders','Hero and tree shader compilation requested');", "g.renderer.compile(g.scene,g.camera);PB.boot.complete('shaders','Hero and tree shader compilation requested');PB.activeScope=null;PB.bus.emit('tree-ready',PB.tree);")
        code='window.PB.initTree=function(){\n'+code+'\n};'
    elif "const canvas=document.getElementById('robot-canvas')" in code:
        code=code.replace('const hx=(headCentre.x*.5+.5)*PB.width,hy=(-headCentre.y*.5+.5)*PB.height,dx=(PB.pointer.x-hx)/PB.height,dy=(PB.pointer.y-hy)/PB.height', 'const bounds=PB.robot.bounds,hx=(bounds?.left||0)+(headCentre.x*.5+.5)*(bounds?.width||PB.width),hy=(bounds?.top||0)+(-headCentre.y*.5+.5)*(bounds?.height||PB.height),dx=(PB.pointer.x-hx)/(bounds?.height||PB.height),dy=(PB.pointer.y-hy)/(bounds?.height||PB.height)')
        code=code.replace('function resize(){renderer.setSize(PB.width,PB.height,false);camera.aspect=PB.width/PB.height;camera.position.z=PB.width<700?5.4:4.1;camera.updateProjectionMatrix()}', "function resize(){const slot=PB.robot.slot;const w=slot?slot.clientWidth:PB.width,h=slot?slot.clientHeight:PB.height;renderer.setSize(Math.max(1,w),Math.max(1,h),false);camera.aspect=w/Math.max(1,h);camera.position.z=slot?.dataset.companion?4.7:PB.width<700?5.4:4.1;camera.updateProjectionMatrix()}PB.robot.resize=resize;")
        code=code.replace("if(verdictUntil>t){glyph=", "if(PB.lifecycle.route==='/plan-review'&&verdictUntil<=t){glyph=PB.store.get().gateOpen?'GATE: OPEN':'GATE: CLOSED';context.fillStyle=PB.store.get().gateOpen?'#72e6a1':'#ff6f72'}if(verdictUntil>t){glyph=")
        code=code.replace("if(t-lastTex>=1/15&&(!PB.reduced||lastTex<0))", "if(t-lastTex>=1/15&&(!PB.reduced||lastTex<0||PB.robot.refreshScreen))").replace('screenContent(state,t,dx,dy);lastTex=t','screenContent(state,t,dx,dy);lastTex=t;PB.robot.refreshScreen=false')
        code=code.replace("PB.bus.on('verdict',v=>{verdict=v;", "PB.bus.on('gate',()=>{PB.robot.refreshScreen=true});PB.bus.on('route',()=>{PB.robot.refreshScreen=true});PB.bus.on('verdict',v=>{PB.robot.refreshScreen=true;verdict=v;")
        code=code.replace('screenContent(\'BOOT\',0,0,0);',"PB.robot.acknowledge=acknowledge;screenContent('BOOT',0,0,0);")
        code='window.PB.initRobot=function(){\n'+code+'\n};'
    elif 'PB.perf={average:' in code:
        code=code.replace('if(PB.globe){PB.globe.renderer', 'if(PB.globe&&!PB.globe.disposed){PB.globe.renderer')
    elif 'PB.audio={start()' in code:
        code=code.replace("!/INPUT|TEXTAREA/.test(e.target.tagName)", "!e.target.isContentEditable&&!/INPUT|TEXTAREA|SELECT/.test(e.target.tagName)")
    html=html[:match.start()]+'<script>'+code+'</script>'+html[match.end():]
# Support must precede factory definitions. Original core/boot scripts run first.
offset=html.index('<script src=')
html=html[:offset]+script('site-support')+html[offset:]
html=html.replace('</body>',script('site-engine')+script('site-ui')+script('site-views')+script('site-app')+'</body>')
html=html.replace('INTERACTIVE DESIGN DEMONSTRATION','SAMPLE DATA')
out=ROOT.parent/'planbound-site.html';out.write_text(html,encoding='utf-8')
assert out.stat().st_size<400_000
print(f'{out}: {out.stat().st_size:,} bytes')
