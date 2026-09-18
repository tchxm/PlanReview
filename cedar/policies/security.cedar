@id("production")
forbid(principal, action, resource) when { context.production };
@id("public_access")
forbid(principal, action, resource) when { context.public_access };
@id("networking")
forbid(principal, action, resource) when { context.networking && context.deny_networking };
@id("contract_scope")
permit(principal, action, resource) when {
  context.addresses.contains(context.address) &&
  context.types.contains(context.resource_type) &&
  context.operations.contains(context.operation) &&
  context.regions.contains(context.region) &&
  !context.unknown
};
