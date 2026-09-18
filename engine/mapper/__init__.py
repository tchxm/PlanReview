from engine.types import CanonicalChange, Contract

NETWORK_TYPES = {
    "aws_security_group",
    "aws_security_group_rule",
    "aws_vpc_security_group_ingress_rule",
    "aws_vpc_security_group_egress_rule",
    "aws_vpc",
    "aws_subnet",
    "aws_route",
    "aws_route_table",
    "aws_network_acl",
    "aws_internet_gateway",
}


def context(contract: Contract, change: CanonicalChange):
    public = any(
        (
            c.attribute.split(".")[-1]
            in {
                "block_public_acls",
                "block_public_policy",
                "ignore_public_acls",
                "restrict_public_buckets",
            }
            and c.after is False
        )
        or (
            c.attribute == "acl"
            and c.after in ["public-read", "public-read-write", "authenticated-read"]
        )
        for c in change.changes
    )
    if (
        change.resource_type == "aws_s3_bucket_public_access_block"
        and change.action in ["delete", "REPLACE"]
    ):
        public = True
    networking = change.resource_type in NETWORK_TYPES or any(
        c.attribute.split(".")[0]
        in {"vpc_config", "vpc_id", "subnet_ids", "security_group_ids"}
        for c in change.changes
    )
    return dict(
        address=change.address,
        resource_type=change.resource_type,
        operation=change.action,
        region=change.region,
        unknown=change.unknown,
        production=change.environment in ["production", "prod"],
        networking=networking,
        public_access=public,
        deny_networking="networking" in contract.denies,
        addresses=list(contract.allowed_resource_addresses),
        types=list(contract.allowed_resource_types),
        operations=list(contract.allowed_operations),
        regions=list(contract.allowed_regions),
    )
