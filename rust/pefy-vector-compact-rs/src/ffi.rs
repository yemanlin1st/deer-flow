use crate::{IndexConfig, IndexStats, OmegaCompactVectorIndex};
use std::cell::RefCell;
use std::ffi::CStr;
use std::os::raw::{c_char, c_float};
use std::ptr;
use std::sync::Mutex;

thread_local! {
    static LAST_ERROR: RefCell<String> = const { RefCell::new(String::new()) };
}

fn set_error(message: impl Into<String>) {
    LAST_ERROR.with(|slot| *slot.borrow_mut() = message.into());
}

#[repr(C)]
pub struct PefyVectorStats {
    pub count: u32,
    pub capacity: u32,
    pub dimensions: u32,
    pub max_neighbors: u32,
    pub logical_bytes: u64,
    pub mapped_virtual_bytes: u64,
    pub approx_bytes_per_vector: u64,
    pub query_memory_budget_bytes: u64,
    pub generation: u64,
}

impl From<IndexStats> for PefyVectorStats {
    fn from(value: IndexStats) -> Self {
        Self {
            count: value.count,
            capacity: value.capacity,
            dimensions: value.dimensions as u32,
            max_neighbors: value.max_neighbors as u32,
            logical_bytes: value.logical_bytes,
            mapped_virtual_bytes: value.mapped_virtual_bytes,
            approx_bytes_per_vector: value.approx_bytes_per_vector,
            query_memory_budget_bytes: value.query_memory_budget_bytes,
            generation: value.generation,
        }
    }
}

pub struct PefyVectorHandle {
    index: Mutex<OmegaCompactVectorIndex>,
}

/// Opens or creates an ΩVECTOR-RS Compact index.
///
/// # Safety
///
/// `path` must point to a valid NUL-terminated C string. The returned handle
/// must be closed exactly once with [`pefy_vector_close`].
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_open(
    path: *const c_char,
    dimensions: u32,
    max_neighbors: u32,
    initial_capacity: u32,
    ef_construction: u32,
    ef_search: u32,
    rerank_candidates: u32,
    query_memory_budget_mb: u32,
) -> *mut PefyVectorHandle {
    if path.is_null() {
        set_error("path pointer is null");
        return ptr::null_mut();
    }
    // SAFETY: required by this function's public safety contract.
    let path = unsafe { CStr::from_ptr(path) };
    let path = match path.to_str() {
        Ok(value) => value,
        Err(error) => {
            set_error(format!("path is not valid UTF-8: {error}"));
            return ptr::null_mut();
        }
    };

    let config = IndexConfig {
        dimensions: dimensions as usize,
        max_neighbors: max_neighbors as usize,
        initial_capacity,
        ef_construction: ef_construction as usize,
        ef_search: ef_search as usize,
        rerank_candidates: rerank_candidates as usize,
        query_memory_budget_mb: query_memory_budget_mb as usize,
    };

    match OmegaCompactVectorIndex::open(path, config) {
        Ok(index) => Box::into_raw(Box::new(PefyVectorHandle {
            index: Mutex::new(index),
        })),
        Err(error) => {
            set_error(error.to_string());
            ptr::null_mut()
        }
    }
}

/// Adds one vector to an ΩVECTOR-RS Compact index.
///
/// # Safety
///
/// `handle` must be live. `vector` must contain at least `dimensions`
/// readable `f32` values. Non-null `out_node` must be writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_add(
    handle: *mut PefyVectorHandle,
    external_id: u64,
    vector: *const c_float,
    dimensions: usize,
    out_node: *mut u32,
) -> i32 {
    if handle.is_null() || vector.is_null() {
        set_error("handle or vector pointer is null");
        return -1;
    }
    // SAFETY: required by this function's public safety contract.
    let vector = unsafe { std::slice::from_raw_parts(vector, dimensions) };
    // SAFETY: required by this function's public safety contract.
    let handle = unsafe { &*handle };
    let mut guard = match handle.index.lock() {
        Ok(value) => value,
        Err(_) => {
            set_error("vector index mutex is poisoned");
            return -2;
        }
    };
    match guard.add(external_id, vector) {
        Ok(node) => {
            if !out_node.is_null() {
                // SAFETY: required by this function's public safety contract.
                unsafe { *out_node = node };
            }
            0
        }
        Err(error) => {
            set_error(error.to_string());
            -3
        }
    }
}

/// Searches an ΩVECTOR-RS Compact index.
///
/// # Safety
///
/// `handle` must be live. `query` must contain at least `dimensions` readable
/// values. Output arrays must each contain at least `out_capacity` writable
/// entries and `out_capacity` must be at least `k`.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_search(
    handle: *const PefyVectorHandle,
    query: *const c_float,
    dimensions: usize,
    k: usize,
    out_ids: *mut u64,
    out_scores: *mut c_float,
    out_capacity: usize,
) -> isize {
    if handle.is_null() || query.is_null() || out_ids.is_null() || out_scores.is_null() {
        set_error("search received a null pointer");
        return -1;
    }
    if out_capacity < k {
        set_error("search output capacity is smaller than k");
        return -2;
    }
    // SAFETY: required by this function's public safety contract.
    let query = unsafe { std::slice::from_raw_parts(query, dimensions) };
    // SAFETY: required by this function's public safety contract.
    let handle = unsafe { &*handle };
    let guard = match handle.index.lock() {
        Ok(value) => value,
        Err(_) => {
            set_error("vector index mutex is poisoned");
            return -3;
        }
    };
    let hits = match guard.search(query, k) {
        Ok(value) => value,
        Err(error) => {
            set_error(error.to_string());
            return -4;
        }
    };
    for (offset, hit) in hits.iter().enumerate() {
        // SAFETY: `hits.len() <= k <= out_capacity` by construction.
        unsafe {
            *out_ids.add(offset) = hit.external_id;
            *out_scores.add(offset) = hit.score;
        }
    }
    hits.len() as isize
}

/// Marks a node deleted.
///
/// # Safety
///
/// `handle` must be live.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_mark_deleted(handle: *mut PefyVectorHandle, node: u32) -> i32 {
    if handle.is_null() {
        set_error("handle pointer is null");
        return -1;
    }
    // SAFETY: required by this function's public safety contract.
    let handle = unsafe { &*handle };
    let mut guard = match handle.index.lock() {
        Ok(value) => value,
        Err(_) => {
            set_error("vector index mutex is poisoned");
            return -2;
        }
    };
    match guard.mark_deleted(node) {
        Ok(()) => 0,
        Err(error) => {
            set_error(error.to_string());
            -3
        }
    }
}

/// Flushes mapped data and advances durable metadata.
///
/// # Safety
///
/// `handle` must be live.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_flush(handle: *mut PefyVectorHandle) -> i32 {
    if handle.is_null() {
        set_error("handle pointer is null");
        return -1;
    }
    // SAFETY: required by this function's public safety contract.
    let handle = unsafe { &*handle };
    let mut guard = match handle.index.lock() {
        Ok(value) => value,
        Err(_) => {
            set_error("vector index mutex is poisoned");
            return -2;
        }
    };
    match guard.flush() {
        Ok(()) => 0,
        Err(error) => {
            set_error(error.to_string());
            -3
        }
    }
}

/// Copies current index statistics.
///
/// # Safety
///
/// `handle` must be live and `out` must be writable.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_stats(
    handle: *const PefyVectorHandle,
    out: *mut PefyVectorStats,
) -> i32 {
    if handle.is_null() || out.is_null() {
        set_error("stats received a null pointer");
        return -1;
    }
    // SAFETY: required by this function's public safety contract.
    let handle = unsafe { &*handle };
    let guard = match handle.index.lock() {
        Ok(value) => value,
        Err(_) => {
            set_error("vector index mutex is poisoned");
            return -2;
        }
    };
    let stats = PefyVectorStats::from(guard.stats());
    // SAFETY: required by this function's public safety contract.
    unsafe { *out = stats };
    0
}

/// Copies the current thread-local error text.
///
/// # Safety
///
/// A non-null `buffer` must point to at least `capacity` writable bytes.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_last_error(buffer: *mut c_char, capacity: usize) -> usize {
    LAST_ERROR.with(|slot| {
        let message = slot.borrow();
        let bytes = message.as_bytes();
        let required = bytes.len().saturating_add(1);
        if buffer.is_null() || capacity == 0 {
            return required;
        }
        let writable = bytes.len().min(capacity.saturating_sub(1));
        // SAFETY: required by this function's public safety contract.
        unsafe {
            ptr::copy_nonoverlapping(bytes.as_ptr(), buffer.cast::<u8>(), writable);
            *buffer.add(writable) = 0;
        }
        required
    })
}

/// Flushes and consumes the handle.
///
/// # Safety
///
/// `handle` must be null or a live handle not previously closed.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn pefy_vector_close(handle: *mut PefyVectorHandle) {
    if handle.is_null() {
        return;
    }
    // SAFETY: required by this function's public safety contract.
    let boxed = unsafe { Box::from_raw(handle) };
    if let Ok(mut guard) = boxed.index.lock()
        && let Err(error) = guard.flush()
    {
        set_error(error.to_string());
    }
}
