# PEFY RAGFlow Ω Adapter — controlled admission profile

**Status:** Engineering integration candidate — not production-approved  
**Reference target:** RAGFlow `v0.27.1` / commit `b9df87c4c75a5b0d35c90d15329fc0f6f91cb73e`  
**PEFY role:** replaceable document-ingestion / retrieval subsystem behind MƐTAFLOW Ω  
**Sovereign retrieval role:** remains ΩVECTOR-RS / ΩMEMORY

## 1. Architecture decision

RAGFlow is admitted only as a subordinate capability. It does not own PEFY mission policy, tenant authorization, project authorization, release policy, evidence policy, or sovereign memory semantics.

```text
PEFY experience / API / cockpit
          |
MƐTAFLOW Ω mission + policy + councils
          |
local tenant/project authorization
          |
PefyRagflowMemoryAdapter
          |
internal RAGFlow gateway
          |
RAGFlow v0.27.1 (retrieval / controlled ingestion)
          |
returned chunks
          |
post-retrieval dataset authorization check
          |
bounded, selected fields only
          |
MƐTAFLOW Ω memory budget + evidence + release gates

Parallel sovereign path:
MƐTAFLOW Ω -> ΩMEMORY / ΩVECTOR-RS
```

## 2. Why hybrid rather than replacement

RAGFlow provides mature document parsing, hybrid retrieval, connectors, knowledge-processing workflows and an API surface that would be expensive to reproduce immediately. PEFY already owns the stronger governance boundary: mission classification, tenant/project context, bounded memory projection, evidence, challenge functions, release gating and ΩVECTOR-RS.

The optimal pattern is therefore **adopt selectively + isolate + wrap + continuously benchmark**, while preserving a clean exit path.

## 3. Upstream qualification lock

The admitted engineering target is recorded in `config/ragflow_upstream.lock.json`.

Current lock:

- upstream: `infiniflow/ragflow`;
- release: `v0.27.1`;
- release commit: `b9df87c4c75a5b0d35c90d15329fc0f6f91cb73e`;
- commit signature: verified at qualification intake;
- license: Apache-2.0;
- production approval: **false**;
- every upstream upgrade requires requalification.

A container digest is intentionally not claimed until the exact deployment image is selected and independently resolved. Production deployment remains blocked until that digest, SBOM and vulnerability evidence exist.

## 4. Phase-1 admitted surface

Allowed initially:

- `/api/v1/retrieval` through the PEFY adapter;
- controlled document ingestion into pre-created datasets only after the selected parser/model path passes its compatibility gate;
- private/internal API access only;
- approved LLM/embedding providers through separately governed credentials;
- observability for retrieval latency, errors and data-scope violations.

Disabled until separately qualified:

- public registration;
- arbitrary user-selected dataset IDs;
- direct public exposure of the RAGFlow API/UI;
- agent code execution;
- unrestricted browser/web-search tools;
- arbitrary MCP/tool execution;
- host Docker socket access;
- cross-tenant shared datasets without an explicit policy decision;
- production self-modification;
- automatic promotion of retrieved content to authoritative records.

## 5. Known upstream compatibility hold

RAGFlow issue `infiniflow/ragflow#19004` reports a v0.27.1 failure path affecting local Qwen/GLM chat calls and keyword extraction. Upstream PR `#19054` proposes the fix but is not part of the locked v0.27.1 commit.

PEFY policy until this is resolved and requalified:

- retrieval against already qualified datasets may continue in engineering/lab scope;
- **local Qwen/GLM-dependent ingestion or auto-keyword extraction is blocked** on the locked upstream target;
- the hold can be removed only after either an accepted upstream release contains the fix or a controlled PEFY backport passes regression/security tests;
- no unreviewed cherry-pick is promoted to production.

This hold is a compatibility control, not a claim that every v0.27.1 deployment is unusable.

## 6. Mandatory security profile

1. Pin an exact release, commit and deployment container digest; never use a floating or nightly image in production.
2. Generate and retain SBOMs for the admitted build/image.
3. Run SCA, container, secret and source scans before promotion.
4. Place RAGFlow and its backing services on private networks with no unnecessary ingress.
5. Put the API behind a PEFY-controlled TLS reverse proxy / gateway.
6. Store API keys and model/provider credentials in a secret manager; inject them at runtime.
7. Run with least privilege, non-root where supported, read-only filesystem where practical, dropped Linux capabilities and resource limits.
8. Do not mount the host Docker socket.
9. Preserve the RAGFlow sandbox service with network disabled unless an approved use case requires narrowly scoped egress.
10. Apply egress allowlists to model providers, object stores and update sources.
11. Reject HTTP redirects from the adapter so a bearer token cannot be forwarded to another location.
12. Bound retrieval query length, dataset count, page size, top-k, timeout and response bytes.
13. Back up datasets, metadata stores and configuration separately; test restore.
14. Record admission version, commit, image digest, SBOM digest and security evidence in the PEFY evidence fabric.
15. Fail closed on missing tenant context, missing secret, unknown dataset mapping, malformed responses or authorization mismatch.
16. Re-run the security and compatibility gates before every upstream upgrade.

## 7. Data and authorization contract

The model, end user and RAGFlow service never decide which datasets are authorized.

The local PEFY resolver maps `(tenant_id, project_id)` to a fixed set of dataset identifiers before the request is sent. For a project-scoped mission, tenant-wide fallback is disabled by default.

On response, every returned chunk must contain a dataset identifier already present in that locally authorized set. Any mismatch blocks the whole retrieval operation. Only selected fields are hydrated; vectors and arbitrary metadata are discarded.

Retrieved content is labelled `retrieved_unverified`. Retrieval relevance is not evidence of truth, authorization or record authority.

## 8. Transport contract

The v0.27.1 official retrieval example confirms the Phase-1 request surface used by the adapter: `dataset_ids`, `question`, `page`, `page_size`, `similarity_threshold`, `vector_similarity_weight`, `top_k` and `keyword`.

PEFY additionally enforces:

- HTTPS endpoint only;
- no embedded URL credentials, query or fragment;
- redirects rejected;
- response bytes capped;
- query and authorized dataset set capped;
- upper bounds for `page_size`, `top_k` and timeout;
- non-finite similarity values neutralized before entering memory context;
- only selected response fields admitted into MƐTAFLOW Ω.

## 9. Secret handling

The adapter references the API credential by environment-variable name (`RAGFLOW_API_KEY` by default). Secret values are not stored in repository configuration, mission packets, logs or vector files.

Production should replace plain environment provisioning with the approved secret-injection mechanism while retaining the same application contract.

## 10. Deployment profiles

### EDGE / resource-constrained

Prefer ΩVECTOR-RS. Do not deploy the full RAGFlow dependency stack on low-memory nodes.

### STANDARD private deployment

Run RAGFlow centrally as an internal retrieval service. Edge workloads call it only when policy and connectivity allow; otherwise ΩVECTOR-RS remains available locally.

### SOVEREIGN / restricted

Use a fully isolated RAGFlow instance per approved security boundary or do not route restricted content to RAGFlow. ΩVECTOR-RS remains the default sovereign path until RAGFlow passes representative isolation, supply-chain, resilience and penetration-testing gates.

## 11. Qualification gates before production

- dedicated adapter unit/scope/provenance CI;
- integration test against the exact pinned RAGFlow release/commit;
- exact deployment image digest capture;
- tenant/project adversarial isolation tests;
- API fuzz / malformed-response tests;
- prompt-injection and document-poisoning tests;
- parser/decompression/archive-bomb tests;
- SSRF, redirect and egress-control tests;
- sandbox escape review;
- authentication and session tests if UI access is enabled;
- SBOM + vulnerability scan with approved exception process;
- backup/restore and disaster-recovery test;
- ingestion/retrieval load test;
- latency/error-budget measurement;
- upstream-delta/IP/license review;
- PEA + counsellor + council release review.

Until these gates pass, the adapter remains an engineering integration candidate.

## 12. Upgrade/fork policy

Use upstream RAGFlow whenever the pinned upstream release satisfies the PEFY admission gates. Maintain a PEFY fork only for necessary security, interoperability or sovereign-control patches, and keep the delta minimal and traceable so upstream fixes can be rebased quickly.

Apache-2.0 obligations and notices must be preserved for upstream-derived code. PEFY-owned adapter, policy, governance, evidence, orchestration and ΩVECTOR-RS layers remain separate proprietary assets subject to the PEFY IP policy.

## 13. Promotion sequence

1. Adapter unit / scope / provenance gate.
2. Pinned RAGFlow v0.27.1 lab deployment with exact image digest.
3. Retrieval-only live integration qualification.
4. Controlled document-ingestion qualification for approved parser/model combinations.
5. Knowledge Compilation qualification after retrieval semantics are verified.
6. Optional agent/tool features only through a separate threat model and admission decision.
7. Representative pilot.
8. Production release gate.
