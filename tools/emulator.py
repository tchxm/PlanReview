"""Local AWS emulator (moto) for proving that a PERMITTED change really applies, with no Docker and no AWS account.

Everything is bound to 127.0.0.1 with dummy credentials. `EmulatorGuard` (engine/gate.py) refuses to let the
apply path talk to anything else. Used by tests/test_emulator_apply.py and tools/prove_emulator_apply.py.
"""

import json
import os
import socket
import threading
import time

ACCOUNT = "123456789012"
VPC_ID = "vpc-12345678"  # the id baked into terraform/fixtures/baseline/main.tf


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Emulator:
    def __init__(self):
        self.port = _free_port()
        self.endpoint = f"http://127.0.0.1:{self.port}"
        self._server = None

    def env(self):
        """Environment that points the AWS provider at the emulator (used for every terraform command)."""
        return {
            "PLANREVIEW_EMULATOR_ENDPOINT": self.endpoint,
            "AWS_ENDPOINT_URL": self.endpoint,
            "AWS_ACCESS_KEY_ID": "test",
            "AWS_SECRET_ACCESS_KEY": "test",
            "AWS_S3_USE_PATH_STYLE": "true",
        }

    def client(self, service):
        import boto3

        return boto3.client(service, endpoint_url=self.endpoint, region_name="ap-south-1", aws_access_key_id="test", aws_secret_access_key="test")

    def start(self):
        import moto.ec2.models.vpcs as vpcs
        from moto.server import ThreadedMotoServer

        vpcs.random_vpc_id = lambda: VPC_ID  # the baseline pins this VPC id; moto only adds default rules to VPCs that exist
        self._server = ThreadedMotoServer(ip_address="127.0.0.1", port=self.port, verbose=False)
        self._server.start()
        for _ in range(50):
            try:
                socket.create_connection(("127.0.0.1", self.port), timeout=0.2).close()
                break
            except OSError:
                time.sleep(0.1)
        import urllib.request

        urllib.request.urlopen(urllib.request.Request(f"{self.endpoint}/moto-api/reset", method="POST"), timeout=10).read()  # moto state is process-global
        self.client("ec2").create_vpc(CidrBlock="10.0.0.0/16")
        self.client("iam").create_role(
            RoleName="demo",
            AssumeRolePolicyDocument=json.dumps(
                {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
            ),
        )
        return self

    def stop(self):
        if self._server:
            self._server.stop()
            self._server = None

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    def snapshot(self):
        """Comparable view of the resources the baseline manages."""
        lam, s3, ec2 = self.client("lambda"), self.client("s3"), self.client("ec2")
        fn = lam.get_function_configuration(FunctionName="dev-api")
        sgs = [g for g in ec2.describe_security_groups()["SecurityGroups"] if g["GroupName"] == "dev-api"]
        return {
            "lambda": {k: fn.get(k) for k in ("MemorySize", "Timeout", "Handler", "Runtime", "Role", "Environment")},
            "lambda_tags": lam.list_tags(Resource=fn["FunctionArn"])["Tags"],
            "bucket_tags": {t["Key"]: t["Value"] for t in s3.get_bucket_tagging(Bucket="planreview-demo-assets")["TagSet"]},
            "public_access": s3.get_public_access_block(Bucket="planreview-demo-assets")["PublicAccessBlockConfiguration"],
            "sg": [{"desc": g["Description"], "ingress": g["IpPermissions"], "egress": g["IpPermissionsEgress"]} for g in sgs],
        }
