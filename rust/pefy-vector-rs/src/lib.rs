#![forbid(unsafe_op_in_unsafe_fn)]
//! PEFY ΩVECTOR-RS.
//!
//! Low-memory vector retrieval for MƐTAFLOW Ω / MƐTAPEFYON Ω.
//! The search representation is normalized int8, exact-ish reranking data is
//! normalized f16, and both are memory-mapped. Graph links use fixed-width
//! u32 slots so the index avoids Python object overhead and does not require
//! retaining full f32 embeddings in process RAM.

mod ffi;

use half::f16;
use memmap2::{MmapMut, MmapOptions};
use std::cmp::Reverse;
use std::collections::{BinaryHeap, HashSet};
use std::fs::{self, File, OpenOptions};
use std::io::{Read, Seek, SeekFrom, Write};
use std::path::{Path, PathBuf};

const META_MAGIC: &[u8; 8] = b"PEFYVEC1";
const META_VERSION: u32 = 1;
const META_SIZE: u64 = 64;
const GRAPH_COUNT_BYTES: usize = 4;
const MIN_DIM: usize = 2;
const MAX_DIM: usize = 32_768;
const MIN_M: usize = 4;
const MAX_M: usize = 64;

#[derive(Debug, thiserror::Error)]
pub enum IndexError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("invalid configuration: {0}")]
    InvalidConfig(String),
    #[error("vector dimension mismatch: expected {expected}, got {actual}")]
    DimensionMismatch { expected: usize, actual: usize },
    #[error("index metadata is corrupt or incompatible: {0}")]
    Corrupt(String),
    #[error("vector norm is zero or non-finite")]
    InvalidVector,
    #[error("node id exceeds current index size")]
    InvalidNode,
    #[error("index size exceeds u32 node address space")]
    CapacityExceeded,
}

pub type Result<T> = std::result::Result<T, IndexError>;

#[derive(Clone, Debug)]
pub struct IndexConfig {
    pub dimensions: usize,
    pub max_neighbors: usize,
    pub initial_capacity: u32,
    pub ef_construction: usize,
    pub ef_search: usize,
    pub rerank_candidates: usize,
    /// Per-query scratch budget. mmap-backed pages remain governed by the OS
    /// page cache / container cgroup rather than being pinned by this crate.
    pub query_memory_budget_mb: usize,
}

impl IndexConfig {
    pub fn validate(&self) -> Result<()> {
        if !(MIN_DIM..=MAX_DIM).contains(&self.dimensions) {
            return Err(IndexError::InvalidConfig(format!(
                "dimensions must be in {MIN_DIM}..={MAX_DIM}"
            )));
        }
        if !(MIN_M..=MAX_M).contains(&self.max_neighbors) {
            return Err(IndexError::InvalidConfig(format!(
                "max_neighbors must be in {MIN_M}..={MAX_M}"
            )));
        }
        if self.initial_capacity == 0 {
            return Err(IndexError::InvalidConfig(
                "initial_capacity must be greater than zero".into(),
            ));
        }
        if self.ef_construction < self.max_neighbors {
            return Err(IndexError::InvalidConfig(
                "ef_construction must be >= max_neighbors".into(),
            ));
        }
        if self.ef_search == 0 || self.rerank_candidates == 0 {
            return Err(IndexError::InvalidConfig(
                "ef_search and rerank_candidates must be non-zero".into(),
            ));
        }
        if self.query_memory_budget_mb == 0 {
            return Err(IndexError::InvalidConfig(
                "query_memory_budget_mb must be non-zero".into(),
            ));
        }
        Ok(())
    }
}

impl Default for IndexConfig {
    fn default() -> Self {
        Self {
            dimensions: 768,
            max_neighbors: 12,
            initial_capacity: 4_096,
            ef_construction: 96,
            ef_search: 80,
            rerank_candidates: 48,
            query_memory_budget_mb: 8,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct SearchHit {
    pub external_id: u64,
    pub score: f32,
    pub node: u32,
}

#[derive(Clone, Debug)]
pub struct IndexStats {
    pub count: u32,
    pub capacity: u32,
    pub dimensions: usize,
    pub max_neighbors: usize,
    pub logical_bytes: u64,
    pub mapped_virtual_bytes: u64,
    pub approx_bytes_per_vector: u64,
    pub query_memory_budget_bytes: u64,
    pub generation: u64,
}

#[derive(Clone, Copy, Debug)]
struct Meta {
    dimensions: u32,
    max_neighbors: u32,
    count: u64,
    capacity: u64,
    generation: u64,
}

#[derive(Clone, Copy)]
struct BackingFiles<'a> {
    q8: &'a File,
    f16_data: &'a File,
    graph: &'a File,
    ids: &'a File,
    tombstones: &'a File,
}

pub struct OmegaVectorIndex {
    dir: PathBuf,
    config: IndexConfig,
    count: u32,
    capacity: u32,
    generation: u64,
    meta_file: File,
    q8_file: File,
    f16_file: File,
    graph_file: File,
    ids_file: File,
    tombstone_file: File,
    q8: MmapMut,
    f16_data: MmapMut,
    graph: MmapMut,
    ids: MmapMut,
    tombstones: MmapMut,
}

impl OmegaVectorIndex {
    pub fn open(path: impl AsRef<Path>, config: IndexConfig) -> Result<Self> {
        config.validate()?;
        let dir = path.as_ref().to_path_buf();
        fs::create_dir_all(&dir)?;

        let meta_path = dir.join("meta.bin");
        let existed = meta_path.exists();
        let mut meta_file = open_rw(&meta_path)?;

        let (count, capacity, generation) = if existed && meta_file.metadata()?.len() >= META_SIZE {
            let meta = read_meta(&mut meta_file)?;
            if meta.dimensions as usize != config.dimensions {
                return Err(IndexError::Corrupt(format!(
                    "stored dimensions {} differ from requested {}",
                    meta.dimensions, config.dimensions
                )));
            }
            if meta.max_neighbors as usize != config.max_neighbors {
                return Err(IndexError::Corrupt(format!(
                    "stored max_neighbors {} differ from requested {}",
                    meta.max_neighbors, config.max_neighbors
                )));
            }
            if meta.count > u32::MAX as u64 || meta.capacity > u32::MAX as u64 {
                return Err(IndexError::CapacityExceeded);
            }
            if meta.count > meta.capacity || meta.capacity == 0 {
                return Err(IndexError::Corrupt(
                    "invalid count/capacity relationship".into(),
                ));
            }
            (meta.count as u32, meta.capacity as u32, meta.generation)
        } else {
            meta_file.set_len(META_SIZE)?;
            write_meta(
                &mut meta_file,
                Meta {
                    dimensions: config.dimensions as u32,
                    max_neighbors: config.max_neighbors as u32,
                    count: 0,
                    capacity: config.initial_capacity as u64,
                    generation: 0,
                },
            )?;
            (0, config.initial_capacity, 0)
        };

        let q8_file = open_rw(dir.join("vectors.q8"))?;
        let f16_file = open_rw(dir.join("vectors.f16"))?;
        let graph_file = open_rw(dir.join("graph.u32"))?;
        let ids_file = open_rw(dir.join("ids.u64"))?;
        let tombstone_file = open_rw(dir.join("tombstones.u8"))?;

        resize_backing_files(
            BackingFiles {
                q8: &q8_file,
                f16_data: &f16_file,
                graph: &graph_file,
                ids: &ids_file,
                tombstones: &tombstone_file,
            },
            capacity,
            config.dimensions,
            config.max_neighbors,
        )?;

        let q8 = map_rw(&q8_file)?;
        let f16_data = map_rw(&f16_file)?;
        let graph = map_rw(&graph_file)?;
        let ids = map_rw(&ids_file)?;
        let tombstones = map_rw(&tombstone_file)?;

        Ok(Self {
            dir,
            config,
            count,
            capacity,
            generation,
            meta_file,
            q8_file,
            f16_file,
            graph_file,
            ids_file,
            tombstone_file,
            q8,
            f16_data,
            graph,
            ids,
            tombstones,
        })
    }

    pub fn len(&self) -> u32 {
        self.count
    }

    pub fn is_empty(&self) -> bool {
        self.count == 0
    }

    pub fn directory(&self) -> &Path {
        &self.dir
    }

    pub fn add(&mut self, external_id: u64, vector: &[f32]) -> Result<u32> {
        self.check_dimension(vector)?;
        if self.count == u32::MAX {
            return Err(IndexError::CapacityExceeded);
        }
        self.ensure_capacity(self.count.saturating_add(1))?;

        let node = self.count;
        let norm = vector_norm(vector)?;
        self.write_vector(node, vector, norm);
        self.write_external_id(node, external_id);
        self.tombstones[node as usize] = 0;

        if node > 0 {
            let query = self.q8_row(node).to_vec();
            let candidates = self.approx_candidates(
                &query,
                self.config.ef_construction.max(self.config.max_neighbors),
                node,
            );
            let selected: Vec<u32> = candidates
                .into_iter()
                .take(self.config.max_neighbors)
                .map(|(_, candidate)| candidate)
                .collect();

            self.clear_graph_record(node);
            for (slot, neighbor) in selected.iter().copied().enumerate() {
                self.set_neighbor(node, slot, neighbor);
            }
            self.set_neighbor_count(node, selected.len());

            for neighbor in selected {
                self.insert_or_replace_neighbor(neighbor, node);
            }
        } else {
            self.clear_graph_record(node);
        }

        self.count = self.count.saturating_add(1);
        Ok(node)
    }

    pub fn search(&self, query: &[f32], k: usize) -> Result<Vec<SearchHit>> {
        self.check_dimension(query)?;
        if k == 0 || self.count == 0 {
            return Ok(Vec::new());
        }

        let (query_q8, query_norm) = encode_query(query)?;
        let requested_ef = self.config.ef_search.max(k.saturating_mul(4)).max(k);
        let candidates = self.approx_candidates(&query_q8, requested_ef, self.count);
        let rerank_limit = self
            .config
            .rerank_candidates
            .max(k.saturating_mul(2))
            .max(k)
            .min(candidates.len());

        let mut hits = Vec::with_capacity(rerank_limit);
        for (_, node) in candidates.into_iter().take(rerank_limit) {
            if self.is_deleted(node) {
                continue;
            }
            hits.push(SearchHit {
                external_id: self.external_id(node),
                score: self.exact_score(node, &query_norm),
                node,
            });
        }

        hits.sort_unstable_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.node.cmp(&b.node))
        });
        hits.truncate(k);
        Ok(hits)
    }

    pub fn mark_deleted(&mut self, node: u32) -> Result<()> {
        if node >= self.count {
            return Err(IndexError::InvalidNode);
        }
        self.tombstones[node as usize] = 1;
        Ok(())
    }

    pub fn flush(&mut self) -> Result<()> {
        self.q8.flush()?;
        self.f16_data.flush()?;
        self.graph.flush()?;
        self.ids.flush()?;
        self.tombstones.flush()?;

        self.generation = self.generation.saturating_add(1);
        write_meta(
            &mut self.meta_file,
            Meta {
                dimensions: self.config.dimensions as u32,
                max_neighbors: self.config.max_neighbors as u32,
                count: self.count as u64,
                capacity: self.capacity as u64,
                generation: self.generation,
            },
        )?;
        self.meta_file.sync_data()?;
        Ok(())
    }

    pub fn stats(&self) -> IndexStats {
        let q8_per = self.config.dimensions as u64;
        let f16_per = self.config.dimensions as u64 * 2;
        let graph_per = self.graph_record_size() as u64;
        let misc_per = 8 + 1;
        let per = q8_per + f16_per + graph_per + misc_per;
        IndexStats {
            count: self.count,
            capacity: self.capacity,
            dimensions: self.config.dimensions,
            max_neighbors: self.config.max_neighbors,
            logical_bytes: per.saturating_mul(self.count as u64),
            mapped_virtual_bytes: per.saturating_mul(self.capacity as u64),
            approx_bytes_per_vector: per,
            query_memory_budget_bytes: (self.config.query_memory_budget_mb as u64)
                .saturating_mul(1024 * 1024),
            generation: self.generation,
        }
    }

    fn check_dimension(&self, vector: &[f32]) -> Result<()> {
        if vector.len() != self.config.dimensions {
            return Err(IndexError::DimensionMismatch {
                expected: self.config.dimensions,
                actual: vector.len(),
            });
        }
        Ok(())
    }

    fn graph_record_size(&self) -> usize {
        GRAPH_COUNT_BYTES + self.config.max_neighbors * 4
    }

    fn ensure_capacity(&mut self, required: u32) -> Result<()> {
        if required <= self.capacity {
            return Ok(());
        }
        let doubled = self.capacity.saturating_mul(2);
        let grown = self.capacity.saturating_add(1_024);
        let new_capacity = doubled.max(grown).max(required);
        if new_capacity <= self.capacity {
            return Err(IndexError::CapacityExceeded);
        }

        self.q8.flush()?;
        self.f16_data.flush()?;
        self.graph.flush()?;
        self.ids.flush()?;
        self.tombstones.flush()?;

        // Drop file-backed mappings before resize for Windows compatibility.
        let old_q8 = std::mem::replace(&mut self.q8, MmapMut::map_anon(1)?);
        let old_f16 = std::mem::replace(&mut self.f16_data, MmapMut::map_anon(1)?);
        let old_graph = std::mem::replace(&mut self.graph, MmapMut::map_anon(1)?);
        let old_ids = std::mem::replace(&mut self.ids, MmapMut::map_anon(1)?);
        let old_tombstones = std::mem::replace(&mut self.tombstones, MmapMut::map_anon(1)?);
        drop((old_q8, old_f16, old_graph, old_ids, old_tombstones));

        resize_backing_files(
            BackingFiles {
                q8: &self.q8_file,
                f16_data: &self.f16_file,
                graph: &self.graph_file,
                ids: &self.ids_file,
                tombstones: &self.tombstone_file,
            },
            new_capacity,
            self.config.dimensions,
            self.config.max_neighbors,
        )?;
        self.q8 = map_rw(&self.q8_file)?;
        self.f16_data = map_rw(&self.f16_file)?;
        self.graph = map_rw(&self.graph_file)?;
        self.ids = map_rw(&self.ids_file)?;
        self.tombstones = map_rw(&self.tombstone_file)?;
        self.capacity = new_capacity;
        Ok(())
    }

    fn write_vector(&mut self, node: u32, vector: &[f32], norm: f32) {
        let q8_start = node as usize * self.config.dimensions;
        let f16_start = node as usize * self.config.dimensions * 2;
        for (i, value) in vector.iter().copied().enumerate() {
            let normalized = value / norm;
            let quantized = (normalized * 127.0).round().clamp(-127.0, 127.0) as i16;
            self.q8[q8_start + i] = (quantized + 128) as u8;
            let bits = f16::from_f32(normalized).to_bits().to_le_bytes();
            let offset = f16_start + i * 2;
            self.f16_data[offset] = bits[0];
            self.f16_data[offset + 1] = bits[1];
        }
    }

    fn q8_row(&self, node: u32) -> &[u8] {
        let start = node as usize * self.config.dimensions;
        &self.q8[start..start + self.config.dimensions]
    }

    fn dot_q8_query(&self, node: u32, query: &[u8]) -> i64 {
        self.q8_row(node)
            .iter()
            .zip(query)
            .map(|(&a, &b)| {
                let ai = a as i16 - 128;
                let bi = b as i16 - 128;
                ai as i64 * bi as i64
            })
            .sum()
    }

    fn dot_q8_nodes(&self, a: u32, b: u32) -> i64 {
        self.q8_row(a)
            .iter()
            .zip(self.q8_row(b))
            .map(|(&x, &y)| {
                let xi = x as i16 - 128;
                let yi = y as i16 - 128;
                xi as i64 * yi as i64
            })
            .sum()
    }

    fn exact_score(&self, node: u32, query_norm: &[f32]) -> f32 {
        let start = node as usize * self.config.dimensions * 2;
        query_norm
            .iter()
            .enumerate()
            .map(|(i, &q)| {
                let offset = start + i * 2;
                let bits = u16::from_le_bytes([self.f16_data[offset], self.f16_data[offset + 1]]);
                f16::from_bits(bits).to_f32() * q
            })
            .sum()
    }

    fn write_external_id(&mut self, node: u32, external_id: u64) {
        let start = node as usize * 8;
        self.ids[start..start + 8].copy_from_slice(&external_id.to_le_bytes());
    }

    fn external_id(&self, node: u32) -> u64 {
        let start = node as usize * 8;
        u64::from_le_bytes(
            self.ids[start..start + 8]
                .try_into()
                .expect("8-byte id slice"),
        )
    }

    fn graph_offset(&self, node: u32) -> usize {
        node as usize * self.graph_record_size()
    }

    fn clear_graph_record(&mut self, node: u32) {
        let start = self.graph_offset(node);
        let end = start + self.graph_record_size();
        self.graph[start..end].fill(0);
    }

    fn neighbor_count(&self, node: u32) -> usize {
        let start = self.graph_offset(node);
        u32::from_le_bytes(
            self.graph[start..start + 4]
                .try_into()
                .expect("4-byte graph count"),
        ) as usize
    }

    fn set_neighbor_count(&mut self, node: u32, count: usize) {
        let start = self.graph_offset(node);
        self.graph[start..start + 4].copy_from_slice(&(count as u32).to_le_bytes());
    }

    fn neighbor(&self, node: u32, slot: usize) -> u32 {
        let start = self.graph_offset(node) + GRAPH_COUNT_BYTES + slot * 4;
        u32::from_le_bytes(
            self.graph[start..start + 4]
                .try_into()
                .expect("4-byte neighbor slice"),
        )
    }

    fn set_neighbor(&mut self, node: u32, slot: usize, neighbor: u32) {
        let start = self.graph_offset(node) + GRAPH_COUNT_BYTES + slot * 4;
        self.graph[start..start + 4].copy_from_slice(&neighbor.to_le_bytes());
    }

    fn insert_or_replace_neighbor(&mut self, owner: u32, candidate: u32) {
        if owner == candidate {
            return;
        }
        let count = self.neighbor_count(owner).min(self.config.max_neighbors);
        for slot in 0..count {
            if self.neighbor(owner, slot) == candidate {
                return;
            }
        }
        if count < self.config.max_neighbors {
            self.set_neighbor(owner, count, candidate);
            self.set_neighbor_count(owner, count + 1);
            return;
        }

        let candidate_score = self.dot_q8_nodes(owner, candidate);
        let mut weakest_slot = 0usize;
        let mut weakest_score = i64::MAX;
        for slot in 0..count {
            let existing = self.neighbor(owner, slot);
            let score = self.dot_q8_nodes(owner, existing);
            if score < weakest_score {
                weakest_score = score;
                weakest_slot = slot;
            }
        }
        if candidate_score > weakest_score {
            self.set_neighbor(owner, weakest_slot, candidate);
        }
    }

    fn effective_ef(&self, requested: usize) -> usize {
        // Conservative scratch estimate covers BinaryHeap + HashSet entry overhead.
        const APPROX_SCRATCH_BYTES_PER_VISITED_NODE: usize = 128;
        let budget_bytes = self
            .config
            .query_memory_budget_mb
            .saturating_mul(1024 * 1024);
        let max_by_budget = (budget_bytes / APPROX_SCRATCH_BYTES_PER_VISITED_NODE).max(32);
        requested.min(max_by_budget).max(1)
    }

    fn approx_candidates(
        &self,
        query: &[u8],
        requested_ef: usize,
        upper_bound: u32,
    ) -> Vec<(i64, u32)> {
        if upper_bound == 0 {
            return Vec::new();
        }
        let ef = self
            .effective_ef(requested_ef)
            .min(upper_bound as usize)
            .max(1);
        let max_seen = ef
            .saturating_mul(self.config.max_neighbors.saturating_add(2))
            .min(self.effective_ef(usize::MAX))
            .max(ef);

        let mut frontier: BinaryHeap<(i64, u32)> = BinaryHeap::new();
        let mut best: BinaryHeap<Reverse<(i64, u32)>> = BinaryHeap::new();
        let mut visited = HashSet::with_capacity(max_seen.min(65_536));

        let seeds = [0, upper_bound / 2, upper_bound.saturating_sub(1)];
        for seed in seeds {
            if seed >= upper_bound || !visited.insert(seed) {
                continue;
            }
            let score = self.dot_q8_query(seed, query);
            frontier.push((score, seed));
            best.push(Reverse((score, seed)));
        }

        let mut expanded = 0usize;
        while let Some((score, node)) = frontier.pop() {
            if best.len() >= ef
                && let Some(Reverse((worst_score, _))) = best.peek().copied()
                && expanded >= ef
                && score < worst_score
            {
                break;
            }
            if expanded >= max_seen {
                break;
            }
            expanded += 1;

            let neighbor_count = self.neighbor_count(node).min(self.config.max_neighbors);
            for slot in 0..neighbor_count {
                if visited.len() >= max_seen {
                    break;
                }
                let neighbor = self.neighbor(node, slot);
                if neighbor >= upper_bound || !visited.insert(neighbor) {
                    continue;
                }
                let neighbor_score = self.dot_q8_query(neighbor, query);
                let should_keep = best.len() < ef
                    || best
                        .peek()
                        .map(|Reverse((worst, _))| neighbor_score > *worst)
                        .unwrap_or(true);
                if should_keep {
                    frontier.push((neighbor_score, neighbor));
                    best.push(Reverse((neighbor_score, neighbor)));
                    if best.len() > ef {
                        best.pop();
                    }
                }
            }
        }

        let mut out: Vec<(i64, u32)> = best.into_iter().map(|Reverse(value)| value).collect();
        out.sort_unstable_by(|a, b| b.cmp(a));
        out
    }

    fn is_deleted(&self, node: u32) -> bool {
        self.tombstones[node as usize] != 0
    }
}

fn open_rw(path: impl AsRef<Path>) -> std::io::Result<File> {
    OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .truncate(false)
        .open(path)
}

fn map_rw(file: &File) -> std::io::Result<MmapMut> {
    // SAFETY: the file is kept open for the lifetime of the mapping, mappings
    // are private to this index handle, and resize operations drop mappings
    // before changing file lengths.
    unsafe { MmapOptions::new().map_mut(file) }
}

fn resize_backing_files(
    files: BackingFiles<'_>,
    capacity: u32,
    dimensions: usize,
    max_neighbors: usize,
) -> std::io::Result<()> {
    let capacity = capacity as u64;
    files
        .q8
        .set_len(capacity.saturating_mul(dimensions as u64))?;
    files
        .f16_data
        .set_len(capacity.saturating_mul(dimensions as u64).saturating_mul(2))?;
    files.graph.set_len(
        capacity.saturating_mul((GRAPH_COUNT_BYTES + max_neighbors.saturating_mul(4)) as u64),
    )?;
    files.ids.set_len(capacity.saturating_mul(8))?;
    files.tombstones.set_len(capacity)?;
    Ok(())
}

fn vector_norm(vector: &[f32]) -> Result<f32> {
    let sum: f64 = vector
        .iter()
        .map(|&value| {
            let value = value as f64;
            value * value
        })
        .sum();
    let norm = sum.sqrt() as f32;
    if !norm.is_finite() || norm <= f32::EPSILON {
        return Err(IndexError::InvalidVector);
    }
    Ok(norm)
}

fn encode_query(vector: &[f32]) -> Result<(Vec<u8>, Vec<f32>)> {
    let norm = vector_norm(vector)?;
    let mut q8 = Vec::with_capacity(vector.len());
    let mut normalized = Vec::with_capacity(vector.len());
    for &value in vector {
        let value = value / norm;
        normalized.push(value);
        let quantized = (value * 127.0).round().clamp(-127.0, 127.0) as i16;
        q8.push((quantized + 128) as u8);
    }
    Ok((q8, normalized))
}

fn read_meta(file: &mut File) -> Result<Meta> {
    let mut bytes = [0u8; META_SIZE as usize];
    file.seek(SeekFrom::Start(0))?;
    file.read_exact(&mut bytes)?;
    if &bytes[0..8] != META_MAGIC {
        return Err(IndexError::Corrupt("metadata magic mismatch".into()));
    }
    let version = u32::from_le_bytes(bytes[8..12].try_into().expect("version slice"));
    if version != META_VERSION {
        return Err(IndexError::Corrupt(format!(
            "unsupported metadata version {version}"
        )));
    }
    Ok(Meta {
        dimensions: u32::from_le_bytes(bytes[12..16].try_into().expect("dim slice")),
        max_neighbors: u32::from_le_bytes(bytes[16..20].try_into().expect("m slice")),
        count: u64::from_le_bytes(bytes[24..32].try_into().expect("count slice")),
        capacity: u64::from_le_bytes(bytes[32..40].try_into().expect("capacity slice")),
        generation: u64::from_le_bytes(bytes[40..48].try_into().expect("generation slice")),
    })
}

fn write_meta(file: &mut File, meta: Meta) -> Result<()> {
    let mut bytes = [0u8; META_SIZE as usize];
    bytes[0..8].copy_from_slice(META_MAGIC);
    bytes[8..12].copy_from_slice(&META_VERSION.to_le_bytes());
    bytes[12..16].copy_from_slice(&meta.dimensions.to_le_bytes());
    bytes[16..20].copy_from_slice(&meta.max_neighbors.to_le_bytes());
    bytes[24..32].copy_from_slice(&meta.count.to_le_bytes());
    bytes[32..40].copy_from_slice(&meta.capacity.to_le_bytes());
    bytes[40..48].copy_from_slice(&meta.generation.to_le_bytes());
    file.seek(SeekFrom::Start(0))?;
    file.write_all(&bytes)?;
    file.flush()?;
    Ok(())
}

pub use ffi::{
    PefyVectorHandle, PefyVectorStats, pefy_vector_add, pefy_vector_close, pefy_vector_flush,
    pefy_vector_last_error, pefy_vector_mark_deleted, pefy_vector_open, pefy_vector_search,
    pefy_vector_stats,
};
