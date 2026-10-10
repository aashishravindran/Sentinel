# LinkedIn post (draft)

Attach `docs/assets/architecture.png` (1200×627) and, optionally, `docs/assets/demo.png`.

---

My RAG access-control layer had a hole in it, and the access control was working perfectly.

Sentinel filters what an AI agent can retrieve based on who the user is. v1's search tool took `user_id` as an argument. So an agent could pass `user_id="ceo"`, through a prompt injection or a plain mistake, and Sentinel would correctly enforce… the CEO's permissions.

The fix in v2: the model never says who the user is.

🔐 Identity comes from the connection: the user who launched the MCP server, or the `sub` of a verified JWT. No tool takes a user ID.
🔄 Permissions are resolved live (SpiceDB, DynamoDB) on every call, so revoking access applies to the next search.
🎯 The filter goes into the vector query, not over the results. Then every chunk is re-checked anyway.
☁️ The same engine now runs inside Amazon Bedrock AgentCore Gateway interceptors, so agents on AWS get it with no extra hop.

What the tests say:
• 0 leaks in 1,728 adversarial attempts (prompt injection × argument smuggling × a knowledge base that ignores filters × 4 entry points), checked in CI on every PR
• Recall@5 stays at 1.00 when the filter is in the query. Retrieve-then-filter drops to 0.10 with 10 teams.
• ~0.17 ms of Sentinel's own overhead per gateway call
• The red-team suite caught a real bug while I was writing it: FastMCP doesn't check `nbf`, so not-yet-valid tokens got through. Fixed in the shared checks.

Code, ADRs and a threat model mapped to the OWASP LLM and Agentic Top 10s:
github.com/aashishravindran/Sentinel
github.com/aashishravindran/sentinel-engine

If you're putting agents in front of internal documents: where does your retrieval layer get the user's identity from?

#AIAgents #RAG #MCP #AWS #Security #AgentCore
