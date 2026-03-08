/// AEGIS Layer 2 — Adaptive Fluid Consensus
///
/// The most novel mechanism. Instead of binary yes/no voting,
/// validators vote with a CONFIDENCE SCORE weighted by their BTS.
///
/// Standard PoS: trust = stake only
/// AEGIS: trust = stake × BTS × confidence
///
/// A validator who consistently catches attacks gets exponentially
/// more weight over time. A validator who misses attacks gets less.
///
/// This creates a self-improving security system.

use crate::types::{
    Transaction, ValidatorId, ValidatorVote, VoteReasoning,
    ConsensusResult, ConsensusDecision, NetworkAlertLevel, AnomalyFlag,
};
use dashmap::DashMap;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{debug, info, warn, error};
use serde::{Serialize, Deserialize};
use chrono::Utc;
use uuid::Uuid;

// ============================================================
// VOTE AGGREGATOR
// Collects votes and computes weighted confidence
// ============================================================

pub struct VoteAggregator {
    /// transaction_id -> collected votes
    pending: DashMap<Uuid, PendingVote>,
    /// How long to wait for votes before timing out
    vote_timeout_ms: u64,
}

struct PendingVote {
    transaction: Transaction,
    votes: Vec<ValidatorVote>,
    started_at: std::time::Instant,
}

impl VoteAggregator {
    pub fn new(vote_timeout_ms: u64) -> Self {
        Self {
            pending: DashMap::new(),
            vote_timeout_ms,
        }
    }

    pub fn start_vote(&self, tx: Transaction) {
        let id = tx.id;
        self.pending.insert(id, PendingVote {
            transaction: tx,
            votes: Vec::new(),
            started_at: std::time::Instant::now(),
        });
    }

    pub fn add_vote(&self, vote: ValidatorVote) -> Option<Vec<ValidatorVote>> {
        if let Some(mut pending) = self.pending.get_mut(&vote.transaction_id) {
            pending.votes.push(vote);
            // Return votes snapshot for aggregation check
            Some(pending.votes.clone())
        } else {
            None
        }
    }

    pub fn get_votes(&self, tx_id: &Uuid) -> Vec<ValidatorVote> {
        self.pending.get(tx_id)
            .map(|p| p.votes.clone())
            .unwrap_or_default()
    }

    pub fn remove(&self, tx_id: &Uuid) -> Option<Transaction> {
        self.pending.remove(tx_id).map(|(_, p)| p.transaction)
    }

    /// Clean up timed-out votes
    pub fn cleanup_timeouts(&self) -> Vec<Uuid> {
        let timeout = std::time::Duration::from_millis(self.vote_timeout_ms);
        let mut expired = Vec::new();

        self.pending.retain(|id, pending| {
            if pending.started_at.elapsed() > timeout {
                expired.push(*id);
                false
            } else {
                true
            }
        });

        expired
    }
}

// ============================================================
// FLUID CONSENSUS ENGINE
// The core algorithm: confidence-weighted voting
// ============================================================

pub struct FluidConsensus {
    /// Confirmation threshold (changes with alert level)
    confirmation_threshold: f64,
    /// Minimum participating stake required
    min_stake_participation: f64,
    /// All registered validators: id -> (stake, current_bts)
    validator_registry: Arc<RwLock<HashMap<String, ValidatorWeight>>>,
}

#[derive(Debug, Clone)]
pub struct ValidatorWeight {
    pub stake: u128,
    pub bts: f64,
    pub effective_weight: f64, // stake * bts
}

impl FluidConsensus {
    pub fn new(
        confirmation_threshold: f64,
        min_stake_participation: f64,
    ) -> Self {
        Self {
            confirmation_threshold,
            min_stake_participation,
            validator_registry: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    pub async fn register_validator(&self, id: &ValidatorId, stake: u128, bts: f64) {
        let key = format!("{:?}", id.0);
        let mut registry = self.validator_registry.write().await;
        registry.insert(key, ValidatorWeight {
            stake,
            bts,
            effective_weight: stake as f64 * bts,
        });
    }

    pub async fn update_validator_bts(&self, id: &ValidatorId, new_bts: f64) {
        let key = format!("{:?}", id.0);
        let mut registry = self.validator_registry.write().await;
        if let Some(v) = registry.get_mut(&key) {
            v.bts = new_bts;
            v.effective_weight = v.stake as f64 * new_bts;
        }
    }

    pub async fn total_effective_weight(&self) -> f64 {
        let registry = self.validator_registry.read().await;
        registry.values().map(|v| v.effective_weight).sum()
    }

    /// Core algorithm: compute weighted confidence from all votes
    ///
    /// Formula:
    /// weighted_confidence = Σ(confidence_i × bts_i × stake_i) / Σ(bts_i × stake_i)
    ///
    /// This means:
    /// - High BTS validator's vote counts more
    /// - High confidence vote counts more  
    /// - High stake validator's vote counts more
    /// - All three factors multiply together
    pub async fn compute_weighted_confidence(
        &self,
        votes: &[ValidatorVote],
        alert_level: &NetworkAlertLevel,
    ) -> WeightedResult {
        let registry = self.validator_registry.read().await;
        let total_network_weight = registry.values().map(|v| v.effective_weight).sum::<f64>();

        let min_bts = alert_level.min_bts_to_vote();

        let mut numerator = 0.0f64;
        let mut denominator = 0.0f64;
        let mut participating_weight = 0.0f64;
        let mut valid_vote_weight = 0.0f64;
        let mut invalid_vote_weight = 0.0f64;
        let mut skipped_low_bts = 0;
        let mut vote_details = Vec::new();

        for vote in votes {
            let key = format!("{:?}", vote.validator_id.0);

            if let Some(validator) = registry.get(&key) {
                if validator.bts < min_bts {
                    skipped_low_bts += 1;
                    continue;
                }

                // Weight = stake × BTS (trust-adjusted stake)
                let weight = validator.effective_weight;
                // Contribution = weight × confidence
                let contribution = weight * vote.confidence;

                numerator += contribution;
                denominator += weight;
                participating_weight += weight;

                if vote.is_valid {
                    valid_vote_weight += weight;
                } else {
                    invalid_vote_weight += weight;
                }

                vote_details.push(VoteDetail {
                    validator_key: key,
                    stake: validator.stake,
                    bts: validator.bts,
                    confidence: vote.confidence,
                    is_valid: vote.is_valid,
                    contribution,
                });
            }
        }

        let weighted_confidence = if denominator > 0.0 {
            numerator / denominator
        } else {
            0.0
        };

        let valid_weight_fraction = if participating_weight > 0.0 {
            valid_vote_weight / participating_weight
        } else {
            0.0
        };

        let stake_participation = if total_network_weight > 0.0 {
            participating_weight / total_network_weight
        } else {
            0.0
        };

        WeightedResult {
            weighted_confidence,
            valid_weight_fraction,
            stake_participation,
            participating_validators: votes.len() - skipped_low_bts,
            skipped_low_bts,
            vote_details,
        }
    }

    /// Make final consensus decision
    pub async fn decide(
        &self,
        tx_id: Uuid,
        votes: &[ValidatorVote],
        alert_level: &NetworkAlertLevel,
    ) -> ConsensusResult {
        let threshold = alert_level.confirmation_threshold();
        let result = self.compute_weighted_confidence(votes, alert_level).await;

        debug!(
            "TX {} — weighted_confidence: {:.3}, valid_fraction: {:.3}, participation: {:.1}%, threshold: {:.2}",
            tx_id,
            result.weighted_confidence,
            result.valid_weight_fraction,
            result.stake_participation * 100.0,
            threshold
        );

        // Need minimum stake participation
        let decision = if result.stake_participation < self.min_stake_participation {
            ConsensusDecision::Escalated // Not enough validators voted
        } else if result.weighted_confidence >= threshold
            && result.valid_weight_fraction > 0.5
        {
            ConsensusDecision::Confirmed
        } else if result.weighted_confidence < (1.0 - threshold)
            || result.valid_weight_fraction < 0.3
        {
            ConsensusDecision::Rejected
        } else {
            // In the grey zone — quarantine for manual review
            // This happens more in Alert/Emergency mode
            ConsensusDecision::Quarantined
        };

        if decision == ConsensusDecision::Confirmed {
            debug!("TX {} CONFIRMED (confidence: {:.3})", tx_id, result.weighted_confidence);
        } else if decision == ConsensusDecision::Rejected {
            warn!("TX {} REJECTED (confidence: {:.3})", tx_id, result.weighted_confidence);
        }

        ConsensusResult {
            transaction_id: tx_id,
            decision,
            weighted_confidence: result.weighted_confidence,
            vote_count: result.participating_validators,
            total_stake_voted: result.vote_details.iter().map(|v| v.stake).sum(),
            timestamp: Utc::now(),
        }
    }
}

#[derive(Debug)]
pub struct WeightedResult {
    pub weighted_confidence: f64,
    pub valid_weight_fraction: f64,
    pub stake_participation: f64,
    pub participating_validators: usize,
    pub skipped_low_bts: usize,
    pub vote_details: Vec<VoteDetail>,
}

#[derive(Debug, Clone, Serialize)]
pub struct VoteDetail {
    pub validator_key: String,
    pub stake: u128,
    pub bts: f64,
    pub confidence: f64,
    pub is_valid: bool,
    pub contribution: f64,
}

// ============================================================
// LAYER 2 ENGINE — ties everything together
// ============================================================

pub struct Layer2Engine {
    consensus: Arc<FluidConsensus>,
    aggregator: Arc<VoteAggregator>,
    alert_level: Arc<RwLock<NetworkAlertLevel>>,

    // Stats
    confirmed_count: std::sync::atomic::AtomicU64,
    rejected_count: std::sync::atomic::AtomicU64,
    quarantined_count: std::sync::atomic::AtomicU64,
}

impl Layer2Engine {
    pub fn new() -> Self {
        Self {
            consensus: Arc::new(FluidConsensus::new(0.67, 0.33)),
            aggregator: Arc::new(VoteAggregator::new(2000)), // 2 second vote timeout
            alert_level: Arc::new(RwLock::new(NetworkAlertLevel::Normal)),
            confirmed_count: std::sync::atomic::AtomicU64::new(0),
            rejected_count: std::sync::atomic::AtomicU64::new(0),
            quarantined_count: std::sync::atomic::AtomicU64::new(0),
        }
    }

    pub async fn register_validator(&self, id: &ValidatorId, stake: u128, bts: f64) {
        self.consensus.register_validator(id, stake, bts).await;
    }

    pub async fn update_bts(&self, id: &ValidatorId, bts: f64) {
        self.consensus.update_validator_bts(id, bts).await;
    }

    pub fn submit_transaction(&self, tx: Transaction) {
        self.aggregator.start_vote(tx);
    }

    pub async fn submit_vote(&self, vote: ValidatorVote) -> Option<ConsensusResult> {
        let tx_id = vote.transaction_id;
        let votes = self.aggregator.add_vote(vote)?;

        // Check if we have enough votes to decide
        let alert_level = self.alert_level.read().await;
        let total_weight = self.consensus.total_effective_weight().await;

        // Compute current participating weight
        let result = self.consensus
            .compute_weighted_confidence(&votes, &alert_level)
            .await;

        // Early decision if we already have strong consensus
        // This speeds things up — don't wait for all validators
        let can_decide_early = result.stake_participation >= 0.67
            && (result.weighted_confidence >= alert_level.confirmation_threshold()
                || result.weighted_confidence < 0.15);

        if can_decide_early {
            let decision = self.consensus.decide(tx_id, &votes, &alert_level).await;

            match &decision.decision {
                ConsensusDecision::Confirmed => {
                    self.confirmed_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                }
                ConsensusDecision::Rejected => {
                    self.rejected_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                }
                ConsensusDecision::Quarantined => {
                    self.quarantined_count.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
                }
                _ => {}
            }

            self.aggregator.remove(&tx_id);
            return Some(decision);
        }

        None // Still collecting votes
    }

    pub async fn finalize_vote(&self, tx_id: Uuid) -> Option<ConsensusResult> {
        let votes = self.aggregator.get_votes(&tx_id);
        if votes.is_empty() { return None; }

        let alert_level = self.alert_level.read().await;
        let decision = self.consensus.decide(tx_id, &votes, &alert_level).await;

        self.aggregator.remove(&tx_id);
        Some(decision)
    }

    pub async fn set_alert_level(&self, level: NetworkAlertLevel) {
        *self.alert_level.write().await = level;
    }

    pub fn stats(&self) -> Layer2Stats {
        use std::sync::atomic::Ordering;
        let confirmed = self.confirmed_count.load(Ordering::Relaxed);
        let rejected = self.rejected_count.load(Ordering::Relaxed);
        let quarantined = self.quarantined_count.load(Ordering::Relaxed);
        let total = confirmed + rejected + quarantined;

        Layer2Stats {
            confirmed,
            rejected,
            quarantined,
            total,
            confirmation_rate: if total > 0 { confirmed as f64 / total as f64 } else { 0.0 },
            rejection_rate: if total > 0 { rejected as f64 / total as f64 } else { 0.0 },
        }
    }
}

#[derive(Debug, Serialize)]
pub struct Layer2Stats {
    pub confirmed: u64,
    pub rejected: u64,
    pub quarantined: u64,
    pub total: u64,
    pub confirmation_rate: f64,
    pub rejection_rate: f64,
}

// ============================================================
// ZK BEHAVIORAL PROOF (simplified Schnorr-style proof)
// Allows a validator to prove "my BTS >= threshold"
// without revealing their actual BTS or behavioral data
// ============================================================

/// In production this would use proper ZK-SNARK circuits (e.g. via arkworks)
/// This is a simplified commitment scheme for illustration

pub struct BTSCommitment {
    pub commitment: [u8; 32],
    pub public_threshold: f64,
}

pub struct BTSProof {
    pub commitment: [u8; 32],
    pub challenge_response: [u8; 32],
    pub threshold: f64,
}

impl BTSProof {
    /// Create proof that bts >= threshold, without revealing bts
    pub fn create(bts: f64, threshold: f64, validator_secret: &[u8; 32]) -> Option<Self> {
        if bts < threshold {
            return None; // Can't prove what's not true
        }

        // Simplified commitment: H(bts || secret || threshold)
        // In production: use bulletproofs for range proofs
        let mut hasher = blake3::Hasher::new();
        hasher.update(&bts.to_le_bytes());
        hasher.update(validator_secret);
        hasher.update(&threshold.to_le_bytes());
        let commitment: [u8; 32] = hasher.finalize().into();

        // Challenge-response (simplified)
        let mut resp_hasher = blake3::Hasher::new();
        resp_hasher.update(&commitment);
        resp_hasher.update(validator_secret);
        let challenge_response: [u8; 32] = resp_hasher.finalize().into();

        Some(Self {
            commitment,
            challenge_response,
            threshold,
        })
    }

    /// Verify proof is internally consistent (not that it proves BTS >= threshold
    /// — in production the ZK circuit would do that)
    pub fn verify_consistency(&self) -> bool {
        // In production: verify the ZK proof using the circuit
        // Here: just check the proof is well-formed
        self.commitment != [0u8; 32] && self.challenge_response != [0u8; 32]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_fluid_consensus_basic() {
        let consensus = FluidConsensus::new(0.67, 0.33);

        // Register 3 validators
        let v1 = ValidatorId([1u8; 32]);
        let v2 = ValidatorId([2u8; 32]);
        let v3 = ValidatorId([3u8; 32]);

        consensus.register_validator(&v1, 1000, 0.9).await;
        consensus.register_validator(&v2, 1000, 0.85).await;
        consensus.register_validator(&v3, 1000, 0.7).await;

        // All three vote valid with high confidence
        let tx_id = Uuid::new_v4();
        let votes = vec![
            ValidatorVote {
                validator_id: v1.clone(),
                transaction_id: tx_id,
                confidence: 0.95,
                is_valid: true,
                timestamp: Utc::now(),
                reasoning: VoteReasoning {
                    layer0_passed: true,
                    layer1_score: 0.9,
                    anomaly_flags: vec![],
                    bts_at_vote_time: 0.9,
                },
            },
            ValidatorVote {
                validator_id: v2.clone(),
                transaction_id: tx_id,
                confidence: 0.88,
                is_valid: true,
                timestamp: Utc::now(),
                reasoning: VoteReasoning {
                    layer0_passed: true,
                    layer1_score: 0.85,
                    anomaly_flags: vec![],
                    bts_at_vote_time: 0.85,
                },
            },
            ValidatorVote {
                validator_id: v3.clone(),
                transaction_id: tx_id,
                confidence: 0.75,
                is_valid: true,
                timestamp: Utc::now(),
                reasoning: VoteReasoning {
                    layer0_passed: true,
                    layer1_score: 0.7,
                    anomaly_flags: vec![],
                    bts_at_vote_time: 0.7,
                },
            },
        ];

        let result = consensus.decide(tx_id, &votes, &NetworkAlertLevel::Normal).await;
        assert_eq!(result.decision, ConsensusDecision::Confirmed);
    }

    #[tokio::test]
    async fn test_low_bts_validator_ignored_in_alert_mode() {
        let consensus = FluidConsensus::new(0.85, 0.33);

        let v1 = ValidatorId([1u8; 32]);
        let v2 = ValidatorId([2u8; 32]);

        // v1 high BTS, v2 low BTS
        consensus.register_validator(&v1, 1000, 0.9).await;
        consensus.register_validator(&v2, 5000, 0.2).await; // more stake but low BTS

        let tx_id = Uuid::new_v4();
        let votes = vec![
            ValidatorVote {
                validator_id: v1.clone(),
                transaction_id: tx_id,
                confidence: 0.95,
                is_valid: true,
                timestamp: Utc::now(),
                reasoning: VoteReasoning {
                    layer0_passed: true,
                    layer1_score: 0.9,
                    anomaly_flags: vec![],
                    bts_at_vote_time: 0.9,
                },
            },
            ValidatorVote {
                validator_id: v2.clone(),
                transaction_id: tx_id,
                confidence: 0.9,
                is_valid: false, // malicious validator voting invalid
                timestamp: Utc::now(),
                reasoning: VoteReasoning {
                    layer0_passed: true,
                    layer1_score: 0.2,
                    anomaly_flags: vec![AnomalyFlag::TemporalAnomaly],
                    bts_at_vote_time: 0.2,
                },
            },
        ];

        // In emergency mode, v2's vote should be ignored (BTS too low)
        let result = consensus
            .compute_weighted_confidence(&votes, &NetworkAlertLevel::Emergency)
            .await;

        assert_eq!(result.skipped_low_bts, 1, "Low BTS validator should be skipped");
        assert_eq!(result.participating_validators, 1, "Only 1 valid validator");
    }

    #[test]
    fn test_zk_bts_proof() {
        let secret = [42u8; 32];
        let bts = 0.85f64;
        let threshold = 0.7f64;

        let proof = BTSProof::create(bts, threshold, &secret);
        assert!(proof.is_some(), "Should create proof when BTS >= threshold");
        assert!(proof.unwrap().verify_consistency());

        // Should not create proof when BTS < threshold
        let bad_proof = BTSProof::create(0.5, threshold, &secret);
        assert!(bad_proof.is_none(), "Should not create proof when BTS < threshold");
    }
}
