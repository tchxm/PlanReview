"""Contract compatibility checks. These are not live-model execution tests."""
import json
import pytest
from engine.contract import draft,confirm
from engine.types import Contract
from engine.agent import bedrock_model

PHASE1_FIELDS={
    'contract_id','task','allowed_resource_addresses','allowed_resource_types',
    'allowed_operations','allowed_regions','max_changed_resources',
    'max_cost_delta','denies','expires_at','status',
}

def test_stub_has_exact_phase1_payload_and_is_inert():
    value=draft("increase dev-api Lambda memory, don't touch networking or production")
    payload=json.loads(value.model_dump_json())
    assert set(payload)==PHASE1_FIELDS
    assert set(value.model_dump(mode='json'))==PHASE1_FIELDS
    validated=Contract.model_validate(payload)
    assert validated.status=='draft' and not validated.active()
    assert validated.allowed_resource_addresses==('aws_lambda_function.dev_api',)
    assert validated.allowed_operations==('update',)
    assert {'production','networking'}<=set(validated.denies)
    assert confirm(validated).active()
    assert confirm(validated).model_dump()['version']==1

def test_unconfigured_live_model_never_falls_back_to_replay(monkeypatch):
    monkeypatch.setattr('engine.agent.bedrock_configuration',lambda:{
        'model_configured':False,'credentials_resolved':False,
        'bearer_token_configured':False,'region':'ap-south-1',
    })
    with pytest.raises(ValueError,match='missing PLANREVIEW_BEDROCK_MODEL and AWS credentials'):
        bedrock_model()
