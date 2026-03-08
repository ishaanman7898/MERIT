/// AEGIS Layer 1 — Behavioral Trust Scoring (BTS)
///
/// The novel layer. Tracks validator behavior over time using:
///   1. CUSUM (Cumulative Sum) algorithm — detects subtle shifts in latency distribution
///      This is how we catch coordinated attacks BEFORE they execute
///   2. Agreement graph analysis — detects collusion via communication patterns
///   3. Vote accuracy history — validators who caught attacks get more weight
///
/// Biology analogy: adaptive immune system — learns and remembers specific threats

use crate::types::{
    Transaction, ValidatorId, ValidatorInfo, ValidatorVote,
    AnomalyFlag, NetworkAlertLevel,
};
use dashmap::DashMap;
use std::collections::{HashMap, VecDeque};
use std::sync::Arc;
use tracing::{debug, info, warn};
use serde::{Serialize, Deserialize};
use chrono::{DateTime, Utc};

// ============================================================
// CUSUM ANOMALY DETECTOR
// Detects gradual shifts in a distribution, not just outliers
// A validator who normally responds in 50ms suddenly taking 150ms
// is suspicious — not an outlier, but a shift in the mean
// ============================================================

pub struct CUSUMDetector {
    /// Expected mean of the distribution (set during burn-in)
    target_mean: f64,
    /// Allowable slack (k = 0.5 * shift_to_detect * std)
    slack: f64,
    /// Upper cumulative sum
    s_upper: f64,
    /// Lower cumulative sum  
    s_lower: f64,
    /// Alert threshold — when to flag
    threshold: f64,
    /// History of observations for stats
    history: VecDeque<f64>,
    history_max: usize,
}

impl CUSUMDetector {
    pub fn new(target_mean: f64, std_dev: f64, threshold_multiplier: f64) -> Self {
        // Slack = half the minimum detectable shift
        // We want to detect shifts of 1 standard deviation
        let slack = 0.5 * std_dev;
        let threshold = threshold_multiplier * std_dev;

        Self {
            target_mean,
            slack,
            s_upper: 0.0,
            s_lower: 0.0,
            threshold,
            history: VecDeque::with_capacity(500),
            history_max: 500,
        }
    }

    /// Update with new observation, returns anomaly score (0.0 = normal, >1.0 = anomaly)
    pub fn update(&mut self, value: f64) -> f64 {
        // Store in history
        if self.history.len() >= self.history_max {
            self.history.pop_front();
        }
        self.history.push_back(value);

        // CUSUM update
        // s_upper catches upward shifts (getting slower)
        // s_lower catches downward shifts (suspiciously faster - could be pre-staging)
        self.s_upper = (self.s_upper + (value - self.target_mean - self.slack)).max(0.0);
        self.s_lower = (self.s_lower - (value - self.target_mean + self.slack)).max(0.0);

        // Return normalized anomaly score
        let max_sum = self.s_upper.max(self.s_lower);
        max_sum / self.threshold
    }

    /// Reset after alert is handled
    pub fn reset(&mut self) {
        self.s_upper = 0.0;
        self.s_lower = 0.0;
    }

    pub fn current_score(&self) -> f64 {
        let max_sum = self.s_upper.max(self.s_lower);
        max_sum / self.threshold
    }

    /// Check if currently anomalous
    pub fn is_anomalous(&self) -> bool {
        self.current_score() > 1.0
    }

    /// Compute mean of recent history
    pub fn recent_mean(&self) -> f64 {
        if self.history.is_empty() { return self.target_mean; }
        self.history.iter().sum::<f64>() / self.history.len() as f64
    }

    /// Compute std dev of recent history
    pub fn recent_std(&self) -> f64 {
        if self.history.len() < 2 { return 0.0; }
        let mean = self.recent_mean();
        let variance = self.history.iter()
            .map(|x| (x - mean).powi(2))
            .sum::<f64>() / (self.history.len() - 1) as f64;
        variance.sqrt()
    }
}

// ============================================================
// AGREEMENT GRAPH
// Tracks which validators agree with which other validators
// Sudden increase in agreement between specific validators = collusion signal
// ============================================================

pub struct AgreementGraph {
    /// (validator_a, validator_b) -> agreement_count in recent window
    edge_counts: HashMap<(String, String), VecDeque<f64>>,
    /// Baseline agreement rate (set during burn-in)
    baseline_agreement_rate: f64,
    window_size: usize,
}

impl AgreementGraph {
    pub fn new(window_size: usize) -> Self {
        Self {
            edge_counts: HashMap::new(),
            baseline_agreement_rate: 0.5, // default: validators agree ~50% of time
            window_size,
        }
    }

    /// Record agreement between two validators on a transaction
    pub fn record_agreement(&mut self, v1: &ValidatorId, v2: &ValidatorId, agreed: bool) {
        // Use sorted key to avoid (A,B) and (B,A) being different
        let key = self.make_key(v1, v2);

        let window = self.edge_counts.entry(key).or_insert_with(VecDeque::new);
        if window.len() >= self.window_size {
            window.pop_front();
        }
        window.push_back(if agreed { 1.0 } else { 0.0 });
    }

    fn make_key(&self, v1: &ValidatorId, v2: &ValidatorId) -> (String, String) {
        let s1 = format!("{:?}", v1.0);
        let s2 = format!("{:?}", v2.0);
        if s1 < s2 { (s1, s2) } else { (s2, s1) }
    }

    /// Get current agreement rate between two validators
    pub fn agreement_rate(&self, v1: &ValidatorId, v2: &ValidatorId) -> f64 {
        let key = self.make_key(v1, v2);
        if let Some(window) = self.edge_counts.get(&key) {
            if window.is_empty() { return self.baseline_agreement_rate; }
            window.iter().sum::<f64>() / window.len() as f64
        } else {
            self.baseline_agreement_rate
        }
    }

    /// Detect if a validator is colluding with others
    /// Returns collusion score (0.0 = clean, 1.0 = definite collusion)
    pub fn collusion_score(&self, target: &ValidatorId, all_validators: &[ValidatorId]) -> f64 {
        if all_validators.len() < 3 { return 0.0; }

        let agreement_rates: Vec<f64> = all_validators.iter()
            .filter(|v| {
                // Compare string representations to avoid implementing PartialEq
                format!("{:?}", v.0) != format!("{:?}", target.0)
            })
            .map(|v| self.agreement_rate(target, v))
            .collect();

        if agreement_rates.is_empty() { return 0.0; }

        let mean_agreement = agreement_rates.iter().sum::<f64>() / agreement_rates.len() as f64;
        let std_agreement = {
            let variance = agreement_rates.iter()
                .map(|r| (r - mean_agreement).powi(2))
                .sum::<f64>() / agreement_rates.len() as f64;
            variance.sqrt()
        };

        // High variance = validator agrees strongly with some but not others
        // = potential collusion cluster
        let variance_score = std_agreement / (self.baseline_agreement_rate + 0.01);

        // Count validators with suspiciously high agreement
        let high_agreement_count = agreement_rates.iter()
            .filter(|&&r| r > self.baseline_agreement_rate * 1.5)
            .count() as f64;

        let cluster_score = high_agreement_count / all_validators.len() as f64;

        // Combine: high variance AND clustering together = strong collusion signal
        (variance_score * 0.4 + cluster_score * 0.6).min(1.0)
    }
}

// ============================================================
// BURN-IN STATE MACHINE
// Prevents new validators from being falsely flagged
// ============================================================

#[derive(Debug, Clone, PartialEq)]
pub enum BurnInState {
    Active { blocks_remaining: u64 },
    Complete,
}

// ============================================================
// VALIDATOR BEHAVIORAL PROFILE
// The core per-validator state maintained by Layer 1
// ============================================================

pub struct ValidatorProfile {
    pub id: ValidatorId,
    pub info: ValidatorInfo,

    // Burn-in
    pub burn_in: BurnInState,
    burn_in_latencies: Vec<f64>,
    burn_in_required: u64,

    // CUSUM detectors
    latency_cusum: CUSUMDetector,
    response_rate_cusum: CUSUMDetector,

    // Agreement graph
    // Note: stored at Layer1Engine level, not per-validator

    // Vote accuracy history
    vote_history: VecDeque<VoteRecord>,
    vote_history_max: usize,

    // Computed BTS
    pub current_bts: f64,
    bts_history: VecDeque<f64>,

    // Timestamps
    pub last_seen: DateTime<Utc>,
    pub blocks_active: u64,

    // Anomaly state
    pub anomaly_flags: Vec<AnomalyFlag>,
}

#[derive(Debug, Clone)]
struct VoteRecord {
    block_height: u64,
    was_correct: bool,
    confidence_at_vote: f64,
    latency_ms: f64,
}

impl ValidatorProfile {
    pub fn new(info: ValidatorInfo, burn_in_blocks: u64) -> Self {
        // Default CUSUM with conservative parameters
        // Will be recalibrated after burn-in
        let latency_cusum = CUSUMDetector::new(100.0, 50.0, 5.0);
        let response_rate_cusum = CUSUMDetector::new(0.95, 0.1, 3.0);

        Self {
            id: info.id.clone(),
            info,
            burn_in: BurnInState::Active { blocks_remaining: burn_in_blocks },
            burn_in_latencies: Vec::new(),
            burn_in_required: burn_in_blocks,
            latency_cusum,
            response_rate_cusum,
            vote_history: VecDeque::with_capacity(1000),
            vote_history_max: 1000,
            current_bts: 0.5, // neutral score during burn-in
            bts_history: VecDeque::with_capacity(100),
            last_seen: Utc::now(),
            blocks_active: 0,
            anomaly_flags: Vec::new(),
        }
    }

    /// Record a new observation from this validator
    pub fn record_observation(&mut self, latency_ms: f64, responded: bool) {
        self.last_seen = Utc::now();
        self.blocks_active += 1;

        match &self.burn_in {
            BurnInState::Active { blocks_remaining } => {
                // During burn-in: just collect data
                self.burn_in_latencies.push(latency_ms);

                let remaining = blocks_remaining - 1;
                if remaining == 0 {
                    self.complete_burn_in();
                } else {
                    self.burn_in = BurnInState::Active { blocks_remaining: remaining };
                }
            }
            BurnInState::Complete => {
                // After burn-in: actually score
                let latency_anomaly = self.latency_cusum.update(latency_ms);
                let response_val = if responded { 1.0 } else { 0.0 };
                let rate_anomaly = self.response_rate_cusum.update(response_val);

                // Update BTS based on anomaly scores
                // Anomaly reduces BTS, recovery slowly increases it
                if latency_anomaly > 1.0 || rate_anomaly > 1.0 {
                    let penalty = (latency_anomaly.max(rate_anomaly) - 1.0) * 0.05;
                    self.current_bts = (self.current_bts - penalty).max(0.0);
                } else {
                    // Slow recovery
                    self.current_bts = (self.current_bts + 0.001).min(1.0);
                }

                // Record BTS history
                if self.bts_history.len() >= 100 {
                    self.bts_history.pop_front();
                }
                self.bts_history.push_back(self.current_bts);
            }
        }
    }

    fn complete_burn_in(&mut self) {
        if self.burn_in_latencies.is_empty() {
            return;
        }

        // Compute mean and std from burn-in period
        let n = self.burn_in_latencies.len() as f64;
        let mean = self.burn_in_latencies.iter().sum::<f64>() / n;
        let std = (self.burn_in_latencies.iter()
            .map(|x| (x - mean).powi(2))
            .sum::<f64>() / (n - 1.0).max(1.0))
            .sqrt();

        info!(
            "Validator {} burn-in complete. Baseline latency: {:.1}ms ± {:.1}ms",
            self.id, mean, std
        );

        // Recalibrate CUSUM with real baseline
        self.latency_cusum = CUSUMDetector::new(mean, std.max(1.0), 5.0);

        // Set initial BTS based on burn-in behavior
        // Was the validator consistent during burn-in?
        let cv = std / mean; // coefficient of variation
        self.current_bts = if cv < 0.3 {
            0.8 // consistent = trustworthy
        } else if cv < 0.6 {
            0.6
        } else {
            0.4 // inconsistent during burn-in
        };

        self.burn_in = BurnInState::Complete;
    }

    /// Record outcome of a vote (was the validator right?)
    pub fn record_vote_outcome(
        &mut self,
        block_height: u64,
        was_correct: bool,
        confidence: f64,
        latency_ms: f64,
    ) {
        if self.vote_history.len() >= self.vote_history_max {
            self.vote_history.pop_front();
        }

        self.vote_history.push_back(VoteRecord {
            block_height,
            was_correct,
            confidence_at_vote: confidence,
            latency_ms,
        });

        // Update BTS based on correctness
        // High confidence wrong vote = bigger penalty
        let bts_delta = if was_correct {
            0.002 * confidence // reward proportional to confidence
        } else {
            -0.01 * confidence // bigger penalty for confident wrong votes
        };

        self.current_bts = (self.current_bts + bts_delta).clamp(0.0, 1.0);
    }

    /// Get vote accuracy in recent window
    pub fn recent_accuracy(&self, window: usize) -> f64 {
        let recent: Vec<&VoteRecord> = self.vote_history.iter()
            .rev()
            .take(window)
            .collect();

        if recent.is_empty() { return 0.5; }
        recent.iter().filter(|v| v.was_correct).count() as f64 / recent.len() as f64
    }

    /// Is this validator's BTS sufficient to vote at current alert level?
    pub fn can_vote(&self, alert_level: &NetworkAlertLevel) -> bool {
        if self.burn_in != BurnInState::Complete {
            return false;
        }
        self.current_bts >= alert_level.min_bts_to_vote()
    }

    pub fn latency_anomaly_score(&self) -> f64 {
        self.latency_cusum.current_score()
    }
}

// ============================================================
// LAYER 1 ENGINE
// ============================================================

pub struct Layer1Engine {
    profiles: DashMap<String, ValidatorProfile>,
    agreement_graph: tokio::sync::Mutex<AgreementGraph>,
    burn_in_blocks: u64,
    current_alert_level: tokio::sync::RwLock<NetworkAlertLevel>,
}

impl Layer1Engine {
    pub fn new(burn_in_blocks: u64) -> Self {
        Self {
            profiles: DashMap::new(),
            agreement_graph: tokio::sync::Mutex::new(AgreementGraph::new(500)),
            burn_in_blocks,
            current_alert_level: tokio::sync::RwLock::new(NetworkAlertLevel::Normal),
        }
    }

    pub fn register_validator(&self, info: ValidatorInfo) {
        let key = format!("{:?}", info.id.0);
        let profile = ValidatorProfile::new(info, self.burn_in_blocks);
        self.profiles.insert(key, profile);
        info!("Registered validator with {}-block burn-in", self.burn_in_blocks);
    }

    /// Score a transaction from the perspective of a specific validator
    /// Returns (confidence, anomaly_flags)
    pub async fn score_transaction(
        &self,
        tx: &Transaction,
        validator_id: &ValidatorId,
        latency_ms: f64,
    ) -> (f64, Vec<AnomalyFlag>) {
        let key = format!("{:?}", validator_id.0);
        let alert_level = self.current_alert_level.read().await;

        let mut anomaly_flags = Vec::new();

        // Get validator profile
        let bts = if let Some(mut profile) = self.profiles.get_mut(&key) {
            profile.record_observation(latency_ms, true);

            // Check for latency anomaly
            if profile.latency_anomaly_score() > 0.8 {
                anomaly_flags.push(AnomalyFlag::TemporalAnomaly);
            }

            if !profile.can_vote(&alert_level) {
                return (0.0, anomaly_flags); // Not trusted enough to vote
            }

            profile.current_bts
        } else {
            return (0.0, vec![]); // Unknown validator
        };

        // Check for suspicious transaction patterns
        let features = tx.extract_features();

        // High value-to-gas ratio is a flash loan signal
        if features.value_to_gas_ratio > 1000.0 {
            anomaly_flags.push(AnomalyFlag::HighValueToGasRatio);
        }

        // Large data payload with high value = complex attack potential
        if features.data_length > 1000 && features.value_log > 10.0 {
            anomaly_flags.push(AnomalyFlag::UnusualCallPattern);
        }

        // Compute base confidence from BTS
        let base_confidence = bts;

        // Reduce confidence for each anomaly flag
        let confidence_reduction = anomaly_flags.len() as f64 * 0.1;
        let final_confidence = (base_confidence - confidence_reduction).max(0.05);

        (final_confidence, anomaly_flags)
    }

    /// Record agreement between validators after a consensus round
    pub async fn record_validator_agreements(
        &self,
        votes: &[ValidatorVote],
    ) {
        let mut graph = self.agreement_graph.lock().await;

        for i in 0..votes.len() {
            for j in (i + 1)..votes.len() {
                let agreed = votes[i].is_valid == votes[j].is_valid;
                graph.record_agreement(&votes[i].validator_id, &votes[j].validator_id, agreed);
            }
        }
    }

    /// Compute collusion risk for a validator
    pub async fn collusion_score(&self, validator_id: &ValidatorId) -> f64 {
        let graph = self.agreement_graph.lock().await;
        let all_ids: Vec<ValidatorId> = self.profiles
            .iter()
            .map(|entry| {
                // Reconstruct ValidatorId from key
                // In production this would be stored directly
                ValidatorId([0u8; 32]) // placeholder
            })
            .collect();

        graph.collusion_score(validator_id, &all_ids)
    }

    /// Update network alert level based on current conditions
    pub async fn update_alert_level(&self) -> NetworkAlertLevel {
        let mut anomalous_validators = 0;
        let mut total_validators = 0;
        let mut avg_bts: f64 = 0.0;

        for entry in self.profiles.iter() {
            let profile = entry.value();
            if profile.burn_in == BurnInState::Complete {
                total_validators += 1;
                avg_bts += profile.current_bts;
                if profile.latency_anomaly_score() > 1.0 {
                    anomalous_validators += 1;
                }
            }
        }

        if total_validators == 0 {
            return NetworkAlertLevel::Normal;
        }

        avg_bts /= total_validators as f64;
        let anomaly_rate = anomalous_validators as f64 / total_validators as f64;

        let new_level = if anomaly_rate > 0.3 || avg_bts < 0.3 {
            NetworkAlertLevel::Emergency
        } else if anomaly_rate > 0.2 || avg_bts < 0.5 {
            NetworkAlertLevel::Alert
        } else if anomaly_rate > 0.1 || avg_bts < 0.6 {
            NetworkAlertLevel::Elevated
        } else {
            NetworkAlertLevel::Normal
        };

        *self.current_alert_level.write().await = new_level.clone();

        if new_level != NetworkAlertLevel::Normal {
            warn!(
                "Network alert level: {:?} (anomaly rate: {:.1}%, avg BTS: {:.2})",
                new_level,
                anomaly_rate * 100.0,
                avg_bts
            );
        }

        new_level
    }

    pub fn validator_bts(&self, validator_id: &ValidatorId) -> Option<f64> {
        let key = format!("{:?}", validator_id.0);
        self.profiles.get(&key).map(|p| p.current_bts)
    }

    pub fn layer1_stats(&self) -> Layer1Stats {
        let mut total = 0;
        let mut in_burn_in = 0;
        let mut avg_bts = 0.0;
        let mut low_trust_count = 0;

        for entry in self.profiles.iter() {
            let p = entry.value();
            total += 1;
            if p.burn_in != BurnInState::Complete {
                in_burn_in += 1;
            } else {
                avg_bts += p.current_bts;
                if p.current_bts < 0.5 {
                    low_trust_count += 1;
                }
            }
        }

        let active = total - in_burn_in;
        Layer1Stats {
            total_validators: total,
            in_burn_in,
            active_validators: active,
            avg_bts: if active > 0 { avg_bts / active as f64 } else { 0.0 },
            low_trust_validators: low_trust_count,
        }
    }
}

#[derive(Debug, Serialize)]
pub struct Layer1Stats {
    pub total_validators: usize,
    pub in_burn_in: usize,
    pub active_validators: usize,
    pub avg_bts: f64,
    pub low_trust_validators: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_cusum_detects_shift() {
        let mut cusum = CUSUMDetector::new(100.0, 10.0, 5.0);

        // Feed normal values
        for _ in 0..20 {
            let score = cusum.update(100.0);
            assert!(score < 1.0, "Normal values should not trigger");
        }

        // Feed shifted values (mean jumped to 150ms)
        let mut triggered = false;
        for _ in 0..30 {
            let score = cusum.update(150.0);
            if score > 1.0 {
                triggered = true;
                break;
            }
        }
        assert!(triggered, "CUSUM should detect the shift to 150ms");
    }

    #[test]
    fn test_cusum_no_false_alarm_on_noise() {
        let mut cusum = CUSUMDetector::new(100.0, 20.0, 5.0);
        use rand::Rng;
        let mut rng = rand::thread_rng();

        // Feed noisy but centered data
        let mut false_alarms = 0;
        for _ in 0..100 {
            let value = 100.0 + rng.gen::<f64>() * 40.0 - 20.0; // ±20ms noise
            if cusum.update(value) > 1.0 {
                false_alarms += 1;
            }
        }
        assert!(false_alarms < 5, "Should have minimal false alarms on normal noise");
    }

    #[test]
    fn test_agreement_graph_collusion() {
        let mut graph = AgreementGraph::new(100);
        let v1 = ValidatorId([1u8; 32]);
        let v2 = ValidatorId([2u8; 32]);
        let v3 = ValidatorId([3u8; 32]);

        // v1 and v2 always agree (colluding)
        for _ in 0..50 {
            graph.record_agreement(&v1, &v2, true);
        }

        // v1 and v3 agree randomly
        for i in 0..50 {
            graph.record_agreement(&v1, &v3, i % 2 == 0);
        }

        let rate_12 = graph.agreement_rate(&v1, &v2);
        let rate_13 = graph.agreement_rate(&v1, &v3);

        assert!(rate_12 > 0.9, "v1 and v2 should have high agreement rate");
        assert!(rate_13 < 0.6, "v1 and v3 should have normal agreement rate");
    }
}
