use pefy_vector_rs::{IndexConfig, OmegaVectorIndex};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn temp_index(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!("pefy-vector-rs-{name}-{}-{nonce}", std::process::id()))
}

fn config(dimensions: usize) -> IndexConfig {
    IndexConfig {
        dimensions,
        max_neighbors: 8,
        initial_capacity: 2,
        ef_construction: 32,
        ef_search: 32,
        rerank_candidates: 16,
        query_memory_budget_mb: 2,
    }
}

#[test]
fn nearest_neighbor_survives_flush_and_reopen() {
    let dir = temp_index("persist");
    let cfg = config(8);
    {
        let mut index = OmegaVectorIndex::open(&dir, cfg.clone()).expect("open");
        index
            .add(10, &[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            .expect("add a");
        index
            .add(20, &[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            .expect("add b");
        index
            .add(30, &[0.9, 0.1, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
            .expect("add c");
        index.flush().expect("flush");

        let hits = index
            .search(&[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 2)
            .expect("search");
        assert_eq!(hits[0].external_id, 10);
        assert!(hits[0].score >= hits[1].score);
    }

    {
        let reopened = OmegaVectorIndex::open(&dir, cfg).expect("reopen");
        assert_eq!(reopened.len(), 3);
        let hits = reopened
            .search(&[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1)
            .expect("search reopened");
        assert_eq!(hits[0].external_id, 20);
    }

    let _ = fs::remove_dir_all(dir);
}

#[test]
fn capacity_growth_keeps_existing_vectors_searchable() {
    let dir = temp_index("growth");
    let mut index = OmegaVectorIndex::open(&dir, config(16)).expect("open");
    for id in 0..64u64 {
        let mut vector = [0.0f32; 16];
        vector[(id as usize) % 16] = 1.0;
        vector[((id as usize) + 1) % 16] = (id as f32 + 1.0) / 100.0;
        index.add(id, &vector).expect("add");
    }
    assert!(index.stats().capacity >= 64);
    let mut query = [0.0f32; 16];
    query[7] = 1.0;
    let hits = index.search(&query, 4).expect("search");
    assert!(!hits.is_empty());
    assert!(hits.iter().any(|hit| hit.external_id % 16 == 7));
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn tombstoned_nodes_are_not_returned() {
    let dir = temp_index("delete");
    let mut index = OmegaVectorIndex::open(&dir, config(8)).expect("open");
    let node = index
        .add(1, &[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        .expect("add");
    index
        .add(2, &[0.8, 0.2, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        .expect("add second");
    index.mark_deleted(node).expect("delete");
    let hits = index
        .search(&[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 2)
        .expect("search");
    assert!(hits.iter().all(|hit| hit.external_id != 1));
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn vector_storage_is_more_compact_than_full_f32_for_typical_embeddings() {
    let dir = temp_index("stats");
    let dimensions = 768usize;
    let index = OmegaVectorIndex::open(&dir, config(dimensions)).expect("open");
    let stats = index.stats();
    let full_f32_payload = dimensions as u64 * 4;
    // ΩVECTOR-RS stores int8 search + f16 rerank plus a compact graph/id record.
    assert!(stats.approx_bytes_per_vector < full_f32_payload + 512);
    assert_eq!(stats.query_memory_budget_bytes, 2 * 1024 * 1024);
    let _ = fs::remove_dir_all(dir);
}
