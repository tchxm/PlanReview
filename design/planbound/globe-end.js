 // Shared hooks extend the original geometry and preserve the descent equations.
 const PB=window.PB;
 PB.globe={scene,camera,root,lg,hubs,base,N,R,core,inner,renderer,composer,bloom,canvas,visible:true,totalLineVerts};
 PB.boot.complete('context','WebGL context created — local visual engine');
 PB.boot.complete('lattice','Built '+N.toLocaleString()+'-node lattice + '+H+' hubs');
 PB.boot.complete('links','Linked '+(totalLineVerts/2).toLocaleString()+' real edges');
 const copy=document.querySelector('.hero-copy'),stats=document.querySelector('.hero-stats'),depth=document.querySelector('.depth-label'),cue=document.querySelector('.scroll-cue');
 const ptr=new THREE.Vector2(),ray=new THREE.Raycaster(),sphere=new THREE.Sphere(root.position,R),hit=new THREE.Vector3(),localHit=new THREE.Vector3(),normal=new THREE.Vector3(),look=new THREE.Vector3();
 const springPos=new Float32Array(N),springVel=new Float32Array(N),highPos=new Float32Array(9),edgePos=new Float32Array(108),nearest=new Int32Array(3),oldNearest=new Int32Array(3).fill(-1),distances=new Float32Array(3);
 const highGeo=new THREE.BufferGeometry();highGeo.setAttribute('position',new THREE.BufferAttribute(highPos,3));
 const high=new THREE.Points(highGeo,new THREE.PointsMaterial({map:tex,size:.17,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending,color:0xffffff}));root.add(high);
 const edgeGeo=new THREE.BufferGeometry();edgeGeo.setAttribute('position',new THREE.BufferAttribute(edgePos,3));const edges=new THREE.LineSegments(edgeGeo,new THREE.LineBasicMaterial({color:0xe5ead5,opacity:.8,transparent:true,depthWrite:false,blending:THREE.AdditiveBlending}));root.add(edges);
 const neighborIds=new Int32Array(6),neighborDistances=new Float32Array(6);
 const px={x:0,v:0},py={x:0,v:0};let idle=0;
 PB.globe.originalPose=function(p){return {position:[1.25-p*.72,-p*.18,8.2-p*9.4],look:[root.position.x-.12,root.position.y,-p*2.7]}};
 PB.globe.applyPose=function(p){camera.position.set(1.25-p*.72,-p*.18,8.2-p*9.4);look.set(root.position.x-.12,root.position.y,-p*2.7);camera.lookAt(look)};
 PB.bus.on('resize',resize);PB.observe(hero,PB.globe);
 PB.frame(function(dt,t){
  if(!PB.globe.visible||document.hidden)return;
  const p=PB.reduced?0:PB.P,old=Math.min(1,p/.30),smooth=PB.smooth;
  PB.globe.applyPose(old);
  idle+=dt*.02;
  const react=1-smooth((p-.22)/.08);
  root.rotation.y=old*.72+(PB.reduced?0:idle*react);root.rotation.x=old*.16;
  const reveal=.18+.82*smooth((old-.08)/.74);lg.setDrawRange(0,Math.floor(totalLineVerts*reveal/2)*2);lineMat.opacity=.10+.10*reveal;
  shell1.material.opacity=.02+.09*smooth((old-.30)/.36);shell2.material.opacity=.01+.08*smooth((old-.58)/.36);
  const fade=1-smooth((old-.08)/.23);copy.style.opacity=fade;copy.style.pointerEvents=fade>.2?'auto':'none';copy.style.transform='translateY('+(-24*(1-fade))+'px)';stats.style.opacity=fade;depth.style.opacity=fade;cue.style.opacity=fade;
  const forestFade=1-.97*smooth((p-.31)/.12);shell1.material.opacity*=forestFade;shell2.material.opacity*=forestFade;particles.material.opacity=.88*forestFade;hubs.material.opacity=.9*forestFade;lineMat.opacity*=forestFade;
  inner.material.opacity=.08*forestFade;core.material.opacity=PB.mix(.27,.8,smooth((p-.30)/.08))*(1-.9*smooth((p-.38)/.1));
  if(bloom)bloom.strength=PB.mix(.55,.9,smooth((p-.30)/.08))*(1-.35*smooth((p-.38)/.12));
  ptr.set(PB.touch?Math.sin(t*.31):PB.pointer.ndcX,PB.touch?Math.cos(t*.23):PB.pointer.ndcY);
  PB.spring(px,PB.reduced?0:ptr.x*.08*react,4,1,dt);PB.spring(py,PB.reduced?0:ptr.y*.05*react,4,1,dt);
  camera.position.x+=px.x*react;camera.position.y+=py.x*react;camera.lookAt(look);
  root.updateMatrixWorld(true);camera.updateMatrixWorld(true);ray.setFromCamera(ptr,camera);
  const intersects=react>0&&!PB.reduced&&PB.quality<4&&ray.ray.intersectSphere(sphere,hit);
  if(intersects)localHit.copy(hit),root.worldToLocal(localHit);
  for(let k=0;k<N;k++){const q=k*3,bx=base[q],by=base[q+1],bz=base[q+2];let target=0;if(intersects){const dx=bx-localHit.x,dy=by-localHit.y,dz=bz-localHit.z,d2=dx*dx+dy*dy+dz*dz;if(d2<.3025)target=.22*smooth(1-Math.sqrt(d2)/.55)*react}
   const f=1+2*dt*.6*10,hoo=dt*100,hhoo=dt*hoo,inv=1/(f+hhoo),nx=(f*springPos[k]+dt*springVel[k]+hhoo*target)*inv;springVel[k]=(springVel[k]+hoo*(target-springPos[k]))*inv;springPos[k]=nx;
   const shift=PB.reduced?0:(nx+Math.sin(t*.6+k*.37)*.012*react)/Math.sqrt(bx*bx+by*by+bz*bz);pos[q]=bx*(1+shift);pos[q+1]=by*(1+shift);pos[q+2]=bz*(1+shift);
  }
  if(!PB.reduced)pg.attributes.position.needsUpdate=true;
  high.visible=edges.visible=!!intersects;
  if(intersects){distances.fill(Infinity);nearest.fill(-1);for(let h=0;h<H;h++){const q=h*3,dx=hp[q]-localHit.x,dy=hp[q+1]-localHit.y,dz=hp[q+2]-localHit.z,d=dx*dx+dy*dy+dz*dz;for(let n=0;n<3;n++)if(d<distances[n]){for(let m=2;m>n;m--){distances[m]=distances[m-1];nearest[m]=nearest[m-1]}distances[n]=d;nearest[n]=h;break}}
   if(nearest[0]!==oldNearest[0]||nearest[1]!==oldNearest[1]||nearest[2]!==oldNearest[2]){let ep=0;for(let n=0;n<3;n++){const h=nearest[n]*3;highPos[n*3]=hp[h];highPos[n*3+1]=hp[h+1];highPos[n*3+2]=hp[h+2];neighborIds.fill(-1);neighborDistances.fill(Infinity);for(let j=0;j<N;j++){const q=j*3,d=(base[q]-hp[h])**2+(base[q+1]-hp[h+1])**2+(base[q+2]-hp[h+2])**2;if(d>.00001)for(let m=0;m<6;m++)if(d<neighborDistances[m]){for(let z=5;z>m;z--){neighborDistances[z]=neighborDistances[z-1];neighborIds[z]=neighborIds[z-1]}neighborDistances[m]=d;neighborIds[m]=j;break}}for(let m=0;m<6;m++){const q=neighborIds[m]*3;edgePos[ep++]=hp[h];edgePos[ep++]=hp[h+1];edgePos[ep++]=hp[h+2];edgePos[ep++]=base[q];edgePos[ep++]=base[q+1];edgePos[ep++]=base[q+2]}}highGeo.attributes.position.needsUpdate=true;edgeGeo.attributes.position.needsUpdate=true;oldNearest.set(nearest)}
  }
  const outerVisible=p<.40||PB.reduced;inner.visible=core.visible=o1.visible=o2.visible=o3.visible=depthGroup.visible=outerVisible;
  if(PB.tree)PB.tree.update(dt,t,p,look);
  canvas.style.opacity=PB.reduced?'1':String(1-smooth((p-.96)/.04));
  if(composer&&PB.quality<2)composer.render();else renderer.render(scene,camera);
 });
})();
