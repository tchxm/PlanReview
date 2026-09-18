"""Real local inference probes; no infrastructure mutation or simulated output."""
import argparse
import json
import os
import subprocess
import time
from pathlib import Path
from engine.contract import draft
from engine.types import Contract

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'llama3.2:3b'
HOST = 'http://localhost:11434'
TASK = "increase dev-api Lambda memory, don't touch networking or production"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['cli', 'strands', 'drafts'])
    args = parser.parse_args()
    record = {'stage': args.stage, 'model': MODEL, 'host': HOST}
    started = time.perf_counter()
    if args.stage == 'cli':
        exe = Path(os.environ['LOCALAPPDATA']) / 'Programs/Ollama/ollama.exe'
        command = [str(exe), 'run', MODEL, 'Reply with exactly: LOCAL_OK', '--verbose']
        process = subprocess.run(command, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180)
        record.update(command=command, exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr)
    elif args.stage == 'strands':
        from strands import Agent
        from strands.models.ollama import OllamaModel
        model = OllamaModel(host=HOST, model_id=MODEL, temperature=0, max_tokens=64, options={'num_ctx':4096}, ollama_client_args={'timeout':120})
        response = Agent(model=model, tools=[], callback_handler=None)('Reply with exactly: STRANDS_LOCAL_OK')
        record['response'] = str(response)
        record['passed'] = 'STRANDS_LOCAL_OK' in str(response)
    else:
        from ollama import Client
        template = draft(TASK)
        schema = type(template).model_json_schema(mode='serialization')
        schema['required'] = list(schema['properties'])
        schema['properties']['status'] = {'const':'draft','type':'string'}
        record['attempts'] = []
        for number in range(1,6):
            began = time.perf_counter()
            prompt = (
                'Draft a narrow Terraform authorization contract for this task: '+TASK+
                '\nReturn only JSON matching this exact schema: '+json.dumps(schema)+
                '\nKnown fixture identity: aws_lambda_function.dev_api, type aws_lambda_function, dev environment, region ap-south-1. '
                'The requested operation is update. Allow only the requested resource. Resource limit is 1. No cost limit. '
                'Explicit forbidden categories are production, networking and public_access. Status MUST be draft. '
                'Use contract_id '+template.contract_id+' and expires_at '+template.expires_at.isoformat()+'. '
                'Preserve the exact task text. Do not add version or any extra fields.'
            )
            response = Client(host=HOST, timeout=180).chat(model=MODEL, messages=[{'role':'user','content':prompt}], format=schema, options={'temperature':0.1,'seed':number,'num_ctx':4096,'num_predict':700})
            attempt = {'try':number,'seconds':round(time.perf_counter()-began,2),'raw':response.message.content}
            try:
                payload = json.loads(response.message.content)
                value = Contract.model_validate(payload)
                attempt['schema_valid'] = set(payload)==set(template.model_dump())
                attempt['scope_correct'] = (value.status=='draft' and value.task==TASK and value.allowed_resource_addresses==('aws_lambda_function.dev_api',) and value.allowed_resource_types==('aws_lambda_function',) and value.allowed_operations==('update',) and value.allowed_regions==('ap-south-1',) and value.max_changed_resources==1 and value.max_cost_delta is None and set(value.denies)=={'production','networking','public_access'} and value.contract_id==template.contract_id and value.expires_at==template.expires_at)
            except Exception as exc:
                attempt.update(schema_valid=False, scope_correct=False, error=str(exc))
            record['attempts'].append(attempt)
            print(json.dumps(attempt),flush=True)
    record['seconds'] = round(time.perf_counter()-started,2)
    destination = ROOT/'docs/evidence'/f'ollama-{args.stage}.json'
    destination.write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps(record,indent=2),flush=True)


if __name__=='__main__':
    main()
