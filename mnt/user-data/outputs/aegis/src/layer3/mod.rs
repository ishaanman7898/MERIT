/// AEGIS Layer 3 — Immunological Memory
///
/// After every confirmed or rejected transaction, the network learns.
/// Rejected transactions teach Layer 0 new attack patterns.
/// Confirmed transactions update the "normal" baseline.
/// Validator vote outcomes update their BTS.
///
/// The network gets permanently smarter after every block.
/// Biology analogy: B-cells and memory T-cells

use crate::types::{
    Transaction, ValidatorId, ValidatorVote, ConsensusResult,
    ConsensusDecision, ThreatFingerprint,
};
use crate::layer0::Layer0Engine;
use crate::layer1::Layer1Engine;
use crate::layer2::Layer2Engine;
use dashmap::DashMap;
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::{debug, info, warn};
use serde::{Serialize, Deserialize};
use chrono::{DateTime, Utc};

// ============================================================
// THREAT MEMORY STORE
// Permanent storage of learned attack patterns
// Survives node restarts via serialization
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreatMemory {
    pub pattern_id: String,
    pub features: Vec<f64>,
    pub first_seen: DateTime<Utc>,
    pub times_seen: u32,
    pub last_seen: DateTime<Utc>,
    pub variant_of: Option<String>, // if this is a mutation of a known attack
    pub description: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct NormalBaseline {
    /// Running mean of each feature
    pub feature_means: Vec<f64>,
    /// Running variance of each feature
    pub feature_variances: Vec<f64>,
    /// Total samples observed
    pub sample_count: u64,
}

impl NormalBaseline {
    pub fn new(feature_dim: usize) -> Self {
        Self {
            feature_means: vec![0.0; feature_dim],
            feature_variances: vec![1.0; feature_dim],
            sample_count: 0,
        }
    }

    /// Welford's online algorithm for computing mean and variance
    /// This is THE correct way to do it — numerically stable, single pass
    /// No need to store all samples
    pub fn update(&mut self, features: &[f64]) {
        self.sample_count += 1;
        let n = self.sample_count as f64;

        for (i, &x) in features.iter().enumerate() {
            if i >= self.feature_means.len() { break; }

            let old_mean = self.feature_means[i];
            let delta = x - old_mean;
            self.feature_means[i] += delta / n;
            let delta2 = x - self.feature_means[i];
            // Update M2 (aggregate squared differences)
            // variance = M2 / (n-1) for sample variance
            let old_m2 = self.feature_variances[i] * (n - 1.0).max(1.0);
            let new_m2 = old_m2 + delta * delta2;
            self.feature_variances[i] = if n > 1.0 { new_m2 / (n - 1.0) } else { 0.0 };
        }
    }

    /// How anomalous is this feature vector relative to baseline?
    /// Returns z-scores for each feature
    pub fn anomaly_scores(&self, features: &[f64]) -> Vec<f64> {
        features.iter().enumerate().map(|(i, &x)| {
            if i >= self.feature_means.len() { return 0.0; }
            let std = self.feature_variances[i].sqrt();
            if std < 1e-10 { return 0.0; }
            ((x - self.feature_means[i]) / std).abs()
        }).collect()
    }

    /// Overall anomaly score (max z-score across features)
    pub fn overall_anomaly(&self, features: &[f64]) -> f64 {
        self.anomaly_scores(features)
            .iter()
            .cloned()
            .fold(0.0_f64, f64::max)
    }
}

// ============================================================
// VALIDATOR PERFORMANCE LEDGER
// Permanent record of how well each validator has done
// Used to compute long-term BTS adjustments
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidatorPerformanceLedger {
    pub validator_id: String,
    pub total_votes: u64,
    pub correct_votes: u64,
    pub false_positive_votes: u64, // said attack, was legitimate
    pub false_negative_votes: u64, // said legitimate, was attack
    pub total_stake_participated: u128,
    pub first_vote: DateTime<Utc>,
    pub last_vote: DateTime<Utc>,
}

impl ValidatorPerformanceLedger {
    pub fn new(validator_id: String) -> Self {
        Self {
            validator_id,
            total_votes: 0,
            correct_votes: 0,
            false_positive_votes: 0,
            false_negative_votes: 0,
            total_stake_participated: 0,
            first_vote: Utc::now(),
            last_vote: Utc::now(),
        }
    }

    pub fn accuracy(&self) -> f64 {
        if self.total_votes == 0 { return 0.5; }
        self.correct_votes as f64 / self.total_votes as f64
    }

    /// Precision: when validator flags something, how often is it right?
    pub fn false_positive_rate(&self) -> f64 {
        let flagged = self.false_positive_votes + self.correct_votes;
        if flagged == 0 { return 0.0; }
        self.false_positive_votes as f64 / flagged as f64
    }

    /// Miss rate: of actual attacks, how many did validator miss?
    pub fn false_negative_rate(&self) -> f64 {
        let actual_attacks = self.false_negative_votes + self.correct_votes;
        if actual_attacks == 0 { return 0.0; }
        self.false_negative_votes as f64 / actual_attacks as f64
    }

    /// Compute long-term BTS adjustment from performance history
    /// Range: -0.1 to +0.1 per epoch
    pub fn bts_adjustment(&self) -> f64 {
        let accuracy = self.accuracy();
        let fp_rate = self.false_positive_rate();

        // Reward accurate validators
        // Penalize validators who miss attacks (more dangerous than false positives)
        let base = (accuracy - 0.5) * 0.1;  // +0.05 for perfect, -0.05 for random
        let fp_penalty = fp_rate * 0.02;     // small penalty for false positives
        let fn_penalty = self.false_negative_rate() * 0.05; // bigger penalty for missing attacks

        (base - fp_penalty - fn_penalty).clamp(-0.1, 0.1)
    }
}

// ============================================================
// NETWORK THREAT BROADCAST
// When a new attack pattern is learned, broadcast to all nodes
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThreatBroadcast {
    pub broadcast_id: String,
    pub new_patterns: Vec<ThreatMemory>,
    pub timestamp: DateTime<Utc>,
    pub source_block: u64,
}

// ============================================================
// LAYER 3 ENGINE
// ============================================================

pub struct Layer3Engine {
    /// Learned attack patterns
    threat_memories: DashMap<String, ThreatMemory>,
    /// What normal looks like
    normal_baseline: Mutex<NormalBaseline>,
    /// Validator performance records
    validator_ledgers: DashMap<String, ValidatorPerformanceLedger>,
    /// Pending updates to propagate to Layer 0/1/2
    pending_broadcasts: Mutex<Vec<ThreatBroadcast>>,
    /// Current block height
    current_block: std::sync::atomic::AtomicU64,
}

impl Layer3Engine {
    pub fn new(feature_dim: usize) -> Self {
        Self {
            threat_memories: DashMap::new(),
            normal_baseline: Mutex::new(NormalBaseline::new(feature_dim)),
            validator_ledgers: DashMap::new(),
            pending_broadcasts: Mutex::new(Vec::new()),
            current_block: std::sync::atomic::AtomicU64::new(0),
        }
    }

    /// Called after every finalized consensus result
    /// This is the main learning loop
    pub async fn process_outcome(
        &self,
        tx: &Transaction,
        result: &ConsensusResult,
        votes: &[ValidatorVote],
        block_height: u64,
    ) {
        self.current_block.store(block_height, std::sync::atomic::Ordering::Relaxed);
        let features = tx.extract_features().to_vec();

        match &result.decision {
            ConsensusDecision::Confirmed => {
                // Update normal baseline with legitimate transaction
                self.update_normal_baseline(&features).await;

                // Update validator performance — those who voted correctly rewarded
                for vote in votes {
                    if vote.is_valid {
                        self.record_correct_vote(&vote.validator_id, false).await;
                    } else {
                        // Voted invalid but transaction was confirmed = false positive
                        self.record_incorrect_vote(&vote.validator_id, true).await;
                    }
                }

                debug!("TX {} confirmed, baseline updated", tx.id);
            }

            ConsensusDecision::Rejected => {
                // Learn this attack pattern
                let pattern_id = self.learn_attack_pattern(tx, &features, block_height).await;
                info!("New attack pattern learned: {} from TX {}", pattern_id, tx.id);

                // Update validator performance — those who voted invalid correctly rewarded
                for vote in votes {
                    if !vote.is_valid {
                        self.record_correct_vote(&vote.validator_id, true).await;
                    } else {
                        // Voted valid but it was an attack = false negative (dangerous)
                        self.record_incorrect_vote(&vote.validator_id, false).await;
                    }
                }
            }

            ConsensusDecision::Quarantined => {
                // Don't learn yet — wait for manual review
                // Just record it happened
                warn!("TX {} quarantined at block {}", tx.id, block_height);
            }

            ConsensusDecision::Escalated => {
                // Will come back through the system — don't record yet
            }
        }
    }

    async fn update_normal_baseline(&self, features: &[f64]) {
        let mut baseline = self.normal_baseline.lock().await;
        baseline.update(features);
    }

    async fn learn_attack_pattern(
        &self,
        tx: &Transaction,
        features: &[f64],
        block_height: u64,
    ) -> String {
        // Check if this is a variant of a known attack
        // (simplified — in production use LSH to find similar patterns)
        let pattern_id = format!("attack_{:x}", {
            let mut h = blake3::Hasher::new();
            for f in features {
                h.update(&f.to_le_bytes());
            }
            u64::from_le_bytes(h.finalize().as_bytes()[..8].try_into().unwrap_or([0;8]))
        });

        if let Some(mut existing) = self.threat_memories.get_mut(&pattern_id) {
            // Seen this pattern before — update count
            existing.times_seen += 1;
            existing.last_seen = Utc::now();
        } else {
            // New pattern
            let memory = ThreatMemory {
                pattern_id: pattern_id.clone(),
                features: features.to_vec(),
                first_seen: Utc::now(),
                times_seen: 1,
                last_seen: Utc::now(),
                variant_of: None,
                description: format!("Attack detected at block {}, TX type: {:?}", block_height, tx.tx_type),
            };

            self.threat_memories.insert(pattern_id.clone(), memory.clone());

            // Queue broadcast to other nodes
            let mut broadcasts = self.pending_broadcasts.lock().await;
            broadcasts.push(ThreatBroadcast {
                broadcast_id: uuid::Uuid::new_v4().to_string(),
                new_patterns: vec![memory],
                timestamp: Utc::now(),
                source_block: block_height,
            });
        }

        pattern_id
    }

    async fn record_correct_vote(&self, validator_id: &ValidatorId, caught_attack: bool) {
        let key = format!("{:?}", validator_id.0);
        let mut ledger = self.validator_ledgers
            .entry(key)
            .or_insert_with(|| ValidatorPerformanceLedger::new(
                format!("{:?}", validator_id.0)
            ));

        ledger.total_votes += 1;
        ledger.correct_votes += 1;
        ledger.last_vote = Utc::now();
    }

    async fn record_incorrect_vote(&self, validator_id: &ValidatorId, false_positive: bool) {
        let key = format!("{:?}", validator_id.0);
        let mut ledger = self.validator_ledgers
            .entry(key)
            .or_insert_with(|| ValidatorPerformanceLedger::new(
                format!("{:?}", validator_id.0)
            ));

        ledger.total_votes += 1;
        ledger.last_vote = Utc::now();

        if false_positive {
            ledger.false_positive_votes += 1;
        } else {
            ledger.false_negative_votes += 1; // missed an attack — dangerous
        }
    }

    /// Get all pending threat broadcasts to send to peers
    pub async fn drain_broadcasts(&self) -> Vec<ThreatBroadcast> {
        let mut pending = self.pending_broadcasts.lock().await;
        std::mem::take(&mut *pending)
    }

    /// Apply a received broadcast from another node
    pub async fn apply_broadcast(&self, broadcast: ThreatBroadcast, layer0: &mut Layer0Engine) {
        for pattern in broadcast.new_patterns {
            if !self.threat_memories.contains_key(&pattern.pattern_id) {
                let id = pattern.pattern_id.clone();
                let features = pattern.features.clone();
                self.threat_memories.insert(id.clone(), pattern);

                // Immediately update Layer 0
                layer0.add_attack_pattern(id, features);
            }
        }
    }

    /// Compute BTS adjustments for all validators based on performance
    /// Called once per epoch (e.g. every 100 blocks)
    pub fn compute_bts_adjustments(&self) -> Vec<(String, f64)> {
        self.validator_ledgers
            .iter()
            .map(|entry| {
                let adj = entry.value().bts_adjustment();
                (entry.key().clone(), adj)
            })
            .collect()
    }

    /// Get anomaly score for a transaction relative to learned baseline
    pub async fn anomaly_score(&self, features: &[f64]) -> f64 {
        let baseline = self.normal_baseline.lock().await;
        if baseline.sample_count < 100 {
            return 0.5; // Not enough data yet
        }
        baseline.overall_anomaly(features)
    }

    pub fn threat_count(&self) -> usize {
        self.threat_memories.len()
    }

    pub fn layer3_stats(&self) -> Layer3Stats {
        let total_votes: u64 = self.validator_ledgers
            .iter()
            .map(|e| e.value().total_votes)
            .sum();

        let avg_accuracy = {
            let accuracies: Vec<f64> = self.validator_ledgers
                .iter()
                .map(|e| e.value().accuracy())
                .collect();
            if accuracies.is_empty() { 0.0 }
            else { accuracies.iter().sum::<f64>() / accuracies.len() as f64 }
        };

        Layer3Stats {
            threat_patterns_learned: self.threat_memories.len(),
            total_votes_recorded: total_votes,
            avg_validator_accuracy: avg_accuracy,
            current_block: self.current_block.load(std::sync::atomic::Ordering::Relaxed),
        }
    }
}

#[derive(Debug, Serialize)]
pub struct Layer3Stats {
    pub threat_patterns_learned: usize,
    pub total_votes_recorded: u64,
    pub avg_validator_accuracy: f64,
    pub current_block: u64,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_welford_online_algorithm() {
        let mut baseline = NormalBaseline::new(3);

        // Feed known values
        let samples = vec![
            vec![1.0, 2.0, 3.0],
            vec![2.0, 4.0, 6.0],
            vec![3.0, 6.0, 9.0],
        ];

        for s in &samples {
            baseline.update(s);
        }

        // Mean should be [2, 4, 6]
        assert!((baseline.feature_means[0] - 2.0).abs() < 0.001);
        assert!((baseline.feature_means[1] - 4.0).abs() < 0.001);
        assert!((baseline.feature_means[2] - 6.0).abs() < 0.001);
    }

    #[test]
    fn test_anomaly_detection() {
        let mut baseline = NormalBaseline::new(2);

        // Build baseline with normal data
        for i in 0..100 {
            baseline.update(&[10.0 + (i % 3) as f64, 20.0 + (i % 5) as f64]);
        }

        // Normal transaction should have low anomaly
        let normal_score = baseline.overall_anomaly(&[11.0, 21.0]);
        assert!(normal_score < 3.0, "Normal tx should not be anomalous");

        // Extreme transaction should have high anomaly
        let extreme_score = baseline.overall_anomaly(&[1000.0, 5000.0]);
        assert!(extreme_score > 10.0, "Extreme tx should be very anomalous");
    }

    #[test]
    fn test_validator_ledger_bts_adjustment() {
        let mut ledger = ValidatorPerformanceLedger::new("test".to_string());

        // Perfect validator
        for _ in 0..100 {
            ledger.total_votes += 1;
            ledger.correct_votes += 1;
        }

        let adj = ledger.bts_adjustment();
        assert!(adj > 0.0, "Perfect validator should get positive adjustment");

        // Bad validator (misses attacks)
        let mut bad_ledger = ValidatorPerformanceLedger::new("bad".to_string());
        for _ in 0..100 {
            bad_ledger.total_votes += 1;
            bad_ledger.false_negative_votes += 1; // misses every attack
        }

        let bad_adj = bad_ledger.bts_adjustment();
        assert!(bad_adj < 0.0, "Attack-missing validator should get negative adjustment");
        assert!(bad_adj < adj, "Bad validator adjustment should be less than good");
    }
}
