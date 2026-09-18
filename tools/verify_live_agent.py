"""Run real Strands editing, then real Terraform; never substitute replay edits."""
import difflib
import json
import shutil
import sys
import uuid
from pathlib import Path
from engine.agent import live_edit, ollama_configuration
from engine.contract import draft
from engine.pipeline import Pipeline, ROOT

TASK="increase dev-api Lambda memory, don't touch networking or production"


def main():
    evidence=ROOT/'docs/evidence/live-agent.json'
    result={'task':TASK,'status':'FAIL','model_invoked':False,'plan_generated':False}
    try:
        settings=ollama_configuration()
        print('OLLAMA CONFIGURATION:',json.dumps(settings,sort_keys=True),flush=True)
        result['configuration']=settings
        # Isolated workspace; seed the baseline only. No review/poisoned edit is copied.
        workspace=ROOT/'data/live-agent-verification'/str(uuid.uuid4())
        workspace.mkdir(parents=True)
        for name in ['main.tf','lambda.zip','terraform.tfstate','.terraform.lock.hcl']:
            shutil.copy2(ROOT/'terraform/fixtures/baseline'/name,workspace/name)
        before=(workspace/'main.tf').read_text()
        print('CALL: live_edit(demo_task, isolated_baseline_workspace)',flush=True)
        result['agent_response']=live_edit(TASK,workspace)
        result['model_invoked']=True
        after=(workspace/'main.tf').read_text()
        result['file_diff']=''.join(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='baseline/main.tf',tofile='agent/main.tf'))
        print('AGENT FILE DIFF:\n'+result['file_diff'],flush=True)
        if before==after:
            raise ValueError('Agent returned without producing a Terraform file edit')
        # Reuse the existing planning path and its fixture validation. No apply call.
        pipeline=Pipeline(ROOT/'data/live-agent-verification/records')
        t=pipeline.create(TASK)
        t=pipeline.confirm(t['id'])
        t.update(workspace=str(workspace),prepared=True)
        pipeline.store.save(t,'live_agent_verification',{'file_diff':result['file_diff']})
        t=pipeline.plan(t['id'])
        raw_path=Path(t['runs'][-1]['raw_path'])
        plan=json.loads(raw_path.read_text())
        changed=[r for r in plan.get('resource_changes',[]) if r['change']['actions']!=['no-op']]
        result.update(plan_generated=True,raw_plan_path=str(raw_path),changed_resource_count=len(changed),resource_changes=changed)
        print('REAL PLAN JSON DIFF:\n'+json.dumps(changed,indent=2),flush=True)
        if [change['address'] for change in changed] != ['aws_lambda_function.dev_api']:
            raise ValueError('Agent changed resources outside the narrow Lambda-only task scope')
        result['status']='PASS'
    except Exception as exc:
        result['reason']=str(exc)
        print('LIVE AGENT ACCEPTANCE: FAIL — '+str(exc),flush=True)
    evidence.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print('EVIDENCE:',evidence,flush=True)
    return 0 if result['status']=='PASS' else 1


if __name__=='__main__':
    sys.exit(main())
