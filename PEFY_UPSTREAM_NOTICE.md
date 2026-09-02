# PEFY upstream and intellectual-property boundary notice

## Purpose

This branch introduces PEFY integration overlays around existing open-source runtimes. It does not erase, replace or reassign upstream copyright, license, patent or attribution obligations.

## DeerFlow upstream

The existing DeerFlow codebase is distributed under the MIT License. The original copyright and permission notice must remain with copies or substantial portions of upstream software.

PEFY modifications may be owned by their respective author/rights holder to the extent permitted by applicable law, contributor agreements and the upstream license, but the presence of PEFY code does not convert upstream DeerFlow code into exclusively proprietary PEFY software.

## RAGFlow upstream

RAGFlow is an external, replaceable subsystem distributed under the Apache License 2.0. The PEFY adapter in this repository communicates with RAGFlow through its API and does not copy RAGFlow source code into the PEFY adapter package.

If PEFY later distributes a modified RAGFlow fork or other derivative upstream code, the applicable Apache-2.0 requirements must be preserved, including the license copy, relevant notices/attributions and prominent modification notices where required. Upstream trademarks are not transferred to PEFY by the software license.

The engineering qualification target is separately pinned in `config/ragflow_upstream.lock.json`. That lock records provenance and qualification state; it does not alter upstream license terms.

## PEFY-owned control layer

PEFY-specific value should be isolated into clearly identifiable modules and repositories, including where applicable:

- PEA orchestration logic
- counsellor and council governance rules
- PEFY business/process policy
- private prompts and evaluation assets
- proprietary skills and agent definitions
- private connectors and adapters
- client-specific workflows
- PEFY memory and evidence contracts
- ΩMEMORY / ΩVECTOR-RS implementation
- commercial configuration
- brand assets
- confidential benchmarks

For commercial distribution, the recommended architecture is a private PEFY control-plane repository/package that consumes DeerFlow, RAGFlow or another runtime through controlled adapter boundaries.

## Public-repository rule

Do not commit any of the following to a public upstream-compatible repository:

- credentials, API keys, signing material or secrets
- confidential PEFY prompts or decision rules
- client names/data unless explicitly authorized for public release
- private memory exports
- restricted evidence
- unreleased commercial pricing or strategy
- personal data not required for the public source tree

## Provenance and humanization

Humanization and output hygiene may remove accidental chatbot wording, hidden formatting artifacts and irrelevant provider labels from deliverables. They must not remove:

- mandatory copyright notices
- open-source license notices
- legally required disclosures
- citations or evidence required to support claims
- contractual provenance obligations
- security/audit evidence that must be retained

## Status

This notice is an engineering governance baseline, not a substitute for professional legal advice, trademark clearance, contributor agreements or formal IP registration.
