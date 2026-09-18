(function(){
const PB=window.PB,times=new Float32Array(60);let i=0,count=0,sum=0,slow=0;
PB.perf={average:0,tiers:[],sample(ms,dt){sum-=times[i];times[i]=ms;sum+=ms;i=(i+1)%60;count=Math.min(60,count+1);this.average=sum/count;if(count<60)return;if(this.average>22)slow+=dt;else slow=0;if(slow>=2&&PB.quality<5){PB.quality++;slow=0;this.tiers.push({tier:PB.quality,average:this.average});if(PB.quality===1){if(PB.globe){PB.globe.renderer.setPixelRatio(Math.max(.75,Math.min(devicePixelRatio,1.5)-.25));PB.globe.composer&&PB.globe.composer.setPixelRatio(Math.max(.75,Math.min(devicePixelRatio,1.5)-.25))}if(PB.robot)PB.robot.renderer.setPixelRatio(Math.max(.75,Math.min(devicePixelRatio,1.75)-.25));PB.bus.emit('resize')}}}};
PB.frame((dt,t,ms)=>{if(PB.started&&((PB.globe&&PB.globe.visible)||(PB.robot&&PB.robot.visible)))PB.perf.sample(ms,dt)});
})();
