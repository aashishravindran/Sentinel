# Copyright (c) 2026 Aashish Ravindran. All rights reserved.
# Use of this software is governed by the Elastic License 2.0
# found in the LICENSE file.

#!/usr/bin/env python3
"""
scripts/setup_aws.py — Provision Sentinel's AWS infrastructure.

Creates (in order):
  1. DynamoDB table           — identity store (user_id → tags)
  2. S3 bucket                — document storage for Bedrock KB
  3. IAM role                 — trusted by Bedrock; grants S3 + AOSS + embed access
  4. OpenSearch Serverless    — vector collection supporting hybrid (knn + BM25) search
  5. AOSS vector index        — knn_vector + text fields matching Bedrock KB field names
  6. Bedrock Knowledge Base   — points at AOSS collection with Titan embed model
  7. S3 data source           — attached to KB, covering the configured S3 prefix

Prints the full env-var block to paste into .mcp.json when complete.

Usage:
    python scripts/setup_aws.py --stack sentinel --region us-east-1
    python scripts/setup_aws.py --stack sentinel --region us-east-1 --s3-prefix docs/
    python scripts/setup_aws.py --stack sentinel --region us-east-1 --destroy

Prerequisites:
    - AWS credentials configured (env vars, ~/.aws/credentials, or instance profile)
    - Caller must have IAM permissions to create/delete the resources above
    - uv add boto3  (aioboto3 already satisfies this transitively, but boto3 is used
      here directly since setup is a one-shot sync task)
"""

import argparse
import json
import sys
import time
from dotenv import load_dotenv
load_dotenv()  # pick up AWS_PROFILE / AWS_ACCESS_KEY_ID etc. from .env if present

import boto3

# ── Constants ─────────────────────────────────────────────────────────────────

# Bedrock embedding model and its output dimensionality.
EMBED_MODEL_ID = "amazon.titan-embed-text-v2:0"
EMBED_DIM = 1024

# AOSS index field names that Bedrock KB expects.
VECTOR_FIELD = "bedrock-knowledge-base-default-vector"
TEXT_FIELD = "AMAZON_BEDROCK_TEXT_CHUNK"
METADATA_FIELD = "AMAZON_BEDROCK_METADATA"


# ── Helpers ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(f"    {msg}", flush=True)


def wait_dots(seconds: int, label: str) -> None:
    print(f"    Waiting {seconds}s {label}", end="", flush=True)
    for _ in range(seconds):
        time.sleep(1)
        print(".", end="", flush=True)
    print()


# ── 1. DynamoDB ───────────────────────────────────────────────────────────────

def create_ddb_table(client, table_name: str) -> None:
    try:
        client.create_table(
            TableName=table_name,
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}],
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
            Tags=[{"Key": "sentinel:managed", "Value": "true"}],
        )
        log(f"Created table: {table_name}")
    except client.exceptions.ResourceInUseException:
        log(f"Table already exists: {table_name}")


def delete_ddb_table(client, table_name: str) -> None:
    try:
        client.delete_table(TableName=table_name)
        log(f"Deleted table: {table_name}")
    except client.exceptions.ResourceNotFoundException:
        log(f"Table not found (skipping): {table_name}")


# ── 2. S3 ─────────────────────────────────────────────────────────────────────

def create_s3_bucket(client, bucket_name: str, region: str) -> None:
    try:
        if region == "us-east-1":
            client.create_bucket(Bucket=bucket_name)
        else:
            client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
        client.put_bucket_tagging(
            Bucket=bucket_name,
            Tagging={"TagSet": [{"Key": "sentinel:managed", "Value": "true"}]},
        )
        log(f"Created bucket: {bucket_name}")
    except client.exceptions.BucketAlreadyOwnedByYou:
        log(f"Bucket already exists: {bucket_name}")
    except client.exceptions.BucketAlreadyExists:
        sys.exit(f"\nERROR: S3 bucket '{bucket_name}' is already owned by another account.")


def delete_s3_bucket(client, bucket_name: str) -> None:
    try:
        # Must empty the bucket (including all versions) before deletion.
        paginator = client.get_paginator("list_object_versions")
        for page in paginator.paginate(Bucket=bucket_name):
            objects = [
                {"Key": o["Key"], "VersionId": o["VersionId"]}
                for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
            ]
            if objects:
                client.delete_objects(Bucket=bucket_name, Delete={"Objects": objects})
        client.delete_bucket(Bucket=bucket_name)
        log(f"Deleted bucket: {bucket_name}")
    except client.exceptions.NoSuchBucket:
        log(f"Bucket not found (skipping): {bucket_name}")


# ── 3. IAM ────────────────────────────────────────────────────────────────────

def _inline_policy(bucket_name: str, region: str, account_id: str) -> dict:
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "S3ReadWrite",
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:ListBucket"],
                "Resource": [
                    f"arn:aws:s3:::{bucket_name}",
                    f"arn:aws:s3:::{bucket_name}/*",
                ],
            },
            {
                "Sid": "BedrockEmbed",
                "Effect": "Allow",
                "Action": "bedrock:InvokeModel",
                "Resource": (
                    f"arn:aws:bedrock:{region}::foundation-model/{EMBED_MODEL_ID}"
                ),
            },
            {
                "Sid": "AOSSAccess",
                "Effect": "Allow",
                "Action": "aoss:APIAccessAll",
                "Resource": f"arn:aws:aoss:{region}:{account_id}:collection/*",
            },
        ],
    }


def create_iam_role(client, role_name: str, bucket_name: str, region: str, account_id: str) -> str:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "bedrock.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account_id}
                },
            }
        ],
    }
    try:
        resp = client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Sentinel Bedrock KB execution role",
            Tags=[{"Key": "sentinel:managed", "Value": "true"}],
        )
        role_arn = resp["Role"]["Arn"]
        log(f"Created IAM role: {role_name}")
    except client.exceptions.EntityAlreadyExistsException:
        role_arn = client.get_role(RoleName=role_name)["Role"]["Arn"]
        log(f"IAM role already exists: {role_name}")

    # Always overwrite the inline policy so it stays current.
    client.put_role_policy(
        RoleName=role_name,
        PolicyName=f"{role_name}-policy",
        PolicyDocument=json.dumps(_inline_policy(bucket_name, region, account_id)),
    )
    log("Attached inline policy to role")
    return role_arn


def delete_iam_role(client, role_name: str) -> None:
    try:
        for policy in client.list_role_policies(RoleName=role_name)["PolicyNames"]:
            client.delete_role_policy(RoleName=role_name, PolicyName=policy)
        client.delete_role(RoleName=role_name)
        log(f"Deleted IAM role: {role_name}")
    except client.exceptions.NoSuchEntityException:
        log(f"IAM role not found (skipping): {role_name}")


# ── 4. OpenSearch Serverless collection ───────────────────────────────────────

def create_aoss_collection(
    client, name: str, role_arn: str, region: str, account_id: str, caller_arn: str
) -> tuple[str, str]:
    """
    Create the AOSS security/access policies and the collection.
    Returns (collection_id, collection_endpoint).

    Policy strategy:
      - Encryption: AWS-managed key (simplest; bring your own KMS if needed)
      - Network:    public endpoint (required for Bedrock KB to reach the collection)
      - Data access: grants the Bedrock role + the caller full index CRUD rights
    """
    enc_policy = json.dumps({
        "Rules": [{"ResourceType": "collection", "Resource": [f"collection/{name}"]}],
        "AWSOwnedKey": True,
    })
    _try_create_aoss_policy(client, "security", "encryption", f"{name}-enc", enc_policy)

    net_policy = json.dumps([{
        "Rules": [
            {"ResourceType": "collection", "Resource": [f"collection/{name}"]},
            {"ResourceType": "dashboard",  "Resource": [f"collection/{name}"]},
        ],
        "AllowFromPublic": True,
    }])
    _try_create_aoss_policy(client, "security", "network", f"{name}-net", net_policy)

    # Grant both the Bedrock KB role and the script caller index + collection rights.
    data_policy = json.dumps([{
        "Rules": [
            {
                "ResourceType": "index",
                "Resource": [f"index/{name}/*"],
                "Permission": [
                    "aoss:CreateIndex", "aoss:DeleteIndex",
                    "aoss:UpdateIndex", "aoss:DescribeIndex",
                    "aoss:ReadDocument", "aoss:WriteDocument",
                ],
            },
            {
                "ResourceType": "collection",
                "Resource": [f"collection/{name}"],
                "Permission": [
                    "aoss:CreateCollectionItems",
                    "aoss:DescribeCollectionItems",
                ],
            },
        ],
        "Principal": [
            role_arn,
            caller_arn,  # exact ARN of the IAM user/role running this script
        ],
    }])
    _try_create_aoss_policy(client, "access", "data", f"{name}-access", data_policy)

    # Create the collection.
    try:
        resp = client.create_collection(
            name=name,
            type="VECTORSEARCH",
            tags=[{"key": "sentinel:managed", "value": "true"}],
        )
        collection_id = resp["createCollectionDetail"]["id"]
        log(f"Created AOSS collection: {name} (id={collection_id})")
    except client.exceptions.ConflictException:
        resp = client.batch_get_collection(names=[name])
        collection_id = resp["collectionDetails"][0]["id"]
        log(f"AOSS collection already exists: {name}")

    endpoint = _wait_for_aoss_active(client, collection_id, name)
    return collection_id, endpoint


def _try_create_aoss_policy(client, kind: str, policy_type: str, name: str, policy: str) -> None:
    """Create or update an AOSS security/access policy (always writes the latest version)."""
    try:
        if kind == "security":
            client.create_security_policy(name=name, type=policy_type, policy=policy)
        else:
            client.create_access_policy(name=name, type=policy_type, policy=policy)
        log(f"Created AOSS {policy_type} policy: {name}")
    except client.exceptions.ConflictException:
        # Policy exists — update it so the principal list stays current.
        try:
            if kind == "security":
                existing = client.get_security_policy(name=name, type=policy_type)
                version = existing["securityPolicyDetail"]["policyVersion"]
                client.update_security_policy(name=name, type=policy_type, policy=policy, policyVersion=version)
            else:
                existing = client.get_access_policy(name=name, type=policy_type)
                version = existing["accessPolicyDetail"]["policyVersion"]
                client.update_access_policy(name=name, type=policy_type, policy=policy, policyVersion=version)
            log(f"Updated AOSS {policy_type} policy: {name}")
        except Exception as e:
            log(f"Warning: could not update AOSS {policy_type} policy: {e}")


def _wait_for_aoss_active(client, collection_id: str, name: str) -> str:
    print("    Waiting for AOSS collection to become ACTIVE", end="", flush=True)
    for _ in range(60):  # up to 10 minutes
        resp = client.batch_get_collection(ids=[collection_id])
        detail = resp["collectionDetails"][0]
        status = detail.get("status", "")
        if status == "ACTIVE":
            print(" active.")
            return detail["collectionEndpoint"]
        if status == "FAILED":
            sys.exit(f"\nERROR: AOSS collection '{name}' failed to create.")
        print(".", end="", flush=True)
        time.sleep(10)
    sys.exit("\nERROR: Timed out waiting for AOSS collection to become active.")


def delete_aoss_collection(client, name: str) -> None:
    try:
        resp = client.batch_get_collection(names=[name])
        if not resp.get("collectionDetails"):
            log(f"AOSS collection not found (skipping): {name}")
        else:
            collection_id = resp["collectionDetails"][0]["id"]
            client.delete_collection(id=collection_id)
            log(f"Deleted AOSS collection: {name}")
    except Exception as e:
        log(f"Could not delete AOSS collection: {e}")

    for kind, policy_type, suffix in [
        ("security", "encryption", "-enc"),
        ("security", "network",    "-net"),
        ("access",   "data",       "-access"),
    ]:
        try:
            if kind == "security":
                client.delete_security_policy(name=f"{name}{suffix}", type=policy_type)
            else:
                client.delete_access_policy(name=f"{name}{suffix}", type=policy_type)
            log(f"Deleted AOSS {policy_type} policy")
        except Exception:
            pass


# ── 5. AOSS vector index ──────────────────────────────────────────────────────

def create_aoss_index(endpoint: str, index_name: str, region: str, session: boto3.Session) -> None:
    """
    PUT the vector index using requests-aws4auth for reliable SigV4 signing.

    Index design:
      - knn: true           enables approximate nearest-neighbour search (dense)
      - VECTOR_FIELD        knn_vector, HNSW with faiss — the dense retrieval field
      - TEXT_FIELD          text, indexed=true — BM25 keyword search field (hybrid)
      - METADATA_FIELD      text, indexed=false — stores raw metadata, not searched
    """
    import requests
    from requests_aws4auth import AWS4Auth

    creds = session.get_credentials().get_frozen_credentials()
    auth = AWS4Auth(
        creds.access_key,
        creds.secret_key,
        region,
        "aoss",
        session_token=creds.token,
    )

    mapping = {
        "settings": {"index": {"knn": True}},
        "mappings": {
            "properties": {
                VECTOR_FIELD: {
                    "type": "knn_vector",
                    "dimension": EMBED_DIM,
                    "method": {
                        "name": "hnsw",
                        "engine": "faiss",
                        "space_type": "l2",
                        "parameters": {"m": 16, "ef_construction": 512},
                    },
                },
                TEXT_FIELD:     {"type": "text", "index": True},
                METADATA_FIELD: {"type": "text", "index": False},
            }
        },
    }

    url = f"{endpoint}/{index_name}"

    for attempt in range(1, 10):
        resp = requests.put(url, auth=auth, json=mapping)

        if resp.status_code == 200:
            if resp.json().get("acknowledged"):
                log(f"Created AOSS index: {index_name}")
            else:
                log(f"AOSS index response: {resp.json()}")
            return
        elif resp.status_code == 400:
            if resp.json().get("error", {}).get("type") == "resource_already_exists_exception":
                log(f"AOSS index already exists: {index_name}")
                return
        elif resp.status_code == 403:
            log(f"403 on attempt {attempt}/9 — retrying in 10s... ({resp.text})")
            time.sleep(10)
            continue

        sys.exit(f"\nERROR creating AOSS index: {resp.status_code} {resp.text}")


# ── 6. Bedrock Knowledge Base ─────────────────────────────────────────────────

def create_bedrock_kb(
    client, kb_name: str, role_arn: str,
    collection_arn: str, index_name: str, region: str,
) -> str:
    try:
        resp = client.create_knowledge_base(
            name=kb_name,
            roleArn=role_arn,
            knowledgeBaseConfiguration={
                "type": "VECTOR",
                "vectorKnowledgeBaseConfiguration": {
                    "embeddingModelArn": (
                        f"arn:aws:bedrock:{region}::foundation-model/{EMBED_MODEL_ID}"
                    ),
                },
            },
            storageConfiguration={
                "type": "OPENSEARCH_SERVERLESS",
                "opensearchServerlessConfiguration": {
                    "collectionArn": collection_arn,
                    "vectorIndexName": index_name,
                    "fieldMapping": {
                        "vectorField":   VECTOR_FIELD,
                        "textField":     TEXT_FIELD,
                        "metadataField": METADATA_FIELD,
                    },
                },
            },
            tags={"sentinel:managed": "true"},
        )
        kb_id = resp["knowledgeBase"]["knowledgeBaseId"]
        log(f"Created Bedrock KB: {kb_name} (id={kb_id})")
        return kb_id
    except client.exceptions.ConflictException:
        return _find_kb_by_name(client, kb_name)


def _find_kb_by_name(client, kb_name: str) -> str:
    paginator = client.get_paginator("list_knowledge_bases")
    for page in paginator.paginate():
        for kb in page["knowledgeBaseSummaries"]:
            if kb["name"] == kb_name:
                log(f"Bedrock KB already exists: {kb_name}")
                return kb["knowledgeBaseId"]
    sys.exit(f"\nERROR: KB '{kb_name}' conflict on create but not found in list.")


# ── 7. S3 data source ─────────────────────────────────────────────────────────

def create_bedrock_data_source(
    client, kb_id: str, ds_name: str, bucket_name: str, s3_prefix: str
) -> str:
    """
    Attach an S3 data source to the KB.

    Chunking strategy: NONE — our ingest() method pre-chunks documents
    (one file per chunk, one .metadata.json sidecar per chunk).  Bedrock
    will treat each S3 object as exactly one chunk and load its metadata
    from the sidecar. Re-chunking would corrupt the chunk boundaries we
    set deliberately (e.g. one page per chunk for PDFs).
    """
    try:
        resp = client.create_data_source(
            knowledgeBaseId=kb_id,
            name=ds_name,
            dataSourceConfiguration={
                "type": "S3",
                "s3Configuration": {
                    "bucketArn": f"arn:aws:s3:::{bucket_name}",
                    "inclusionPrefixes": [s3_prefix],
                },
            },
            vectorIngestionConfiguration={
                "chunkingConfiguration": {"chunkingStrategy": "NONE"},
            },
        )
        ds_id = resp["dataSource"]["dataSourceId"]
        log(f"Created S3 data source: {ds_name} (id={ds_id})")
        return ds_id
    except client.exceptions.ConflictException:
        # Data source with this name already exists — look it up.
        for ds in client.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]:
            if ds["name"] == ds_name:
                log(f"Data source already exists: {ds_name}")
                return ds["dataSourceId"]
        sys.exit(f"\nERROR: Data source '{ds_name}' conflict but not found in list.")


def delete_bedrock_kb(client, kb_name: str) -> None:
    paginator = client.get_paginator("list_knowledge_bases")
    kb_id = None
    for page in paginator.paginate():
        for kb in page["knowledgeBaseSummaries"]:
            if kb["name"] == kb_name:
                kb_id = kb["knowledgeBaseId"]
                break

    if not kb_id:
        log(f"Bedrock KB not found (skipping): {kb_name}")
        return

    for ds in client.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"]:
        client.delete_data_source(knowledgeBaseId=kb_id, dataSourceId=ds["dataSourceId"])
        log(f"Deleted data source: {ds['dataSourceId']}")

    client.delete_knowledge_base(knowledgeBaseId=kb_id)
    log(f"Deleted Bedrock KB: {kb_name}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Provision (or destroy) Sentinel AWS infrastructure.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--stack",       default="sentinel",   help="Name prefix for all AWS resources")
    p.add_argument("--region",      default="us-east-1",  help="AWS region")
    p.add_argument("--s3-prefix",   default="documents/", help="S3 key prefix for KB documents")
    p.add_argument("--start-from",  type=int, default=1,  help="Skip to this step (1-7)")
    p.add_argument("--destroy",     action="store_true",  help="Tear down all resources")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    stack     = args.stack
    region    = args.region
    s3_prefix = args.s3_prefix.rstrip("/") + "/"

    # Derive all resource names from the stack prefix.
    ddb_table       = f"{stack}-identity"
    bucket_name     = f"{stack}-kb-docs"
    role_name       = f"{stack}-bedrock-role"
    collection_name = f"{stack}-kb"
    index_name      = f"{stack}-index"
    kb_name         = f"{stack}-kb"
    ds_name         = f"{stack}-s3-source"

    session     = boto3.Session(region_name=region)
    caller      = session.client("sts").get_caller_identity()
    account_id  = caller["Account"]
    caller_arn  = caller["Arn"]

    ddb     = session.client("dynamodb")
    s3      = session.client("s3")
    iam     = session.client("iam")
    aoss    = session.client("opensearchserverless")
    bedrock = session.client("bedrock-agent")

    # ── Destroy path ──────────────────────────────────────────────────────────
    if args.destroy:
        print(f"\nDestroying Sentinel stack '{stack}' in {region}...\n")
        print("1/5  Bedrock KB")
        delete_bedrock_kb(bedrock, kb_name)
        print("2/5  OpenSearch Serverless")
        delete_aoss_collection(aoss, collection_name)
        print("3/5  IAM role")
        delete_iam_role(iam, role_name)
        print("4/5  S3 bucket")
        delete_s3_bucket(s3, bucket_name)
        print("5/5  DynamoDB table")
        delete_ddb_table(ddb, ddb_table)
        print("\nDone.")
        return

    # ── Create path ───────────────────────────────────────────────────────────
    start = args.start_from
    print(f"\nProvisioning Sentinel stack '{stack}' in {region} (account {account_id})...\n")

    if start <= 1:
        print("1/7  DynamoDB identity table")
        create_ddb_table(ddb, ddb_table)

    if start <= 2:
        print("2/7  S3 document bucket")
        create_s3_bucket(s3, bucket_name, region)

    if start <= 3:
        print("3/7  IAM role")
        role_arn = create_iam_role(iam, role_name, bucket_name, region, account_id)
        wait_dots(15, "for IAM role to propagate")
    else:
        role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]

    if start <= 4:
        print("4/7  OpenSearch Serverless collection")
        collection_id, collection_endpoint = create_aoss_collection(
            aoss, collection_name, role_arn, region, account_id, caller_arn
        )
    else:
        resp = aoss.batch_get_collection(names=[collection_name])
        col = resp["collectionDetails"][0]
        collection_id, collection_endpoint = col["id"], col["collectionEndpoint"]

    collection_arn = f"arn:aws:aoss:{region}:{account_id}:collection/{collection_id}"

    if start <= 5:
        print("5/7  AOSS vector index")
        create_aoss_index(collection_endpoint, index_name, region, session)

    if start <= 6:
        print("6/7  Bedrock Knowledge Base")
        wait_dots(20, "for AOSS index to propagate")
        kb_id = create_bedrock_kb(bedrock, kb_name, role_arn, collection_arn, index_name, region)

    else:
        kb_id = _find_kb_by_name(bedrock, kb_name)

    if start <= 7:
        print("7/7  S3 data source")
        ds_id = create_bedrock_data_source(bedrock, kb_id, ds_name, bucket_name, s3_prefix)
    else:
        ds_id = bedrock.list_data_sources(knowledgeBaseId=kb_id)["dataSourceSummaries"][0]["dataSourceId"]

    # ── Output ────────────────────────────────────────────────────────────────
    rerank_arn = f"arn:aws:bedrock:{region}::foundation-model/amazon.rerank-v1:0"
    print(f"""
{"━" * 60}
 Sentinel AWS infrastructure ready.
 Add these env vars to your .mcp.json:
{"━" * 60}

  SENTINEL_IDENTITY_STORE   = dynamodb
  SENTINEL_KNOWLEDGE_STORE  = bedrock

  AWS_REGION                = {region}

  DDB_TABLE_NAME            = {ddb_table}

  BEDROCK_KB_ID             = {kb_id}
  BEDROCK_S3_BUCKET         = {bucket_name}
  BEDROCK_S3_PREFIX         = {s3_prefix}
  BEDROCK_DS_ID             = {ds_id}

  BEDROCK_SEARCH_TYPE       = HYBRID
  BEDROCK_RERANKING         = false
  BEDROCK_RERANK_MODEL_ARN  = {rerank_arn}
  BEDROCK_RERANK_OVERSAMPLE = 3

{"━" * 60}

 To seed the DynamoDB identity table run:
   python scripts/seed_ddb.py --table {ddb_table} --region {region}

 To trigger the first KB ingestion sync run:
   aws bedrock-agent start-ingestion-job \\
     --knowledge-base-id {kb_id} \\
     --data-source-id {ds_id} \\
     --region {region}
""")


if __name__ == "__main__":
    main()
