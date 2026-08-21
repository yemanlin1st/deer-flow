use pefy_vector_compact_rs::{IndexConfig, OmegaCompactVectorIndex};
use std::fs;
use std::path::PathBuf;
use std::time::{SystemTime, UNIX_EPOCH};

fn temp_index(name: &str) -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    std::env::temp_dir().join(format!(
        "pefy-vector-compact-rs-{name}-{}-{nonce}",
        std::process::id()
    ))
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
        let mut index = OmegaCompactVectorIndex::open(&dir, cfg.clone()).expect("open");
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
    }

    let reopened = OmegaCompactVectorIndex::open(&dir, cfg).expect("reopen");
    assert_eq!(reopened.len(), 3);
    assert_eq!(
        reopened
            .search(&[0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0], 1)
            .expect("search reopened")[0]
            .external_id,
        20
    );
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn compact_engine_has_no_f16_payload_and_is_small_at_768_dimensions() {
    let dir = temp_index("compact");
    let dimensions = 768usize;
    let mut index = OmegaCompactVectorIndex::open(&dir, config(dimensions)).expect("open");
    let mut vector = vec![0.0f32; dimensions];
    vector[0] = 1.0;
    index.add(1, &vector).expect("add");
    index.flush().expect("flush");

    let stats = index.stats();
    let full_f32_payload = dimensions as u64 * 4;
    assert!(stats.approx_bytes_per_vector < full_f32_payload / 2);
    assert!(!dir.join("vectors.f16").exists());
    assert_eq!(
        fs::metadata(dir.join("vectors.q8"))
            .expect("q8 metadata")
            .len(),
        2 * 768
    );
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn capacity_growth_preserves_committed_state() {
    let dir = temp_index("growth");
    let cfg = config(16);
    {
        let mut index = OmegaCompactVectorIndex::open(&dir, cfg.clone()).expect("open");
        for id in 0..64u64 {
            let mut vector = [0.0f32; 16];
            vector[(id as usize) % 16] = 1.0;
            index.add(id, &vector).expect("add");
        }
        assert_eq!(index.len(), 64);
        assert!(index.stats().capacity >= 64);
        index.flush().expect("flush");
    }
    let reopened = OmegaCompactVectorIndex::open(&dir, cfg).expect("reopen");
    assert_eq!(reopened.len(), 64);
    assert!(reopened.stats().generation >= 1);
    let _ = fs::remove_dir_all(dir);
}

#[test]
fn tombstoned_nodes_are_not_returned() {
    let dir = temp_index("delete");
    let mut index = OmegaCompactVectorIndex::open(&dir, config(8)).expect("open");
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
