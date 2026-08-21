# PEFY upstream and intellectual-property boundary notice

## Purpose

This branch introduces a PEFY integration overlay around an existing DeerFlow-derived repository. It does not erase, replace or reassign upstream copyright.

## DeerFlow upstream

The existing DeerFlow codebase is distributed under the MIT License. The original copyright and permission notice must remain with copies or substantial portions of upstream software.

PEFY modifications may be owned by their respective author/rights holder to the extent permitted by applicable law, contributor agreements and the upstream license, but the presence of PEFY code does not convert upstream DeerFlow code into exclusively proprietary PEFY software.

## PEFY-owned control layer

PEFY-specific value should be isolated into clearly identifiable modules and repositories, including where applicable:

- PEA orchestration logic
- counsellor and council governance rules
- PEFY business/process policy
- private prompts and evaluation assets
- proprietary skills and agent definitions
- private connectors
- client-specific workflows
- PEFY memory and evidence contracts
- commercial configuration
- brand assets
- confidential benchmarks

For commercial distribution, the recommended architecture is a private PEFY control-plane repository/package that consumes DeerFlow or another runtime through an adapter boundary.

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
