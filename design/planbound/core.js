(function(){
'use strict';
const PB=window.PB={started:false,ready:false,version:'0.9',frames:[],errors:[],P:0,targetProgress:0,width:innerWidth,height:innerHeight,travel:1,heroTop:0,scroll:scrollY,previousScroll:scrollY,scrollVel:0,quality:0,webgl:true};
PB.reduced=matchMedia('(prefers-reduced-motion: reduce)').matches;
PB.touch=matchMedia('(hover:none)').matches;
PB.clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
PB.smooth=x=>{x=PB.clamp(x);return x*x*(3-2*x)};
PB.mix=(a,b,t)=>a+(b-a)*t;
PB.spring=function(s,target,omega,zeta,dt){const f=1+2*dt*zeta*omega,oo=omega*omega,hoo=dt*oo,hhoo=dt*hoo,inv=1/(f+hhoo),nx=(f*s.x+dt*s.v+hhoo*target)*inv,nv=(s.v+hoo*(target-s.x))*inv;s.x=nx;s.v=nv};
PB.rng=function(seed){return function(){let t=seed+=0x6D2B79F5;t=Math.imul(t^t>>>15,t|1);t^=t+Math.imul(t^t>>>7,t|61);return ((t^t>>>14)>>>0)/4294967296}};
const listeners={};PB.bus={on(name,fn){(listeners[name]||(listeners[name]=[])).push(fn)},emit(name,data){const ls=listeners[name];if(ls)for(let i=0;i<ls.length;i++)ls[i](data)}};
PB.frame=fn=>PB.frames.push(fn);
PB.pointer={x:innerWidth/2,y:innerHeight/2,previousX:innerWidth/2,previousY:innerHeight/2,time:0,speed:0,inside:false,ndcX:0,ndcY:0};
addEventListener('pointermove',e=>{PB.pointer.x=e.clientX;PB.pointer.y=e.clientY;PB.pointer.time=performance.now();PB.pointer.inside=true},{passive:true});
document.documentElement.addEventListener('pointerleave',()=>{PB.pointer.inside=false});
addEventListener('scroll',()=>{PB.scroll=scrollY;PB.targetProgress=PB.clamp((PB.scroll-PB.heroTop)/PB.travel)},{passive:true});
PB.layoutDirty=true;addEventListener('resize',()=>{PB.layoutDirty=true},{passive:true});
PB.observe=function(element,owner){owner.visible=false;new IntersectionObserver(es=>{owner.visible=es[0].isIntersecting;PB.wake()},{threshold:0}).observe(element)};
PB.go=function(p){window.scrollTo({top:PB.heroTop+PB.travel*p,behavior:PB.reduced?'instant':'smooth'})};
window.addEventListener('error',e=>PB.errors.push(e.message));
window.addEventListener('unhandledrejection',e=>PB.errors.push(String(e.reason)));
PB.FEATURES=[
{id:'intent',n:'01',title:'Intent contract',kicker:'HUMAN SETS THE BOUNDARY',body:'Confirm the authorization before an agent changes anything. Intent becomes the root of every decision.',metric:'confirmed: true'},
{id:'ingest',n:'02',title:'Plan ingest',kicker:'AGENT PROPOSES',body:'Turn the Terraform plan into discrete resource changes. Every create, update, delete and replacement stays inspectable.',metric:'3 changes / 1 saved plan'},
{id:'engine',n:'03',title:'Boundary engine',kicker:'EVERY CHANGE, ONE VERDICT',body:'Evaluate each change against the confirmed boundary. Three outcomes, each with a reason.',metric:'ALLOW · REVIEW · DENY'},
{id:'resolve',n:'04',title:'Human resolution',kicker:'JUDGMENT ONLY WHERE NEEDED',body:'Approve or reject uncovered changes. A denied change cannot be approved away.',metric:'1 review open'},
{id:'gate',n:'05',title:'Apply gate',kicker:'CLOSED BY DEFAULT',body:'The gate stays closed while any prohibited or unresolved change remains. A decision has consequences.',metric:'gate: closed'},
{id:'trace',n:'06',title:'Audit trace',kicker:'INTENT → PLAN → VERDICT',body:'Trace each decision back to the resource, operation and authorization it was checked against.',metric:'1 auditable chain'}];
PB.record={record_id:'PB-DEMO-001',source:'interactive design demonstration',contract:{confirmed:true,environment:'dev',max_changed_resources:3},changes:[{resource:'aws_iam_role.ec2_role',operation:'update',attribute:'policy',before:'AmazonS3FullAccess',after:'AmazonS3ReadOnlyAccess',verdict:'ALLOW'},{resource:'aws_security_group.web_sg',operation:'update',attribute:'cidr_blocks',before:['0.0.0.0/0'],after:['10.0.0.0/16'],verdict:'REVIEW'},{resource:'aws_s3_bucket.assets',operation:'update',attribute:'acl',before:'private',after:'public-read',verdict:'DENY'}],human_resolution:'pending',apply_gate:'closed'};
PB.renderJSON=function(el,data){const text=JSON.stringify(data,null,2);el.innerHTML=text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/("(?:[^"\\]|\\.)*"\s*:)|("(?:[^"\\]|\\.)*")|\b(true|false|null|\d+)\b/g,(m,k,s,n)=>'<span class="'+(k?'json-key':s?'json-string':'json-number')+'">'+m+'</span>')};
const detail=document.getElementById('feature-detail'),detailText=document.getElementById('detail-json');let returnFocus=null;
PB.open=function(index){returnFocus=document.activeElement;document.getElementById('detail-title').textContent=PB.FEATURES[index].title;PB.renderJSON(detailText,{station:PB.FEATURES[index].n,...PB.record});detail.showModal();PB.audio&&PB.audio.click()};
document.getElementById('detail-close').addEventListener('click',()=>{detail.close();if(returnFocus)returnFocus.focus()});
PB.renderJSON(document.querySelector('#data pre'),PB.record);
window.resolveReview=function(choice){PB.record.human_resolution=choice;document.getElementById('reviewReason').textContent='Demonstration review '+choice+'. This does not authorize the denied change.';document.getElementById('gateText').textContent='S3 public-access DENY remains. Apply gate: closed.';PB.renderJSON(document.querySelector('#data pre'),PB.record);PB.bus.emit('verdict',choice==='approved'?'allow':'deny')};
document.querySelectorAll('.mini:not([onclick])').forEach(el=>el.addEventListener('click',()=>PB.open(5)));
document.querySelectorAll('[data-verdict]').forEach(el=>{el.addEventListener('pointerenter',()=>PB.bus.emit('verdict',el.dataset.verdict));el.addEventListener('focus',()=>PB.bus.emit('verdict',el.dataset.verdict))});
const mirrored=document.getElementById('feature-mirror');PB.FEATURES.forEach(f=>{const li=document.createElement('li');li.innerHTML='<h2>'+f.title+'</h2><p>'+f.body+'</p>';mirrored.appendChild(li)});
const io=new IntersectionObserver(es=>es.forEach(e=>{if(e.isIntersecting)e.target.classList.add('visible')}),{threshold:.1});document.querySelectorAll('.reveal').forEach(el=>io.observe(el));
const counters=Array.from(document.querySelectorAll('[data-count]'));let countStart=0;
PB.bus.on('start',()=>{countStart=performance.now();document.querySelectorAll('.hero h1 .word').forEach((el,i)=>{el.style.transitionDelay=i*60+'ms';el.classList.add('entered')})});
let last=0,raf=0;PB.wake=function(){if(!raf&&!document.hidden)raf=requestAnimationFrame(tick)};
function tick(now){raf=0;if(document.hidden)return;const ms=last?now-last:16.67,dt=Math.min(.05,ms/1000);last=now;
 if(PB.layoutDirty){PB.width=innerWidth;PB.height=innerHeight;const hero=document.getElementById('hero');PB.heroTop=hero.getBoundingClientRect().top+scrollY;PB.travel=Math.max(1,hero.offsetHeight-innerHeight);PB.targetProgress=PB.clamp((scrollY-PB.heroTop)/PB.travel);PB.layoutDirty=false;PB.bus.emit('resize')}
 PB.P+=((PB.started?PB.targetProgress:0)-PB.P)*(1-Math.exp(-dt*6));
 const p=PB.pointer;p.speed=Math.hypot(p.x-p.previousX,p.y-p.previousY)/Math.max(dt,.001);p.previousX=p.x;p.previousY=p.y;p.ndcX=p.x/PB.width*2-1;p.ndcY=1-p.y/PB.height*2;
 PB.scrollVel+=(PB.clamp((PB.scroll-PB.previousScroll)/Math.max(dt,.001),-8000,8000)-PB.scrollVel)*(1-Math.exp(-dt*8));PB.previousScroll=PB.scroll;
 if(countStart){const f=PB.reduced?1:PB.clamp((now-countStart)/1200);for(let i=0;i<counters.length;i++)counters[i].textContent=Math.round(+counters[i].dataset.count*(1-Math.pow(1-f,3))).toLocaleString();if(f===1)countStart=0}
 for(let i=0;i<PB.frames.length;i++)PB.frames[i](dt,now/1000,ms);
 PB.wake();
}
document.addEventListener('visibilitychange',()=>{last=0;PB.wake()});PB.core=PB;PB.wake();
})();
