# MƐTAFLOW Ω — ΩEDGE Integration

MƐTAFLOW Ω consumes the PEFY ΩEDGE FABRIC standard governed by GARKAEL Ω.

## Required profiles

- EDGE-C for agentic/AI streaming traffic
- EDGE-A when exposed as a public web/API service
- EDGE-F for local development
- EDGE-E for sovereign/offline installations when applicable

## Runtime requirements

- Application processes do not bind public management ports directly in production.
- NGINX is the default classic reverse-proxy option.
- Envoy is preferred where advanced streaming, gRPC, dynamic routing, circuit breaking or service-to-service policy is required.
- Kubernetes deployments use Gateway API with an approved implementation such as NGINX Gateway Fabric or Envoy Gateway. New community ingress-nginx deployments are prohibited.
- WebSocket and SSE paths must be explicitly tested and use workload-specific timeout budgets.
- Client-supplied PEFY identity/AAL/session headers are never trusted. Trusted identity must be re-established through the GARKAEL/ΩTRUST boundary.
- Administrative, sandbox, tool-execution, memory and orchestration endpoints are private by default.
- Provider egress is policy-controlled and observable without logging secrets or sensitive prompts by default.
- WAF/WAAP is risk-based and must not break valid long-running agent/streaming requests.
- Rate limits distinguish interactive user traffic, agent sub-task traffic, provider callbacks and privileged control-plane traffic.
- Production promotion requires ΩEDGE qualification evidence and full council/councillor review.

## Deployment patterns

### VM / bare metal / Compose

Internet -> GARKAEL policy -> NGINX or HAProxy -> optional Envoy service gateway -> MƐTAFLOW services

### Kubernetes

Internet/load balancer -> GARKAEL controls -> Gateway API -> NGINX Gateway Fabric or Envoy Gateway -> private MƐTAFLOW Services

### Sovereign/offline

Private client -> GARKAEL -> NGINX/HAProxy/Envoy -> MƐTAFLOW, using local/offline PKI and local observability.

This integration is an engineering control contract. It does not claim production qualification by itself.
