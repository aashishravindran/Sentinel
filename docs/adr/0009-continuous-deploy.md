# 0009. Continuous deploy of the demo gateway through scoped roles

## Context

The `SentinelDemo` stack (AgentCore Gateway, interceptors, Cognito, identity table) was deployed by
hand, through the CDK bootstrap roles. Those roles are account-wide administrators: the deploy role
can change any stack and the CloudFormation execution role has `AdministratorAccess`. Sentinel is a
security product, and its public repository is a target; whoever can get code onto `master` should
not get the AWS account with it.

## Decision

- **Deploy on merge.** CI's `deploy` job runs after `python` and `cdk` pass on a push to `master`:
  it deploys the Lambda bundle the `cdk` job built and tested, then runs `demo/smoke.py` against the
  live gateway with a throwaway Cognito user.
- **No bootstrap roles.** `SentinelDemo` uses `CliCredentialsStackSynthesizer` with its own asset
  bucket. `SentinelCiCd` (deployed by hand, never by CI) holds:
  - a deploy role trusted only by this repo's `production` environment (pinned to GitHub's owner
    and repo IDs), allowed to change only the `SentinelDemo` stack and run the smoke test;
  - a CloudFormation execution role scoped to the services the stack uses, which can create roles
    named `SentinelDemo-*` only with the `sentinel-demo-boundary` boundary attached;
  - the boundary: logs, the identity table, the envelope secret, invoking the stack's functions and
    `bedrock:Retrieve`.
- **A protected `master`.** Pull requests only, required checks, one approving review, auto-merge
  off. The maintainer merges deliberately (admin bypass, pull requests only). Agents open PRs.

## Consequences

- A malicious or buggy commit on `master` can break the demo gateway, not the account.
- Generated IDs (user pools, gateways) mean the execution role manages those services account-wide;
  CloudFormation still only touches resources in its own template.
- Creating a knowledge base needs Bedrock and S3 permissions the execution role doesn't have; those
  deploys are manual by design (see ADR 0008).
- An agent holding the maintainer's own GitHub token can still use the admin bypass. Real separation
  needs the agent to use a lower-privilege identity (a bot account or fine-grained token without
  admin), whose PRs the maintainer approves.
