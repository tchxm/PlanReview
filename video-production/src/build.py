"""Assemble the film. Usage: python build.py  (needs assets/raw/main.webm, scene*.webm, audio/seg*.mp3)"""
import json, subprocess, re
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
H=Path(__file__).resolve().parent.parent; A=H/'assets'; R=A/'raw'; T=H/'build'; T.mkdir(exist_ok=True)
M=json.load(open(A/'marks.json')); seg=json.load(open(H/'audio/segments.json'))
import imageio_ffmpeg; FF=imageio_ffmpeg.get_ffmpeg_exe()
def ff(*a): subprocess.run([FF,'-y','-loglevel','error',*map(str,a)],check=True)
VF='scale=1920:1080:flags=lanczos,fps=25,format=yuv420p'
def clip(name,src,ss,d):
    ff('-i',src,'-ss',ss,'-t',d,'-vf',VF,'-an','-c:v','libx264','-crf','18','-preset','veryfast',T/f'{name}.mp4'); return name
main=R/'main.webm'; st=[s['t'] for s in M['steps']]
plan=[]  # (clip name, duration)
def add(n,src,ss,d): clip(n,src,ss,d); plan.append((n,d))
# scene 1 (9s) real gate robot, then entering the site
add('1a',main,36.0,5.5); add('1b',main,M['site']-0.2,3.5)
# scene 2 (20s) real globe descent, then the problem
add('2a',main,M['site']+3.0,6.0); add('2b',R/'scene2.webm',0.3,14.0)
add('3',R/'scene3.webm',0.3,12.0)
for i,t in enumerate(st): add(f'4_{i}',main,max(t-0.3,0),4.8)
add('5',R/'scene5.webm',0.3,22.0); add('6',R/'scene6.webm',0.3,28.0)
add('7a',R/'scene7a.webm',0.3,6.0); add('7c',main,M['home_again']+0.6,3.0); add('7b',R/'scene7b.webm',0.3,7.0)
open(T/'list.txt','w').write(''.join(f"file '{n}.mp4'\n" for n,_ in plan))
ff('-f','concat','-safe','0','-i',T/'list.txt','-c','copy',T/'video_raw.mp4')
total=sum(d for _,d in plan); print('video seconds',total)
# scene start times for narration
bounds=[0,9,29,41,84.2,106.2,134.2]  # scene starts (s)
ins=[];fl=[]
for i,s in enumerate(seg):
    ins+=['-i',H/f'audio/seg{i+1}.mp3']; ms=int((bounds[i]+0.4)*1000); fl.append(f'[{i}:a]adelay={ms}|{ms},volume=1.6[n{i}]')
n=len(seg)
fl.append(''.join(f'[n{i}]' for i in range(n))+f'amix=inputs={n}:normalize=0[nar]')
ins+=['-f','lavfi','-i',f'sine=f=55:d={total}','-f','lavfi','-i',f'sine=f=82.4:d={total}','-f','lavfi','-i',f'anoisesrc=c=pink:a=0.02:d={total}']
fl.append(f'[{n}:a]volume=.05[a1];[{n+1}:a]volume=.03[a2];[{n+2}:a]lowpass=f=400,volume=.6[a3];[a1][a2][a3]amix=inputs=3:normalize=0,afade=t=in:d=3,afade=t=out:st={total-4}:d=4[amb]')
fl.append('[nar][amb]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-16:TP=-1.5,atrim=0:%s[out]'%total)
ff(*ins,'-filter_complex',';'.join(fl),'-map','[out]','-c:a','aac','-b:a','192k',T/'audio.m4a')
# captions: sentence split, timed by characters within each narration segment
font=ImageFont.truetype(r'C:\Windows\Fonts\georgia.ttf',44); caps=[]
for i,s in enumerate(seg):
    sents=re.split(r'(?<=[.?!])\s+',s['text']); tot=sum(len(x) for x in sents); t=bounds[i]+0.4
    for x in sents:
        d=s['dur']*len(x)/tot; caps.append((t,t+d,x)); t+=d
def srt_t(t): return '%02d:%02d:%02d,%03d'%(t//3600,t%3600//60,t%60,(t%1)*1000)
open(H/'audio/captions.srt','w',encoding='utf-8').write(''.join(f'{i+1}\n{srt_t(a)} --> {srt_t(b)}\n{x}\n\n' for i,(a,b,x) in enumerate(caps)))
def wrap(x):
    words=x.split();lines=[];cur=''
    for w in words:
        if font.getlength((cur+' '+w).strip())>1500: lines.append(cur);cur=w
        else: cur=(cur+' '+w).strip()
    return lines+[cur]
ci=[];ff_=[];prev='0:v'
for i,(a,b,x) in enumerate(caps):
    L=wrap(x); im=Image.new('RGBA',(1700,20+64*len(L)),(0,0,0,0)); d=ImageDraw.Draw(im)
    d.rounded_rectangle((0,0,im.width,im.height),12,fill=(8,8,7,170))
    for j,l in enumerate(L): d.text((im.width/2,10+64*j+32),l,font=font,fill=(239,233,220,255),anchor='mm')
    p=T/f'cap{i}.png'; im.save(p); ci+=['-i',p]
    ff_.append(f"[{prev}][{i+1}:v]overlay=(W-w)/2:H-h-70:enable='between(t,{a:.2f},{b:.2f})'[v{i}]"); prev=f'v{i}'
ff('-i',T/'video_raw.mp4',*ci,'-filter_complex',';'.join(ff_),'-map',f'[{prev}]','-c:v','libx264','-crf','19','-preset','veryfast','-pix_fmt','yuv420p',T/'video_cap.mp4')
out=H/'renders/PlanReview-final-demo.mp4'
ff('-i',T/'video_cap.mp4','-i',T/'audio.m4a','-i',H/'audio/captions.srt','-map','0:v','-map','1:a','-map','2','-c:v','copy','-c:a','copy','-c:s','mov_text','-metadata:s:s:0','language=eng','-shortest','-movflags','+faststart',out)
print(out)
