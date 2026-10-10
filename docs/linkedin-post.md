# LinkedIn post (draft)

Images, in this order (LinkedIn shows several images as a gallery):
1. `docs/assets/live-test.png`: the live AWS run, Cognito → AgentCore Gateway → Sentinel
2. `docs/assets/architecture.png`: one engine, two ways in
3. `docs/assets/demo.png`: the local demo in a terminal

---

My RAG access-control layer had a hole in it, and the access control was working perfectly.

Sentinel filters what an AI agent can retrieve based on who the user is. v1's search tool took `user_id` as an argument. So an agent could pass `user_id="ceo"`, through a prompt injection or a plain mistake, and Sentinel would correctly enforce… the CEO's permissions.

The fix in v2: the model never says who the user is.

🔐 Identity comes from the connection: the user who launched the MCP server, or the `sub` of a verified login token. No tool takes a user ID.
🔄 Permissions are looked up live on every call (SpiceDB or DynamoDB), so revoking access applies to the very next request.
🎯 The filter goes into the vector query, not over the results, and every result is re-checked anyway.
☁️ The same engine runs inside Amazon Bedrock AgentCore Gateway: a request interceptor rebuilds every tool call from the verified identity, and a response interceptor re-checks what comes back.

Then I deployed it to AWS with real Cognito users and called it as each of them:
• alice got finance + public, the intern got public, the admin got nothing (admin rights ≠ document access)
• the intern sent `user_id="charlie"` and was still the intern
• no token, or a garbage token → 401 at the gateway, before any of my code ran
• I removed alice's finance tag mid-session; her next call, with the same unexpired token, came back public-only. No redeploy.
• every decision is one CloudWatch line: user, tags, allow or deny

The live run also caught a bug my local tests couldn't: the gateway hands notifications to the response interceptor as an empty 202, which my code rejected, breaking the MCP handshake. Fixed and pinned with a regression test. Test against the real thing.

Locally, CI runs the rest:
• 0 leaks in 1,728 adversarial attempts across 4 entry points, including a knowledge base that ignores filters
• recall@5 stays at 1.00 with the filter in the query; retrieve-then-filter drops to 0.10 at 10 teams
• the token tests caught FastMCP not checking `nbf`, now enforced in Sentinel's own checks

Code, ADRs and a threat model mapped to the OWASP LLM and Agentic Top 10s:
github.com/aashishravindran/Sentinel
github.com/aashishravindran/sentinel-engine

If you're putting agents in front of internal documents: where does your retrieval layer get the user's identity from?

#AIAgents #RAG #MCP #AWS #AgentCore #Security
