# PEFY RAGFlow Ω Adapter — controlled admission profile

**Status:** Engineering integration candidate — not production-approved  
**Reference target:** RAGFlow `v0.27.1`  
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
RAGFlow v0.27.1 (retrieval / ingestion)
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

## 3. Phase-1 admitted surface

Allowed initially:

- controlled document ingestion into pre-created datasets;
- `/api/v1/retrieval` through the PEFY adapter;
- private/internal API access only;
- approved LLM/embedding providers through separately governed credentials;
- observability required for retrieval latency, errors and data-scope violations.

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

## 4. Mandatory security profile

1. Pin an exact release and container digest; never use a floating or nightly image in production.
2. Generate and retain SBOMs for the admitted build.
3. Run SCA, container, secret and source scans before promotion.
4. Place RAGFlow and its backing services on private networks with no unnecessary ingress.
5. Put the API behind a PEFY-controlled TLS reverse proxy / gateway.
6. Store API keys and model/provider credentials in a secret manager; inject them at runtime.
7. Run with least privilege, non-root where supported, read-only filesystem where practical, dropped Linux capabilities and resource limits.
8. Do not mount the host Docker socket.
9. Preserve the RAGFlow sandbox service with network disabled unless an approved use case requires narrowly scoped egress.
10. Apply egress allowlists to model providers, object stores and update sources.
11. Back up datasets, metadata stores and configuration separately; test restore.
12. Record admission version, image digest, SBOM digest and security evidence in the PEFY evidence fabric.
13. Fail closed on missing tenant context, missing secret, unknown dataset mapping, malformed responses or authorization mismatch.
14. Re-run the security gate before every upstream upgrade.

## 5. Data and authorization contract

The model, end user and RAGFlow service never decide which datasets are authorized.

The local PEFY resolver maps `(tenant_id, project_id)` to a fixed set of dataset identifiers before the request is sent. For a project-scoped mission, tenant-wide fallback is disabled by default.

On response, every returned chunk must contain a dataset identifier already present in that locally authorized set. Any mismatch blocks the whole retrieval operation. Only selected fields are hydrated; vectors and arbitrary metadata are discarded.

Retrieved content is labelled `retrieved_unverified`. Retrieval relevance is not evidence of truth, authorization or record authority.

## 6. Secret handling

The adapter references the API credential by environment-variable name (`RAGFLOW_API_KEY` by default). Secret values are not stored in repository configuration, mission packets, logs or vector files.

Production should replace plain environment provisioning with the approved secret-injection mechanism while retaining the same application contract.

## 7. Deployment profiles

### EDGE / resource-constrained

Prefer ΩVECTOR-RS. Do not deploy the full RAGFlow dependency stack on low-memory nodes.

### STANDARD private deployment

Run RAGFlow centrally as an internal retrieval service. Edge workloads call it only when policy and connectivity allow; otherwise ΩVECTOR-RS remains available locally.

### SOVEREIGN / restricted

Use a fully isolated RAGFlow instance per approved security boundary or do not route restricted content to RAGFlow. ΩVECTOR-RS remains the default sovereign path until RAGFlow passes representative isolation, supply-chain, resilience and penetration-testing gates.

## 8. Qualification gates before production

- unit tests for dataset authorization and bounded hydration;
- integration test against the pinned RAGFlow version;
- tenant/project adversarial isolation tests;
- API fuzz / malformed-response tests;
- prompt-injection and document-poisoning tests;
- parser/decompression/archive-bomb tests;
- SSRF and egress-control tests;
- sandbox escape review;
- authentication and session tests if UI access is enabled;
- SBOM + vulnerability scan with approved exception process;
- backup/restore and disaster-recovery test;
- load test for ingestion and retrieval;
- latency/error-budget measurement;
- upstream-delta/IP/license review;
- PEA + counsellor + council release review.

Until these gates pass, the adapter remains an engineering integration candidate.

## 9. Upgrade/fork policy

Use upstream RAGFlow whenever the pinned upstream release satisfies the PEFY admission gates. Maintain a PEFY fork only for necessary security, interoperability or sovereign-control patches, and keep the delta minimal and traceable so upstream fixes can be rebased quickly.

Apache-2.0 obligations and notices must be preserved for upstream-derived code. PEFY-owned adapter, policy, governance, evidence, orchestration and ΩVECTOR-RS layers remain separate proprietary assets subject to the PEFY IP policy.

## 10. Promotion sequence

1. Adapter unit tests.
2. Pinned RAGFlow 0.27.1 lab deployment.
3. Retrieval-only integration qualification.
4. Controlled DeepDoc/document-ingestion qualification.
5. Knowledge Compilation qualification after retrieval semantics are verified.
6. Optional agent/tool features only through a separate threat model and admission decision.
7. Representative pilot.
8. Production release gate.
