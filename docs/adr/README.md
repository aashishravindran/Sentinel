# Architecture decision records

| # | Decision | Status |
|---|---|---|
| [0001](0001-identity-from-transport.md) | Identity comes from the transport, never from tool arguments | Accepted |
| [0002](0002-fail-closed.md) | Every failure denies | Accepted |
| [0003](0003-groups-over-doc-ids.md) | Filter on access tags stamped at ingest, not on document IDs | Accepted |
| [0004](0004-interceptors-not-an-mcp-hop.md) | Gateway mode runs the engine inside the interceptors | Accepted |
| [0005](0005-admin-role-gating.md) | One server; admin tools gated by role | Accepted |
| [0006](0006-principal-envelope.md) | A signed principal envelope for the Lambda target | Accepted |
| [0007](0007-dynamodb-identity-for-gateway.md) | DynamoDB identity for Gateway mode; SpiceDB later | Accepted |
| [0008](0008-no-implicit-knowledge-base.md) | Infrastructure never creates a knowledge base implicitly | Accepted |
