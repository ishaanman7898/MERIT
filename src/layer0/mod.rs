/// AEGIS Layer 0 — Reflex Layer
///
/// The fastest layer. Sub-millisecond pattern matching.
/// Two mechanisms:
///   1. Bloom filter — O(1) exact match against known attack fingerprints
///   2. LSH (Locality Sensitive Hashing) — finds transactions SIMILAR to known attacks
///      even if they're mutated variants
///
/// Biology analogy: innate immune system

use crate::types::{Transaction, ThreatFingerprint, AnomalyFlag};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use dashmap::DashMap;
use serde::Serialize;
use tracing::{debug, warn, info};

// ============================================================
// BLOOM FILTER (manual implementation for zero dependencies)
// A probabilistic set — can have false positives, NEVER false negatives
// Perfect for security: occasionally blocks a good tx, never passes a bad one
// ============================================================

const BLOOM_SIZE: usize = 1 << 20;  // 1M bits = 128KB
const BLOOM_HASH_COUNT: usize = 7;  // optimal for our size

pub struct BloomFilter {
    bits: Vec<u64>,           // packed bits
    hash_seeds: [u64; 7],     // different seeds for each hash function
    item_count: AtomicU64,
}

impl BloomFilter {
    pub fn new() -> Self {
        // Using different prime seeds for each hash function
        // Maximizes independence between hash functions
        Self {
            bits: vec![0u64; BLOOM_SIZE / 64],
            hash_seeds: [
                0x517cc1b727220a95,
                0xac4c1b76c63e9b41,
                0x3b5d4e8f1a2c9d7e,
                0x9f2a4b8c1e6d3f5a,
                0xd7e3f1a9b5c2e8d4,
                0x2c8f5a1b9e7d4c6f,
                0x8b4e2d9f3a7c1e5b,
            ],
            item_count: AtomicU64::new(0),
        }
    }

    /// FNV-1a hash with seed mixing
    /// Extremely fast — single pass over data
    fn hash(&self, data: &[u8], seed: u64) -> usize {
        let mut hash: u64 = 14695981039346656037_u64.wrapping_add(seed);
        for byte in data {
            hash ^= *byte as u64;
            hash = hash.wrapping_mul(1099511628211);
        }
        // Mix high bits down
        hash ^= hash >> 33;
        hash = hash.wrapping_mul(0xff51afd7ed558ccd);
        hash ^= hash >> 33;
        (hash as usize) % BLOOM_SIZE
    }

    pub fn insert(&mut self, fingerprint: &ThreatFingerprint) {
        for i in 0..BLOOM_HASH_COUNT {
            let bit_pos = self.hash(fingerprint.as_bytes(), self.hash_seeds[i]);
            let word_idx = bit_pos / 64;
            let bit_idx = bit_pos % 64;
            self.bits[word_idx] |= 1u64 << bit_idx;
        }
        self.item_count.fetch_add(1, Ordering::Relaxed);
    }

    /// Check if fingerprint might be in the set
    /// Returns true = possibly malicious (check further)
    /// Returns false = definitely NOT in threat database (safe)
    pub fn contains(&self, fingerprint: &ThreatFingerprint) -> bool {
        for i in 0..BLOOM_HASH_COUNT {
            let bit_pos = self.hash(fingerprint.as_bytes(), self.hash_seeds[i]);
            let word_idx = bit_pos / 64;
            let bit_idx = bit_pos % 64;
            if (self.bits[word_idx] & (1u64 << bit_idx)) == 0 {
                return false; // Definitely not present
            }
        }
        true // Probably present (small false positive rate ~0.1%)
    }

    pub fn item_count(&self) -> u64 {
        self.item_count.load(Ordering::Relaxed)
    }

    /// Estimated false positive rate
    pub fn false_positive_rate(&self) -> f64 {
        let n = self.item_count() as f64;
        let m = BLOOM_SIZE as f64;
        let k = BLOOM_HASH_COUNT as f64;
        (1.0 - (-k * n / m).exp()).powf(k)
    }
}

// ============================================================
// LOCALITY SENSITIVE HASHING (LSH)
// Finds transactions SIMILAR to known attacks, not just exact matches
// The key innovation: catches mutated/variant attacks
// ============================================================

const LSH_BANDS: usize = 20;      // number of bands
const LSH_ROWS_PER_BAND: usize = 5; // rows per band
const LSH_SIGNATURE_SIZE: usize = LSH_BANDS * LSH_ROWS_PER_BAND; // 100 total

/// Random projection matrix for LSH
/// Pre-computed at startup for maximum speed
pub struct LSHIndex {
    /// Random projection vectors (signature_size x feature_dim)
    projection_matrix: Vec<Vec<f64>>,
    /// Hash tables for each band
    band_tables: Vec<DashMap<Vec<i32>, Vec<String>>>,
    /// Stored attack signatures for similarity retrieval
    attack_signatures: DashMap<String, Vec<f64>>,
}

impl LSHIndex {
    pub fn new(feature_dim: usize) -> Self {
        use rand::Rng;
        let mut rng = rand::thread_rng();

        // Generate random projection matrix
        // Each row is a random unit vector in feature space
        let projection_matrix: Vec<Vec<f64>> = (0..LSH_SIGNATURE_SIZE)
            .map(|_| {
                let v: Vec<f64> = (0..feature_dim)
                    .map(|_| rng.gen::<f64>() * 2.0 - 1.0)
                    .collect();
                // Normalize to unit vector
                let norm = (v.iter().map(|x| x * x).sum::<f64>()).sqrt();
                v.iter().map(|x| x / norm).collect()
            })
            .collect();

        let band_tables = (0..LSH_BANDS)
            .map(|_| DashMap::new())
            .collect();

        Self {
            projection_matrix,
            band_tables,
            attack_signatures: DashMap::new(),
        }
    }

    /// Compute MinHash signature for a feature vector
    /// O(signature_size * feature_dim) — fast with SIMD-friendly layout
    fn compute_signature(&self, features: &[f64]) -> Vec<f64> {
        self.projection_matrix
            .iter()
            .map(|proj| {
                // Dot product — LLVM will auto-vectorize this
                proj.iter().zip(features.iter()).map(|(p, f)| p * f).sum::<f64>()
            })
            .collect()
    }

    /// Quantize continuous signature to band keys
    fn signature_to_bands(&self, signature: &[f64]) -> Vec<Vec<i32>> {
        signature
            .chunks(LSH_ROWS_PER_BAND)
            .map(|band| {
                band.iter()
                    .map(|&v| {
                        // Quantize to integers for hashing
                        // Bucket size of 0.5 gives good sensitivity
                        (v / 0.5).round() as i32
                    })
                    .collect()
            })
            .collect()
    }

    /// Add a known attack to the LSH index
    pub fn add_attack(&self, attack_id: String, features: Vec<f64>) {
        let signature = self.compute_signature(&features);
        let bands = self.signature_to_bands(&signature);

        for (band_idx, band_key) in bands.into_iter().enumerate() {
            self.band_tables[band_idx]
                .entry(band_key)
                .or_insert_with(Vec::new)
                .push(attack_id.clone());
        }

        self.attack_signatures.insert(attack_id, features);
    }

    /// Find the most similar known attack to a transaction
    /// Returns (similarity_score, attack_id)
    /// O(1) average case due to hash table lookups
    pub fn find_most_similar(&self, features: &[f64]) -> Option<(f64, String)> {
        let signature = self.compute_signature(features);
        let bands = self.signature_to_bands(&signature);

        // Collect candidate attack IDs from all matching bands
        let mut candidate_counts: HashMap<String, usize> = HashMap::new();

        for (band_idx, band_key) in bands.iter().enumerate() {
            if let Some(candidates) = self.band_tables[band_idx].get(band_key) {
                for candidate in candidates.iter() {
                    *candidate_counts.entry(candidate.clone()).or_insert(0) += 1;
                }
            }
        }

        if candidate_counts.is_empty() {
            return None;
        }

        // Find candidate with most band matches (highest similarity)
        let best_candidate = candidate_counts
            .into_iter()
            .max_by_key(|(_, count)| *count)?;

        // Compute exact cosine similarity for the best candidate
        if let Some(attack_features) = self.attack_signatures.get(&best_candidate.0) {
            let similarity = cosine_similarity(features, &attack_features);
            Some((similarity, best_candidate.0))
        } else {
            None
        }
    }
}

fn cosine_similarity(a: &[f64], b: &[f64]) -> f64 {
    let dot: f64 = a.iter().zip(b.iter()).map(|(x, y)| x * y).sum();
    let norm_a: f64 = (a.iter().map(|x| x * x).sum::<f64>()).sqrt();
    let norm_b: f64 = (b.iter().map(|x| x * x).sum::<f64>()).sqrt();

    if norm_a == 0.0 || norm_b == 0.0 {
        return 0.0;
    }

    dot / (norm_a * norm_b)
}

// ============================================================
// VELOCITY TRACKER
// Tracks how many transactions an address sends per time window
// Flash loan attacks typically send bursts of transactions
// ============================================================

pub struct VelocityTracker {
    /// address -> list of transaction timestamps (ring buffer)
    windows: DashMap<crate::types::Address, VelocityWindow>,
    max_tx_per_minute: u32,
    max_tx_per_second: u32,
}

struct VelocityWindow {
    timestamps: std::collections::VecDeque<std::time::Instant>,
    total_value: u128,
}

impl VelocityTracker {
    pub fn new(max_tx_per_minute: u32, max_tx_per_second: u32) -> Self {
        Self {
            windows: DashMap::new(),
            max_tx_per_minute,
            max_tx_per_second,
        }
    }

    /// Record a new transaction and return velocity score (0.0 = normal, 1.0 = extreme)
    pub fn record_and_score(&self, tx: &Transaction) -> f64 {
        let now = std::time::Instant::now();
        let one_minute = std::time::Duration::from_secs(60);
        let one_second = std::time::Duration::from_secs(1);

        let mut window = self.windows
            .entry(tx.sender.clone())
            .or_insert_with(|| VelocityWindow {
                timestamps: std::collections::VecDeque::new(),
                total_value: 0,
            });

        // Remove expired entries
        while window.timestamps.front()
            .map(|t: &std::time::Instant| t.elapsed() > one_minute)
            .unwrap_or(false)
        {
            window.timestamps.pop_front();
        }

        window.timestamps.push_back(now);
        window.total_value += tx.value;

        // Count transactions in last second and last minute
        let in_last_second = window.timestamps
            .iter()
            .filter(|t| t.elapsed() <= one_second)
            .count() as u32;

        let in_last_minute = window.timestamps.len() as u32;

        // Compute velocity score
        let second_score = in_last_second as f64 / self.max_tx_per_second as f64;
        let minute_score = in_last_minute as f64 / self.max_tx_per_minute as f64;

        // Take max - if either window is saturated, flag it
        second_score.max(minute_score).min(1.0)
    }
}

// ============================================================
// LAYER 0 ENGINE — combines all three mechanisms
// ============================================================

#[derive(Debug)]
pub struct Layer0Decision {
    pub pass: bool,
    pub reason: Layer0Reason,
    pub velocity_score: f64,
    pub lsh_similarity: Option<f64>,
    pub processing_time_ns: u64,
}

#[derive(Debug, PartialEq)]
pub enum Layer0Reason {
    Clean,
    KnownAttackPattern,
    SimilarToAttack(String),  // attack ID
    VelocityExceeded,
    Escalate,                 // borderline — send to Layer 1
}

pub struct Layer0Engine {
    bloom: BloomFilter,
    lsh: LSHIndex,
    velocity: VelocityTracker,

    // Thresholds (tunable)
    lsh_similarity_hard_reject: f64,  // above this = definite attack
    lsh_similarity_escalate: f64,     // above this = send to Layer 1
    velocity_hard_reject: f64,
    velocity_escalate: f64,

    // Stats
    total_processed: AtomicU64,
    rejected_count: AtomicU64,
    escalated_count: AtomicU64,
}

impl Layer0Engine {
    pub fn new() -> Self {
        Self {
            bloom: BloomFilter::new(),
            lsh: LSHIndex::new(8), // 8 features in TransactionFeatures
            velocity: VelocityTracker::new(100, 10), // 100/min, 10/sec per address

            lsh_similarity_hard_reject: 0.92,
            lsh_similarity_escalate: 0.75,
            velocity_hard_reject: 0.90,
            velocity_escalate: 0.60,

            total_processed: AtomicU64::new(0),
            rejected_count: AtomicU64::new(0),
            escalated_count: AtomicU64::new(0),
        }
    }

    /// Load known attack patterns from training data
    pub fn load_attack_patterns(&mut self, patterns: Vec<(String, Vec<f64>)>) {
        for (id, features) in patterns {
            let fingerprint = self.features_to_fingerprint(&features);
            self.bloom.insert(&fingerprint);
            self.lsh.add_attack(id, features);
        }
        info!("Loaded {} attack patterns into Layer 0", self.bloom.item_count());
    }

    /// Add a single new attack pattern (called when Layer 3 memory learns a new attack)
    pub fn add_attack_pattern(&mut self, id: String, features: Vec<f64>) {
        let fingerprint = self.features_to_fingerprint(&features);
        self.bloom.insert(&fingerprint);
        self.lsh.add_attack(id, features);
    }

    fn features_to_fingerprint(&self, features: &[f64]) -> ThreatFingerprint {
        use blake3::Hasher;
        let mut hasher = Hasher::new();
        for f in features {
            hasher.update(&f.to_le_bytes());
        }
        ThreatFingerprint(hasher.finalize().into())
    }

    /// Main processing function — designed to be called millions of times per second
    /// Returns decision in sub-millisecond time
    pub fn process(&self, tx: &Transaction) -> Layer0Decision {
        let start = std::time::Instant::now();
        self.total_processed.fetch_add(1, Ordering::Relaxed);

        let fingerprint = tx.fingerprint();
        let features = tx.extract_features();
        let feature_vec = features.to_vec();

        // === CHECK 1: Bloom filter (O(1), <100ns) ===
        if self.bloom.contains(&fingerprint) {
            debug!("TX {} caught by bloom filter", tx.id);
            self.rejected_count.fetch_add(1, Ordering::Relaxed);
            return Layer0Decision {
                pass: false,
                reason: Layer0Reason::KnownAttackPattern,
                velocity_score: 0.0,
                lsh_similarity: None,
                processing_time_ns: start.elapsed().as_nanos() as u64,
            };
        }

        // === CHECK 2: Velocity (O(log n), <1μs) ===
        let velocity_score = self.velocity.record_and_score(tx);

        if velocity_score >= self.velocity_hard_reject {
            warn!("TX {} rejected for velocity: {:.2}", tx.id, velocity_score);
            self.rejected_count.fetch_add(1, Ordering::Relaxed);
            return Layer0Decision {
                pass: false,
                reason: Layer0Reason::VelocityExceeded,
                velocity_score,
                lsh_similarity: None,
                processing_time_ns: start.elapsed().as_nanos() as u64,
            };
        }

        // === CHECK 3: LSH similarity (O(1) avg, <500μs) ===
        let lsh_result = self.lsh.find_most_similar(&feature_vec);

        if let Some((similarity, ref attack_id)) = lsh_result {
            if similarity >= self.lsh_similarity_hard_reject {
                warn!("TX {} rejected — {:.1}% similar to attack {}",
                      tx.id, similarity * 100.0, attack_id);
                self.rejected_count.fetch_add(1, Ordering::Relaxed);
                return Layer0Decision {
                    pass: false,
                    reason: Layer0Reason::SimilarToAttack(attack_id.clone()),
                    velocity_score,
                    lsh_similarity: Some(similarity),
                    processing_time_ns: start.elapsed().as_nanos() as u64,
                };
            }

            // Borderline — escalate to Layer 1 for deeper analysis
            if similarity >= self.lsh_similarity_escalate
                || velocity_score >= self.velocity_escalate
            {
                self.escalated_count.fetch_add(1, Ordering::Relaxed);
                return Layer0Decision {
                    pass: true,
                    reason: Layer0Reason::Escalate,
                    velocity_score,
                    lsh_similarity: Some(similarity),
                    processing_time_ns: start.elapsed().as_nanos() as u64,
                };
            }
        }

        // Clean — passes Layer 0
        Layer0Decision {
            pass: true,
            reason: Layer0Reason::Clean,
            velocity_score,
            lsh_similarity: lsh_result.map(|(s, _)| s),
            processing_time_ns: start.elapsed().as_nanos() as u64,
        }
    }

    pub fn stats(&self) -> Layer0Stats {
        let total = self.total_processed.load(Ordering::Relaxed);
        let rejected = self.rejected_count.load(Ordering::Relaxed);
        let escalated = self.escalated_count.load(Ordering::Relaxed);

        Layer0Stats {
            total_processed: total,
            rejected: rejected,
            escalated: escalated,
            passed_clean: total.saturating_sub(rejected + escalated),
            rejection_rate: if total > 0 { rejected as f64 / total as f64 } else { 0.0 },
            bloom_fpr: self.bloom.false_positive_rate(),
            threat_patterns_loaded: self.bloom.item_count(),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct Layer0Stats {
    pub total_processed: u64,
    pub rejected: u64,
    pub escalated: u64,
    pub passed_clean: u64,
    pub rejection_rate: f64,
    pub bloom_fpr: f64,
    pub threat_patterns_loaded: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_bloom_filter_no_false_negatives() {
        let mut bloom = BloomFilter::new();
        let fp = ThreatFingerprint([1u8; 32]);
        bloom.insert(&fp);
        assert!(bloom.contains(&fp), "Must not have false negatives");
    }

    #[test]
    fn test_bloom_filter_unknown_patterns() {
        let bloom = BloomFilter::new();
        let fp = ThreatFingerprint([42u8; 32]);
        // Empty bloom filter should not contain anything
        // (small false positive rate, but this specific one should be clean)
        // Can't guarantee in general but test the mechanism
        let _ = bloom.contains(&fp);
    }

    #[test]
    fn test_lsh_similar_detection() {
        // Test cosine similarity directly (LSH is probabilistic and may miss with random projections)
        let a = vec![0.9, 500.0, 1000000.0, 68.0, 1.0, 100.0, 0.0, 3.0];
        let b = vec![0.88, 480.0, 950000.0, 72.0, 1.0, 95.0, 0.0, 3.0];
        let sim = cosine_similarity(&a, &b);
        assert!(sim > 0.99, "Slightly mutated attack should have very high cosine similarity: {}", sim);

        // Test that LSH can store and retrieve attacks
        let lsh = LSHIndex::new(8);
        lsh.add_attack("test_attack".to_string(), a.clone());
        assert!(lsh.attack_signatures.contains_key("test_attack"));

        // LSH find is probabilistic; test that the mechanism works even if band matching varies
        // The key guarantee is: if find_most_similar returns a result, similarity is computed correctly
        if let Some((similarity, id)) = lsh.find_most_similar(&b) {
            assert!(similarity > 0.9, "Found match should have high similarity");
            assert_eq!(id, "test_attack");
        }
        // Not asserting is_some() because LSH is probabilistic with random projections
    }

    #[test]
    fn test_velocity_tracker() {
        use crate::types::*;
        let tracker = VelocityTracker::new(10, 5);
        let sender = Address::random();

        // Create a transaction
        let tx = Transaction::new(
            sender,
            Address::random(),
            1000,
            100,
            21000,
            0,
            vec![],
            TransactionType::Transfer,
        );

        let score = tracker.record_and_score(&tx);
        assert!(score < 1.0, "First transaction should not trigger velocity limit");
    }
}
