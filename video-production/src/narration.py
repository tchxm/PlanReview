"""One voice (en-US-AvaNeural) for every segment; captions text is the display version, speech text has pronunciation fixes."""
import asyncio, json, subprocess
from pathlib import Path
import edge_tts
OUT=Path(__file__).resolve().parent.parent/'audio'
VOICE='en-US-AvaNeural'; RATE='-6%'
S=[
("An AI agent can propose infrastructure changes in seconds. But who decides whether those changes are actually allowed?",None),
("Every node in a cloud is a resource someone depends on. Here, an agent was asked to raise one Lambda function's memory. Its edit also loosened an S3 bucket's public access block, and added a network rule. Nobody asked for that. And nobody had drawn the line.",None),
("PlanReview makes that line explicit. A human confirms a boundary first. Then every proposed change is judged against it, before anything is applied.",None),
("It starts with a contract: which resources may change, which operations, how many, and what is forbidden. An agent edits Terraform, and Terraform produces a real plan. Cedar policies then give every change a verdict. Allow, when it sits inside the boundary. Review, when a human must decide. And deny, when it crosses a forbidden line. Every verdict shows its reason and the policy behind it. A deny can never be approved away. The apply gate opens only when nothing is denied, and every step is written to a tamper-evident audit chain that anyone can verify.",None),
("Under the hood, a FastAPI backend drives the pipeline. Terraform creates the plan. A canonicalizer normalizes and hashes it. Cedar decides. SQLite stores tasks and an H-MAC audit chain. The front end is plain JavaScript, with three J S.",None),
("How does it use AWS? Plans are written for the AWS Terraform provider, covering Lambda functions, S3 buckets, and security groups. Permitted changes apply only to a local AWS emulator. Cedar is the language behind Amazon Verified Permissions, but PlanReview does not call that service. No real AWS account is touched, and nothing is deployed.",None),
("Back to that same change. PlanReview does not let the public access change through. The boundary stays where the human drew it. PlanReview. Human intent, explicit infrastructure boundaries.",None),
]
SPEECH=lambda t:(t.replace('H-MAC','H mac').replace('three J S','three dot J S').replace('PlanReview','Plan Review').replace('S3','S three').replace('canonicalizer','canonicalizer'))
async def main():
    meta=[]
    for i,(t,_) in enumerate(S):
        f=OUT/f'seg{i+1}.mp3'
        await edge_tts.Communicate(SPEECH(t),VOICE,rate=RATE,pitch='-2Hz').save(str(f))
        d=float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(f)]))
        meta.append({'i':i+1,'text':t,'dur':round(d,2)}); print(i+1,round(d,1))
    json.dump(meta,open(OUT/'segments.json','w'),indent=1)
asyncio.run(main())
