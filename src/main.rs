/// AEGIS Node — Main entry point
///
/// Wires all four layers together into a complete security pipeline:
/// Transaction → Layer 0 (reflex) → Layer 1 (behavior) → Layer 2 (consensus) → Layer 3 (memory)

use aegis::types::*;
use aegis::layer0::Layer0Engine;
use aegis::layer1::Layer1Engine;
use aegis::layer2::Layer2Engine;
use aegis::layer3::Layer3Engine;
use std::sync::Arc;
use tokio::sync::{Mutex, RwLock};
use tracing::{info, warn, error};

#[tokio::main]
async fn main() {
    // Initialize logging
    tracing_subscriber::fmt()
        .with_max_level(tracing::Level::INFO)
        .init();

    info!("╔══════════════════════════════════════════════════╗");
    info!("║        AEGIS Security System — Starting          ║");
    info!("║  Adaptive Evolutionary Guard w/ Integrated Sec   ║");
    info!("╚══════════════════════════════════════════════════╝");

    // Boot the AEGIS pipeline
    let node = AegisNode::new().await;
    node.run().await;
}

pub struct AegisNode {
    layer0: Mutex<Layer0Engine>,
    layer1: Arc<Layer1Engine>,
    layer2: Arc<Layer2Engine>,
    layer3: Arc<Layer3Engine>,
    alert_level: RwLock<NetworkAlertLevel>,
    block_height: std::sync::atomic::AtomicU64,
}

impl AegisNode {
    pub async fn new() -> Arc<Self> {
        let node = Arc::new(Self {
            layer0: Mutex::new(Layer0Engine::new()),
            layer1: Arc::new(Layer1Engine::new(1000)), // 1000-block burn-in on mainnet
            layer2: Arc::new(Layer2Engine::new()),
            layer3: Arc::new(Layer3Engine::new(8)),
            alert_level: RwLock::new(NetworkAlertLevel::Normal),
            block_height: std::sync::atomic::AtomicU64::new(0),
        });

        info!("AEGIS node initialized");
        info!("Layer 0: Bloom filter + LSH + Velocity tracking");
        info!("Layer 1: CUSUM behavioral scoring + collusion detection");
        info!("Layer 2: Fluid confidence consensus");
        info!("Layer 3: Immunological memory + continuous learning");

        node
    }

    /// Process a single transaction through the full AEGIS pipeline
    pub async fn process_transaction(&self, tx: Transaction) -> ConsensusDecision {
        let start = std::time::Instant::now();

        // ====================================================
        // LAYER 0 — Reflex (<1ms)
        // ====================================================
        let l0 = self.layer0.lock().await;
        let l0_decision = l0.process(&tx);
        drop(l0);

        if !l0_decision.pass {
            let elapsed = start.elapsed().as_micros();
            info!(
                "TX {} REJECTED by Layer 0 in {}μs — {:?}",
                tx.id, elapsed, l0_decision.reason
            );
            return ConsensusDecision::Rejected;
        }

        // ====================================================
        // LAYER 1 — Behavioral scoring (1-10ms)
        // Scores the transaction from each validator's perspective
        // ====================================================
        let alert_level = self.alert_level.read().await.clone();

        // In a real node, votes come from the network
        // Here we simulate the scoring step
        let layer1_anomaly = self.layer3
            .anomaly_score(&tx.extract_features().to_vec())
            .await;

        if layer1_anomaly > 10.0 && alert_level != NetworkAlertLevel::Normal {
            warn!("TX {} has anomaly score {:.1} — escalating", tx.id, layer1_anomaly);
        }

        // ====================================================
        // LAYER 2 — Consensus (collect votes, decide)
        // In production: votes arrive from network peers
        // ====================================================
        self.layer2.submit_transaction(tx.clone());

        // Wait for consensus (in production: async vote collection)
        // For demo: immediate finalization
        let result = match self.layer2.finalize_vote(tx.id).await {
            Some(r) => r,
            None => ConsensusResult {
                transaction_id: tx.id,
                decision: ConsensusDecision::Escalated,
                weighted_confidence: 0.0,
                vote_count: 0,
                total_stake_voted: 0,
                timestamp: chrono::Utc::now(),
            },
        };

        let elapsed = start.elapsed().as_millis();
        info!(
            "TX {} → {:?} in {}ms (confidence: {:.3}, alert: {:?})",
            tx.id, result.decision, elapsed, result.weighted_confidence, alert_level
        );

        result.decision
    }

    /// Update network alert level — called every block
    pub async fn update_security_posture(&self) {
        let new_level = self.layer1.update_alert_level().await;
        *self.alert_level.write().await = new_level.clone();
        self.layer2.set_alert_level(new_level).await;
    }

    /// End-of-block processing
    pub async fn finalize_block(&self, confirmed_txs: Vec<(Transaction, Vec<ValidatorVote>)>) {
        let block = self.block_height.fetch_add(1, std::sync::atomic::Ordering::SeqCst);

        for (tx, votes) in confirmed_txs {
            // Determine outcome based on consensus
            // Layer 3 learns from every confirmed/rejected transaction
        }

        // Drain any new threat patterns and broadcast to peers
        let broadcasts = self.layer3.drain_broadcasts().await;
        if !broadcasts.is_empty() {
            info!("Broadcasting {} new threat patterns to peers", broadcasts.len());
            // In production: p2p broadcast to all connected nodes
        }

        // Periodic BTS adjustments (every 100 blocks)
        if block % 100 == 0 {
            let adjustments = self.layer3.compute_bts_adjustments();
            for (_validator_key, adj) in &adjustments {
                // Apply adjustments to Layer 2 weights
                if adj.abs() > 0.001 {
                    // layer2.update_bts(validator_id, new_bts).await;
                }
            }
            info!("Applied BTS adjustments to {} validators", adjustments.len());
        }

        // Update alert level
        self.update_security_posture().await;

        // Print stats every 10 blocks
        if block % 10 == 0 {
            self.print_stats().await;
        }
    }

    async fn print_stats(&self) {
        let l0_stats = {
            let l0 = self.layer0.lock().await;
            l0.stats()
        };
        let l1_stats = self.layer1.layer1_stats();
        let l2_stats = self.layer2.stats();
        let l3_stats = self.layer3.layer3_stats();
        let alert = self.alert_level.read().await.clone();

        info!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
        info!("Block {}", self.block_height.load(std::sync::atomic::Ordering::Relaxed));
        info!("Alert Level: {:?}", alert);
        info!("Layer 0 │ Processed: {} │ Rejected: {} │ FPR: {:.6}",
              l0_stats.total_processed, l0_stats.rejected, l0_stats.bloom_fpr);
        info!("Layer 1 │ Validators: {} │ Avg BTS: {:.3} │ Low Trust: {}",
              l1_stats.active_validators, l1_stats.avg_bts, l1_stats.low_trust_validators);
        info!("Layer 2 │ Confirmed: {} │ Rejected: {} │ Quarantined: {}",
              l2_stats.confirmed, l2_stats.rejected, l2_stats.quarantined);
        info!("Layer 3 │ Patterns learned: {} │ Validator accuracy: {:.3}",
              l3_stats.threat_patterns_learned, l3_stats.avg_validator_accuracy);
        info!("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━");
    }

    pub async fn run(self: Arc<Self>) {
        info!("AEGIS node running. Waiting for transactions...");

        // In production: connect to p2p network, listen for transactions
        // For demo: run a quick self-test

        info!("\nRunning self-test with synthetic transactions...");

        let mut gen = aegis::shadow::TransactionGenerator::new();

        let mut confirmed = 0;
        let mut rejected = 0;

        for i in 0..20 {
            let (tx, attack_type) = if i % 3 == 0 {
                gen.flash_loan_attack()
            } else if i % 5 == 0 {
                gen.reentrancy_attack()
            } else {
                gen.normal_transfer()
            };

            let label = if attack_type.is_some() { "ATTACK" } else { "LEGIT " };
            let decision = self.process_transaction(tx).await;

            match decision {
                ConsensusDecision::Confirmed => confirmed += 1,
                ConsensusDecision::Rejected => rejected += 1,
                _ => {}
            }

            info!("  [{}] → {:?}", label, decision);
        }

        info!("\nSelf-test complete: {} confirmed, {} rejected", confirmed, rejected);
        info!("To train properly: run `aegis-shadow` first");
    }
}
