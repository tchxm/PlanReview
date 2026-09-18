(function(){
const PB=window.PB,dot=document.getElementById('curDot'),ring=document.getElementById('curRing'),label=document.getElementById('curLabel');if(PB.touch||PB.reduced)return;
const x={x:innerWidth/2,v:0},y={x:innerHeight/2,v:0};let current=null,magnet=null,box=null,mx={x:0,v:0},my={x:0,v:0};
document.querySelectorAll('.btn,.navcta,.start-button').forEach(el=>el.classList.add('magnetic'));
document.addEventListener('pointerover',e=>{current=e.target.closest('[data-cursor]');ring.classList.toggle('big',!!current);label.textContent=current?current.dataset.cursor:'';const next=e.target.closest('.magnetic');if(next!==magnet){if(magnet)magnet.style.transform='';magnet=next;box=magnet?magnet.getBoundingClientRect():null}});
PB.cursor={label(text){label.textContent=text}};
PB.frame((dt)=>{document.documentElement.classList.toggle('cursor-present',PB.pointer.inside);PB.spring(x,PB.pointer.x,14,.8,dt);PB.spring(y,PB.pointer.y,14,.8,dt);dot.style.transform='translate3d('+(PB.pointer.x-2.5)+'px,'+(PB.pointer.y-2.5)+'px,0)';ring.style.transform='translate3d('+x.x+'px,'+y.x+'px,0) translate(-50%,-50%)';label.style.transform='translate3d('+x.x+'px,'+(y.x+14)+'px,0) translateX(-50%)';if(magnet&&box){PB.spring(mx,PB.clamp((PB.pointer.x-box.left-box.width/2)*.15,-8,8),12,1,dt);PB.spring(my,PB.clamp((PB.pointer.y-box.top-box.height/2)*.15,-8,8),12,1,dt);magnet.style.transform='translate('+mx.x+'px,'+my.x+'px)'}});
})();
