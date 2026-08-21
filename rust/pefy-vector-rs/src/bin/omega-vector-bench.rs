use pefy_vector_rs::{IndexConfig, OmegaVectorIndex};
use std::cmp::Ordering;
use std::env;
use std::fs;
use std::path::PathBuf;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

#[derive(Clone, Copy, Debug)]
struct BenchConfig {
    vectors: u32,
    dimensions: usize,
    queries: usize,
    k: usize,
    max_neighbors: usize,
    ef_construction: usize,
    ef_search: usize,
    rerank_candidates: usize,
    query_memory_budget_mb: usize,
}

impl BenchConfig {
    fn from_env() -> Result<Self, String> {
        let config = Self {
            vectors: env_u32("OMEGA_BENCH_VECTORS", 5_000)?,
            dimensions: env_usize("OMEGA_BENCH_DIMENSIONS", 128)?,
            queries: env_usize("OMEGA_BENCH_QUERIES", 50)?,
            k: env_usize("OMEGA_BENCH_K", 10)?,
            max_neighbors: env_usize("OMEGA_BENCH_MAX_NEIGHBORS", 12)?,
            ef_construction: env_usize("OMEGA_BENCH_EF_CONSTRUCTION", 96)?,
            ef_search: env_usize("OMEGA_BENCH_EF_SEARCH", 80)?,
            rerank_candidates: env_usize("OMEGA_BENCH_RERANK", 48)?,
            query_memory_budget_mb: env_usize("OMEGA_BENCH_QUERY_MEMORY_MB", 8)?,
        };
        if config.vectors == 0 || config.queries == 0 || config.k == 0 {
            return Err("vectors, queries and k must be non-zero".into());
        }
        if config.k > config.vectors as usize {
            return Err("k cannot exceed vector count".into());
        }
        Ok(config)
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct MemorySample {
    rss_kb: u64,
    peak_rss_kb: u64,
}

fn env_usize(name: &str, default: usize) -> Result<usize, String> {
    match env::var(name) {
        Ok(value) => value
            .parse::<usize>()
            .map_err(|error| format!("invalid {name}={value:?}: {error}")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(format!("cannot read {name}: {error}")),
    }
}

fn env_u32(name: &str, default: u32) -> Result<u32, String> {
    match env::var(name) {
        Ok(value) => value
            .parse::<u32>()
            .map_err(|error| format!("invalid {name}={value:?}: {error}")),
        Err(env::VarError::NotPresent) => Ok(default),
        Err(error) => Err(format!("cannot read {name}: {error}")),
    }
}

fn temp_index() -> PathBuf {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock")
        .as_nanos();
    env::temp_dir().join(format!(
        "omega-vector-bench-{}-{nonce}",
        std::process::id()
    ))
}

fn splitmix64(mut state: u64) -> u64 {
    state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
    let mut z = state;
    z = (z ^ (z >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    z = (z ^ (z >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    z ^ (z >> 31)
}

fn deterministic_vector(id: u64, dimensions: usize) -> Vec<f32> {
    let mut output = Vec::with_capacity(dimensions);
    for dimension in 0..dimensions {
        let bits = splitmix64(id.wrapping_mul(0x517c_c1b7_2722_0a95) ^ dimension as u64);
        let unit = (bits >> 11) as f64 / ((1u64 << 53) as f64);
        output.push((unit * 2.0 - 1.0) as f32);
    }
    output
}

fn normalize(vector: &[f32]) -> Vec<f32> {
    let norm = vector
        .iter()
        .map(|&value| {
            let value = value as f64;
            value * value
        })
        .sum::<f64>()
        .sqrt() as f32;
    vector.iter().map(|value| *value / norm).collect()
}

fn dot(a: &[f32], b: &[f32]) -> f32 {
    a.iter().zip(b).map(|(left, right)| left * right).sum()
}

fn exact_top_k(query: &[f32], vector_count: u32, dimensions: usize, k: usize) -> Vec<u64> {
    let query = normalize(query);
    let mut scored: Vec<(f32, u64)> = Vec::with_capacity(vector_count as usize);
    for id in 0..vector_count as u64 {
        let candidate = deterministic_vector(id, dimensions);
        let candidate = normalize(&candidate);
        scored.push((dot(&query, &candidate), id));
    }
    scored.sort_unstable_by(|a, b| {
        b.0.partial_cmp(&a.0)
            .unwrap_or(Ordering::Equal)
            .then_with(|| a.1.cmp(&b.1))
    });
    scored.truncate(k);
    scored.into_iter().map(|(_, id)| id).collect()
}

fn memory_sample_linux() -> MemorySample {
    let Ok(status) = fs::read_to_string("/proc/self/status") else {
        return MemorySample::default();
    };
    let mut sample = MemorySample::default();
    for line in status.lines() {
        if let Some(value) = line.strip_prefix("VmRSS:") {
            sample.rss_kb = parse_status_kb(value);
        } else if let Some(value) = line.strip_prefix("VmHWM:") {
            sample.peak_rss_kb = parse_status_kb(value);
        }
    }
    sample
}

fn parse_status_kb(value: &str) -> u64 {
    value
        .split_whitespace()
        .next()
        .and_then(|token| token.parse::<u64>().ok())
        .unwrap_or(0)
}

fn duration_ms(duration: Duration) -> f64 {
    duration.as_secs_f64() * 1_000.0
}

fn percentile_ms(values: &[Duration], percentile: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut millis: Vec<f64> = values.iter().copied().map(duration_ms).collect();
    millis.sort_by(|a, b| a.partial_cmp(b).unwrap_or(Ordering::Equal));
    let position = ((millis.len() - 1) as f64 * percentile).round() as usize;
    millis[position]
}

fn json_number(value: f64) -> String {
    if value.is_finite() {
        format!("{value:.6}")
    } else {
        "null".into()
    }
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let bench = BenchConfig::from_env().map_err(std::io::Error::other)?;
    let dir = temp_index();
    let memory_before = memory_sample_linux();

    let config = IndexConfig {
        dimensions: bench.dimensions,
        max_neighbors: bench.max_neighbors,
        initial_capacity: bench.vectors.max(1),
        ef_construction: bench.ef_construction,
        ef_search: bench.ef_search,
        rerank_candidates: bench.rerank_candidates,
        query_memory_budget_mb: bench.query_memory_budget_mb,
    };

    let mut index = OmegaVectorIndex::open(&dir, config)?;
    let build_started = Instant::now();
    for id in 0..bench.vectors as u64 {
        let vector = deterministic_vector(id, bench.dimensions);
        index.add(id, &vector)?;
    }
    index.flush()?;
    let build_elapsed = build_started.elapsed();
    let memory_after_build = memory_sample_linux();

    let mut query_latencies = Vec::with_capacity(bench.queries);
    let mut recall_hits = 0usize;
    let mut recall_total = 0usize;

    let query_phase_started = Instant::now();
    for query_index in 0..bench.queries {
        let source_id = ((query_index as u64).wrapping_mul(104_729)) % bench.vectors as u64;
        let query = deterministic_vector(source_id, bench.dimensions);
        let expected = exact_top_k(&query, bench.vectors, bench.dimensions, bench.k);

        let started = Instant::now();
        let actual = index.search(&query, bench.k)?;
        query_latencies.push(started.elapsed());

        for hit in actual {
            if expected.contains(&hit.external_id) {
                recall_hits += 1;
            }
        }
        recall_total += expected.len();
    }
    let query_phase_elapsed = query_phase_started.elapsed();
    let memory_after_queries = memory_sample_linux();
    let stats = index.stats();

    let recall_at_k = if recall_total == 0 {
        0.0
    } else {
        recall_hits as f64 / recall_total as f64
    };
    let qps = if query_phase_elapsed.is_zero() {
        0.0
    } else {
        bench.queries as f64 / query_phase_elapsed.as_secs_f64()
    };

    let persisted_bytes = fs::read_dir(&dir)?
        .filter_map(Result::ok)
        .filter_map(|entry| entry.metadata().ok())
        .map(|metadata| metadata.len())
        .sum::<u64>();

    println!("{{");
    println!("  \"schema\": \"pefy.omega.vector.benchmark.v1\",");
    println!("  \"vectors\": {},", bench.vectors);
    println!("  \"dimensions\": {},", bench.dimensions);
    println!("  \"queries\": {},", bench.queries);
    println!("  \"k\": {},", bench.k);
    println!("  \"max_neighbors\": {},", bench.max_neighbors);
    println!("  \"ef_construction\": {},", bench.ef_construction);
    println!("  \"ef_search\": {},", bench.ef_search);
    println!("  \"rerank_candidates\": {},", bench.rerank_candidates);
    println!("  \"query_memory_budget_mb\": {},", bench.query_memory_budget_mb);
    println!("  \"build_ms\": {},", json_number(duration_ms(build_elapsed)));
    println!("  \"p50_query_ms\": {},", json_number(percentile_ms(&query_latencies, 0.50)));
    println!("  \"p95_query_ms\": {},", json_number(percentile_ms(&query_latencies, 0.95)));
    println!("  \"p99_query_ms\": {},", json_number(percentile_ms(&query_latencies, 0.99)));
    println!("  \"query_phase_qps_including_ground_truth\": {},", json_number(qps));
    println!("  \"recall_at_k\": {},", json_number(recall_at_k));
    println!("  \"logical_bytes\": {},", stats.logical_bytes);
    println!("  \"mapped_virtual_bytes\": {},", stats.mapped_virtual_bytes);
    println!("  \"approx_bytes_per_vector\": {},", stats.approx_bytes_per_vector);
    println!("  \"persisted_index_bytes\": {},", persisted_bytes);
    println!("  \"rss_before_kb\": {},", memory_before.rss_kb);
    println!("  \"peak_rss_before_kb\": {},", memory_before.peak_rss_kb);
    println!("  \"rss_after_build_kb\": {},", memory_after_build.rss_kb);
    println!("  \"peak_rss_after_build_kb\": {},", memory_after_build.peak_rss_kb);
    println!("  \"rss_after_queries_kb\": {},", memory_after_queries.rss_kb);
    println!("  \"peak_rss_after_queries_kb\": {}", memory_after_queries.peak_rss_kb);
    println!("}}");

    drop(index);
    let _ = fs::remove_dir_all(dir);
    Ok(())
}
