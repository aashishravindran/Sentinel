# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Sentinel is a Python MCP (Model Context Protocol) server implementing **Attribute-Based Access Control (ABAC)** as middleware for RAG pipelines. It supports two backend configurations: local (SQLite + ChromaDB) and AWS (DynamoDB + Bedrock Knowledge Bases with hybrid search and optional reranking). It enforces zero-trust access control by matching user tags to document tags before returning search results.

For detailed project structure, tech stack, and conventions, see `.claude/skills/project-structure.md`.

## Commands

```bash
# Install dependencies
uv sync

# Run the MCP server
python -m sentinel.main

# Run tests
uv run pytest

# Run a single test
uv run pytest tests/path/to/test_file.py::test_name
```

## Key Security Principles

- **Zero Trust / Fail-Closed:** No tags = access denied. Never assumes global access.
- **Stateless:** No user data cached between sessions.
- **OR Policy:** User must possess at least one tag matching the document's `access_tags`.

## Design Documents

Full design context lives in `Design/`:
- `Architecture.md.md` — system components, connector architecture, search pipeline diagrams
- `Design.md.md` — data models, security principles, connector contracts
- `Project Structure.md.md` — file layout with annotations
- `Tasklist.md.md` — phased implementation roadmap

## Session Log

### 2026-03-21
Added AWS backend support: DynamoDB identity connector, Bedrock Knowledge Bases connector with hybrid search (dense + BM25) and optional reranking, PDF ingestion via pypdf, and AWS infrastructure provisioning script. Updated architecture docs and added QUICKSTART.md with setup guides for both local and AWS configurations.
