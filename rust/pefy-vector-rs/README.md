# ΩVECTOR-RS

**PEFY ΩVECTOR-RS** is the low-memory semantic vector index for MƐTAFLOW Ω / MƐTAPEFYON Ω.

Status: **CONTROLLED ENGINEERING BASELINE / NOT PRODUCTION-QUALIFIED**.

## Design objective

Reduce resident memory without turning vector retrieval into an external always-on heavyweight database or duplicating authoritative metadata.

The index therefore stores only:

- normalized **int8** vectors for approximate graph search;
- normalized **f16** vectors for reranking a small candidate set;
- fixed-width **u32** graph links;
- **u64** external record IDs;
- one-byte tombstones;
- a small binary metadata header.

Tenant/project metadata, evidence lineage, source text, payloads and authoritative records remain in OMNIA/RMS/Core Store and are hydrated only after retrieval selects a small ID set.

## Storage layout

```text
<index>/
├── meta.bin          # fixed 64-byte versioned header
├── vectors.q8        # normalized int8 search representation, mmap
├── vectors.f16       # normalized f16 rerank representation, mmap
├── graph.u32         # compact fixed-width navigable graph, mmap
├── ids.u64           # external durable-store IDs, mmap
└── tombstones.u8     # logical deletion flags, mmap
```

All large files are memory-mapped without explicit full preloading. Mapping a file reserves virtual address space but does not require every page to remain resident in RAM. Production RSS is therefore also constrained at the process/container/systemd/cgroup layer.

## Retrieval path

1. Normalize the query once.
2. Quantize the query to int8.
3. Traverse the compact graph using int8 dot products.
4. Keep a bounded candidate heap controlled by `query_memory_budget_mb`.
5. Read f16 vectors only for the small rerank set.
6. Return `u64` IDs and scores.
7. Resolve compact metadata/evidence handles from the governed durable store.
8. Hydrate larger source payloads only when the mission actually needs them.

## Why this reduces RAM

A conventional dense vector represented as `f32` consumes 4 bytes per component before graph and application-object overhead. ΩVECTOR-RS uses 1 byte/component for the broad search path. The f16 representation is disk/mmap-backed and touched only for reranking. Thus the hot search representation is theoretically 75% smaller than a full f32 vector payload, before eliminating Python object/list overhead.

This follows the same proven memory principle used by modern vector engines: compact quantized candidates in memory, original vectors on disk/cold storage, then exact reranking. Qdrant documents an equivalent f32→int8 scalar-quantization reduction of roughly 4× for the quantized representation.

Actual RSS reduction is a release metric, not assumed from the format. Qualification must measure RSS, page cache behavior, page faults, latency, recall@k and throughput on representative corpora.

## Graph model

v0.1 uses a compact bounded navigable graph with a fixed maximum neighbor count. It intentionally avoids `Vec<Vec<_>>`, string keys, duplicated payloads and other heap-heavy per-node objects.

The graph is not represented as a claim of full HNSW equivalence. Search quality must be benchmarked against exact top-k and against approved HNSW/DiskANN/Qdrant reference configurations before production promotion.

## Durability

Adds may be batched. `flush()` writes all mmap changes first, then advances the versioned metadata count/generation. If a process dies before metadata advances, uncommitted tail records are ignored on reopen rather than being treated as durable.

## Safety and sovereignty

- no client text or secrets are written into the vector index;
- no global cross-client vector namespace is required;
- recommended deployment is one governed index namespace per isolation boundary;
- metadata hydration must re-check tenant/project authorization;
- no index result grants authorization by itself;
- the vector index is non-authoritative and replaceable;
- all production changes remain evidence-gated and council/councillor-reviewed.

## Toolchain

Pinned engineering baseline: **Rust 1.97.1**.

## Build

```bash
cargo +1.97.1 build --release --manifest-path rust/pefy-vector-rs/Cargo.toml
```

The release build emits an `rlib` and a `cdylib`; MƐTAFLOW's Python adapter uses the narrow C ABI via `ctypes`, avoiding a second resident copy of the vector corpus.
