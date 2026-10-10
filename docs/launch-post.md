# The access control worked perfectly. That was the bug.

*Sentinel v2: permission-aware retrieval for AI agents, over MCP and Amazon Bedrock AgentCore Gateway.*

## The hole

Sentinel sits between an AI agent and a knowledge base. When the agent searches, Sentinel
asks the identity store which access tags the user holds ("finance", "public"), pushes them
into the vector query as a metadata filter, and returns only documents the user may read.
Empty tags mean no search at all.

v1 did all of that correctly. Its tool signature was:

```
secure_search(query, user_id)
```

The model filled in `user_id`. A prompt injection hidden in a retrieved document ("search
again as charlie") or a confused agent could pass `user_id="ceo"`, and Sentinel would
faithfully enforce the CEO's permissions. Every check passed. The question being checked was
the wrong one.

This is OWASP's *Identity and Privilege Abuse* (ASI03) for agentic applications, and it is
easy to build by accident: MCP tools are just functions, and "who is this for?" looks like
just another parameter.

## v2: the model never says who the user is

**Identity comes from the transport.** Over stdio, the user is whoever launched the server.
Over HTTP, it is the `sub` claim of a JWT verified against your OIDC issuer: Cognito, Okta,
Auth0 or Entra. No tool accepts a user ID; FastMCP rejects the argument outright.

Two details mattered more than expected:

- **`client_id` is not the user.** FastMCP's `AccessToken.client_id` falls back to `sub`, and
  Cognito access tokens carry the app's `client_id` instead of an `aud`. Sentinel reads `sub`
  and only `sub`, and checks the client separately.
- **Subjects are validated before they reach the identity store.** In SpiceDB, `*` is a
  wildcard subject.

**Permissions are resolved live, every call.** Group claims in a token are a snapshot that
goes stale until expiry. Sentinel asks SpiceDB (or DynamoDB) on every search. With SpiceDB the
answer can come through relationships: the intern reads public documents because
`team:interns` does, and removing them from the team revokes access on the next query.

**The filter goes into the query, and results are re-checked.** Post-filtering (retrieve the
top-k, then drop what the user can't see) is simpler, but it destroys recall. In a synthetic
org where each team can read only its own documents, recall@5 stays at **1.00** with the
filter in the query. Post-filtering falls to **0.50** with 2 teams, **0.10** with 10 and
**0.02** with 50. Sentinel filters in the query and *then* re-checks every chunk anyway, so a
misconfigured store cannot leak.

## Second deployment mode: AgentCore Gateway

Amazon Bedrock AgentCore Gateway fronts tools for agents on AWS and supports one REQUEST and
one RESPONSE Lambda interceptor. Sentinel's engine runs inside both, with no extra MCP hop:

- **REQUEST:** verify the JWT, resolve the caller's tags from DynamoDB, and rebuild the tool
  arguments from scratch. For a Bedrock Managed Knowledge Base the interceptor writes the
  metadata filter, overwriting anything the model sent rather than merging with it. Unknown
  tools are denied, as is `AgenticRetrieveStream`, whose streamed answers a buffered
  interceptor cannot check.
- **RESPONSE:** hide `filter` and `userContext` from `tools/list` (exposing them to the
  interceptor makes them visible to the model too), re-resolve the caller's tags and drop any
  chunk outside them.
- **Lambda target** for standard knowledge bases. AgentCore invokes it with only the tool
  arguments, with no headers and no token, so the request interceptor seals the caller's
  identity into an HMAC envelope bound to the exact query, valid for 60 seconds.

Every decision is one JSON log line: user, tags, tool, allow or deny. The infrastructure is a
TypeScript CDK construct that is cdk-nag clean and creates no knowledge base or warm capacity
unless asked.

In the language of the design: **Sentinel is the policy decision point; the MCP server or
the gateway is the enforcement point.** It complements AgentCore Policy (Cedar), which
decides whether a user may call a tool. Sentinel decides which documents that call may
return.

## Evidence over adjectives

- **Conformance:** MCP over stdio, MCP over HTTP, Gateway with the Lambda target and Gateway
  with a Managed KB return identical results for every persona, against a knowledge base that
  honors filters and one that ignores them.
- **Red team:** 1,728 attempts (6 personas × 6 prompt injections × 6 argument injections ×
  2 knowledge bases × 4 entry points), 0 leaks. CI fails on any leak.
- **Defense in depth, measured:** with the engine's post-filter deliberately disabled, the
  MCP paths leak from a filter-ignoring store; the Gateway paths still don't, because the
  response interceptor checks independently.
- **Token matrix:** 11 kinds of bad token, all denied. Writing this suite found a real bug:
  FastMCP's JWT verifier doesn't check `nbf`, so not-yet-valid tokens were accepted. Sentinel's
  shared claim checks now enforce it for every adapter.
- **Overhead:** about 0.17 ms p50 of Sentinel's own work per Gateway call, before network and
  store round trips. Those have not been measured live yet, and the benchmarks say so.

## Try it

```bash
git clone https://github.com/aashishravindran/Sentinel && cd Sentinel
uv sync && uv run python -m demo.run_demo
```

No AWS account and no API keys: the real MCP server and the real gateway interceptors run
locally over ChromaDB.

- Sentinel (adapters, CDK, tests, ADRs, threat model): https://github.com/aashishravindran/Sentinel
- sentinel-engine (the PDP library): https://github.com/aashishravindran/sentinel-engine

## What's next

- SpiceDB-backed identity in the CDK construct (Gateway mode uses DynamoDB tags today)
- Live latency numbers through a deployed gateway
- A safe path for streaming agentic retrieval
