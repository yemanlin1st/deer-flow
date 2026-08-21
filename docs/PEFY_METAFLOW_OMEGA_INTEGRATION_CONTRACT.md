# MƐTAFLOW Ω™ integration contract

**Schema family:** `pefy.metaflow.omega.*.v1`  
**Purpose:** connect MƐTAFLOW Ω to MƐTAPEFYON Ω, OMNIA Skillspector, PEA assurance, memory/evidence services, specialist agencies and replaceable execution runtimes.

## 1. Architectural boundary

MƐTAFLOW Ω owns mission policy and orchestration semantics. Runtime frameworks execute bounded work through adapters.

```text
PEFY experience / API / cockpit
          |
mission intake + identity + release class
          |
MƐTAFLOW Ω policy and orchestration
          |
PEA + 5 counsellors + 13 councils
          |
OMNIA capability admission / Skillspector
          |
+---------+----------+-----------+----------+
|                    |                      |
Memory/Evidence   Runtime adapters      Specialist agencies
|                 DeerFlow/LangGraph    DRAMACLAW/etc.
|                    |                      |
+--------------------+----------------------+
          |
controlled artifacts + evidence + events
```

## 2. Mandatory mission envelope

Every mission should carry at minimum:

```json
{
  "schema": "pefy.metaflow.omega.mission.v1",
  "mission_id": "unique-id",
  "tenant_id": "tenant-or-owner-scope",
  "project_id": "optional-project-scope",
  "objective": "human-readable outcome",
  "release_class": "PRIVATE_WORKING",
  "domains": [],
  "confidential": false,
  "client_data": false,
  "personal_data": false,
  "requested_actions": [],
  "requires_current_facts": false,
  "requires_external_tools": false,
  "owner_approved_consequential_actions": false
}
```

Secrets must be referenced through scoped secret handles, never copied into the mission envelope.

## 3. Canonical lifecycle events

| Event | Producer | Primary consumers | Minimum purpose |
|---|---|---|---|
| `mission.intake` | Experience / API | MƐTAFLOW, evidence | Register request and scope |
| `mission.routed` | MƐTAFLOW | PEA, cockpit, evidence | Record mode, gates and reasons |
| `capability.admitted` | OMNIA Skillspector | MƐTAFLOW, runtime | Record approved tools/skills/adapters |
| `council.challenge.completed` | PEA/council mesh | MƐTAFLOW, evidence | Prove all challenge functions were invoked |
| `task.dispatched` | MƐTAFLOW | runtime/cockpit | Trace bounded execution |
| `artifact.produced` | runtime/agency | MƐTAFLOW, evidence | Register candidate output |
| `evidence.verified` | evidence/QA | MƐTAFLOW, release gate | Record verification state |
| `deep_loop.completed` | Deep Loop | MƐTAFLOW, QA | Record audit/fix/benchmark findings |
| `humanization.completed` | output hygiene | release gate | Record editorial cleanup without losing required provenance |
| `release.gated` | MƐTAFLOW/PEA | cockpit, archive | Record final release class and blocks |
| `mission.completed` | MƐTAFLOW | memory, cockpit, analytics | Close mission with outcome and reusable assets |
| `mission.rolled_back` | control plane | evidence, cockpit | Record rollback cause and restored state |

Events should be idempotent, timestamped, tenant-scoped and trace-correlated.

## 4. Council challenge contract

Every mission must contain results from all 18 challenge functions:

- 5 counsellors
- 13 specialist councils/agencies

Each result should expose:

```json
{
  "challenge_function": "Security & Governance",
  "status": "NO_MATERIAL_OBJECTION | CONDITIONAL | BLOCK | PENDING_ADAPTER",
  "depth": "compact | full | adversarial",
  "findings": [],
  "required_controls": [],
  "required_evidence": [],
  "escalation": null
}
```

`PENDING_ADAPTER` is allowed only in development/integration mode. It cannot satisfy a production release gate.

## 5. Capability admission contract

Before a tool, skill, MCP server, model provider or runtime is used, OMNIA/Skillspector should return an admission record with:

- capability ID and version
- source/provenance
- owner
- license state
- trust/security score
- allowed operations
- data classification ceiling
- network/file/secret permissions
- sandbox requirement
- rollback/removal path
- evidence reference

Unknown capabilities are denied by default.

## 6. Runtime adapter contract

A runtime adapter receives a bounded execution packet. It does not receive unrestricted account authority.

Required adapter behaviors:

- enforce blocked actions
- use scoped credentials
- support cancellation/timeouts
- return structured status
- expose tool calls and errors for evidence
- preserve tenant/project boundaries
- avoid hidden persistence outside approved stores
- support deterministic or replayable checkpoints where feasible

Suggested adapter identifiers:

- `deerflow-2x`
- `langgraph-local`
- `pefy-local-agent-runtime`
- `openmultiagent-adapter`
- future replaceable runtimes

## 7. Memory contract

Memory retrieval is purpose-limited and tenant/project scoped.

Memory response fields should include:

- memory ID
- tenant/project scope
- classification
- source type
- relevance score
- validation state
- last-reviewed timestamp
- expiry/retention rule when applicable

Restricted memories must not be copied into public artifacts or cross-tenant contexts.

## 8. Evidence contract

Evidence records should be immutable or tamper-evident for consequential actions and production qualification.

Minimum fields:

- evidence ID
- mission ID
- event type
- timestamp
- actor/agent/service identity
- source lineage
- content digest
- decision or claim supported
- approval state
- retention class

## 9. Humanization contract

The output-hygiene layer may clean style and formatting but must preserve evidence semantics.

Allowed:

- remove generic chatbot residue
- remove zero-width artifacts
- remove redundant scaffolding
- normalize whitespace
- adapt tone to audience
- remove accidental model/provider labels not required by the deliverable

Forbidden:

- deleting mandatory open-source attribution
- deleting required AI-use disclosure
- deleting citations needed for claims
- fabricating human authorship
- altering quoted evidence without marking the change
- suppressing audit/provenance records that policy requires

## 10. Release gate

Production release is blocked unless:

- all 18 challenge functions completed with no unresolved `BLOCK`
- no `PENDING_ADAPTER` challenge remains
- required evidence exists
- security/IP/confidentiality gates pass
- consequential actions carry explicit authority
- output hygiene passes
- target release class is valid
- rollback exists for mutable production changes

## 11. Integration with specialized PEFY agencies

MƐTAFLOW is the meta-orchestrator, not a replacement for specialist engines.

A mission route may delegate to:

- DRAMACLAW Ω STUDIO for video/media production
- PEFY DevSecOps/Cyber agents for engineering/security missions
- Data & Intelligence Agency for analytics
- Finance & Value Agency for financial modeling
- Legal & IP Agency for legal/IP analysis with professional-review gates where required
- Language & Communications Agency for multilingual/editorial work
- other approved PEFY agencies registered by OMNIA

All delegated work returns to the same evidence, Deep Loop, humanization and release gates.
