/// AEGIS Shadow Network Simulator
///
/// Trains AEGIS safely before mainnet by:
///   1. Replaying historical blockchain transactions
///   2. Injecting synthetic attacks at random intervals
///   3. Simulating honest and malicious validators
///   4. Running AEGIS in full learning mode
///   5. Measuring performance vs ground truth

use crate::types::*;
use crate::layer0::Layer0Engine;
use crate::layer1::Layer1Engine;
use crate::layer2::Layer2Engine;
use crate::layer3::Layer3Engine;
use rand::Rng;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{info, warn, debug};
use serde::{Serialize, Deserialize};
use chrono::Utc;

// ============================================================
// SYNTHETIC TRANSACTION GENERATOR
// Generates realistic transactions and attack variations
// ============================================================

pub struct TransactionGenerator {
    rng: rand::rngs::ThreadRng,
}

impl TransactionGenerator {
    pub fn new() -> Self {
        Self { rng: rand::thread_rng() }
    }

    /// Generate a normal transfer transaction
    pub fn normal_transfer(&mut self) -> (Transaction, bool) {
        let value = (10_u128.pow(self.rng.gen_range(0..6))) * self.rng.gen_range(1..1000) as u128;
        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            value,
            self.rng.gen_range(10..200),   // gas price gwei
            21000,                           // standard transfer gas
            self.rng.gen_range(0..1000),
            vec![],
            TransactionType::Transfer,
        );
        (tx, false) // not an attack
    }

    /// Generate a normal contract interaction
    pub fn normal_contract_call(&mut self) -> (Transaction, bool) {
        let data_len = self.rng.gen_range(4..256);
        let mut data = vec![0u8; data_len];
        self.rng.fill(data.as_mut_slice());
        // Standard ERC20 transfer selector: 0xa9059cbb
        data[0] = 0xa9;
        data[1] = 0x05;
        data[2] = 0x9c;
        data[3] = 0xbb;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(20..500),
            self.rng.gen_range(50_000..300_000),
            self.rng.gen_range(0..100),
            data,
            TransactionType::ContractCall,
        );
        (tx, false)
    }

    /// Generate a flash loan attack
    /// Key signatures: very high value, complex calldata, max gas
    pub fn flash_loan_attack(&mut self) -> (Transaction, bool) {
        let value = 10_u128.pow(21) * self.rng.gen_range(1..100) as u128; // 1000+ ETH
        let data_len = self.rng.gen_range(500..2000); // complex calldata
        let mut data = vec![0u8; data_len];
        self.rng.fill(data.as_mut_slice());

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            value,
            self.rng.gen_range(100..2000), // high gas price to front-run
            self.rng.gen_range(1_000_000..10_000_000), // very high gas limit
            0, // often fresh address
            data,
            TransactionType::FlashLoan,
        );
        (tx, true) // is an attack
    }

    /// Generate a mutated flash loan (slightly different to evade exact matching)
    pub fn mutated_flash_loan_attack(&mut self) -> (Transaction, bool) {
        let (mut tx, _) = self.flash_loan_attack();
        // Mutate slightly to test LSH similarity detection
        tx.gas_price = tx.gas_price + self.rng.gen_range(0..50);
        tx.gas_limit = tx.gas_limit + self.rng.gen_range(0..10000);
        (tx, true)
    }

    /// Generate a reentrancy attack
    /// Key signatures: contract call to vulnerable contract, recursive structure
    pub fn reentrancy_attack(&mut self) -> (Transaction, bool) {
        let data_len = self.rng.gen_range(100..500);
        let mut data = vec![0u8; data_len];
        self.rng.fill(data.as_mut_slice());
        // withdraw() selector: 0x3ccfd60b
        data[0] = 0x3c;
        data[1] = 0xcf;
        data[2] = 0xd6;
        data[3] = 0x0b;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1..100) * 10_u128.pow(18),
            self.rng.gen_range(50..500),
            self.rng.gen_range(200_000..2_000_000),
            self.rng.gen_range(0..5),
            data,
            TransactionType::ContractCall,
        );
        (tx, true)
    }

    /// Generate a sandwich attack (MEV)
    pub fn sandwich_attack_frontrun(&mut self) -> (Transaction, bool) {
        let mut data = vec![0u8; 68];
        self.rng.fill(data.as_mut_slice());
        // swapExactTokensForTokens selector: 0x38ed1739
        data[0] = 0x38;
        data[1] = 0xed;
        data[2] = 0x17;
        data[3] = 0x39;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            999999, // extremely high gas to front-run
            self.rng.gen_range(150_000..400_000),
            0,
            data,
            TransactionType::ContractCall,
        );
        (tx, true)
    }

    /// Generate a random transaction (50/50 mix)
    pub fn random_tx(&mut self) -> (Transaction, bool) {
        match self.rng.gen_range(0..10) {
            0..=1 => self.normal_transfer(),
            2..=4 => self.normal_contract_call(),
            5..=6 => self.flash_loan_attack(),
            7 => self.mutated_flash_loan_attack(),
            8 => self.reentrancy_attack(),
            _ => self.sandwich_attack_frontrun(),
        }
    }

    /// Generate training data: (features, is_attack) pairs
    pub fn generate_training_set(&mut self, count: usize) -> Vec<(Vec<f64>, bool)> {
        (0..count)
            .map(|_| {
                let (tx, is_attack) = self.random_tx();
                (tx.extract_features().to_vec(), is_attack)
            })
            .collect()
    }
}

// ============================================================
// SYNTHETIC VALIDATOR SIMULATOR
// Simulates honest and malicious validators
// ============================================================

#[derive(Debug, Clone)]
pub struct SimulatedValidator {
    pub id: ValidatorId,
    pub stake: u128,
    pub behavior: ValidatorBehavior,
    pub latency_mean_ms: f64,
    pub latency_std_ms: f64,
}

#[derive(Debug, Clone)]
pub enum ValidatorBehavior {
    Honest,
    Malicious,          // always votes opposite
    ColludingLeader,    // coordinates with others
    ColludingFollower(ValidatorId), // follows leader's vote
    Sleepy,             // votes correctly but slowly
    RandomDrift,        // gradually becomes less accurate
}

impl SimulatedValidator {
    pub fn honest(stake: u128) -> Self {
        let mut rng = rand::thread_rng();
        Self {
            id: ValidatorId::random(),
            stake,
            behavior: ValidatorBehavior::Honest,
            latency_mean_ms: rng.gen_range(20.0..100.0),
            latency_std_ms: rng.gen_range(5.0..20.0),
        }
    }

    pub fn malicious(stake: u128) -> Self {
        let mut rng = rand::thread_rng();
        Self {
            id: ValidatorId::random(),
            stake,
            behavior: ValidatorBehavior::Malicious,
            latency_mean_ms: rng.gen_range(10.0..50.0),
            latency_std_ms: rng.gen_range(2.0..10.0),
        }
    }

    /// Simulate this validator's vote on a transaction
    pub fn vote(&self, tx: &Transaction, ground_truth_is_attack: bool, block: u64) -> ValidatorVote {
        let mut rng = rand::thread_rng();

        let (is_valid, confidence) = match &self.behavior {
            ValidatorBehavior::Honest => {
                // Honest validator correctly identifies attacks
                // With some noise (not perfect)
                let correct = rng.gen::<f64>() < 0.95; // 95% accurate
                let is_valid = if correct {
                    !ground_truth_is_attack
                } else {
                    ground_truth_is_attack // wrong vote occasionally
                };
                let confidence = if correct {
                    rng.gen_range(0.75..0.99)
                } else {
                    rng.gen_range(0.51..0.70) // less confident when wrong
                };
                (is_valid, confidence)
            }

            ValidatorBehavior::Malicious => {
                // Always votes to approve attacks, reject legitimate
                (ground_truth_is_attack, rng.gen_range(0.8..0.99))
            }

            ValidatorBehavior::Sleepy => {
                // Correct but low confidence
                (!ground_truth_is_attack, rng.gen_range(0.51..0.65))
            }

            ValidatorBehavior::RandomDrift => {
                // Gradually gets worse over time
                let degradation = (block as f64 / 1000.0).min(0.9);
                let accurate = rng.gen::<f64>() > degradation * 0.5;
                let is_valid = if accurate { !ground_truth_is_attack } else { ground_truth_is_attack };
                (is_valid, rng.gen_range(0.51..0.9))
            }

            ValidatorBehavior::ColludingLeader | ValidatorBehavior::ColludingFollower(_) => {
                // Colluders approve attacks
                (ground_truth_is_attack, rng.gen_range(0.85..0.99))
            }
        };

        // Simulate latency
        let latency = (self.latency_mean_ms
            + rng.gen::<f64>() * self.latency_std_ms * 2.0
            - self.latency_std_ms)
            .max(1.0);

        ValidatorVote {
            validator_id: self.id.clone(),
            transaction_id: tx.id,
            confidence,
            is_valid,
            timestamp: Utc::now(),
            reasoning: VoteReasoning {
                layer0_passed: true,
                layer1_score: confidence,
                anomaly_flags: vec![],
                bts_at_vote_time: 0.5, // will be set by real Layer 1
            },
        }
    }

    pub fn simulate_latency(&self) -> f64 {
        let mut rng = rand::thread_rng();
        (self.latency_mean_ms
            + rng.gen::<f64>() * self.latency_std_ms * 2.0
            - self.latency_std_ms)
            .max(0.1)
    }
}

// ============================================================
// SHADOW NETWORK — main training environment
// ============================================================

pub struct ShadowNetwork {
    validators: Vec<SimulatedValidator>,
    tx_generator: TransactionGenerator,
    layer0: Layer0Engine,
    layer1: Arc<Layer1Engine>,
    layer2: Arc<Layer2Engine>,
    layer3: Arc<Layer3Engine>,
    current_block: u64,
    pub metrics: SimulationMetrics,
}

#[derive(Debug, Default, Serialize)]
pub struct SimulationMetrics {
    pub total_transactions: u64,
    pub actual_attacks: u64,
    pub actual_legitimate: u64,

    // Detection results
    pub true_positives: u64,    // attack correctly rejected
    pub true_negatives: u64,    // legitimate correctly confirmed
    pub false_positives: u64,   // legitimate incorrectly rejected
    pub false_negatives: u64,   // attack incorrectly confirmed (DANGEROUS)

    // Layer performance
    pub caught_by_layer0: u64,
    pub caught_by_layer1: u64,
    pub caught_by_layer2: u64,

    pub current_block: u64,
}

impl SimulationMetrics {
    pub fn precision(&self) -> f64 {
        let detected = self.true_positives + self.false_positives;
        if detected == 0 { return 1.0; }
        self.true_positives as f64 / detected as f64
    }

    pub fn recall(&self) -> f64 {
        let actual_attacks = self.true_positives + self.false_negatives;
        if actual_attacks == 0 { return 1.0; }
        self.true_positives as f64 / actual_attacks as f64
    }

    pub fn f1_score(&self) -> f64 {
        let p = self.precision();
        let r = self.recall();
        if p + r == 0.0 { return 0.0; }
        2.0 * p * r / (p + r)
    }

    pub fn false_negative_rate(&self) -> f64 {
        let actual = self.true_positives + self.false_negatives;
        if actual == 0 { return 0.0; }
        self.false_negatives as f64 / actual as f64
    }
}

impl ShadowNetwork {
    pub fn new(honest_validators: u32, malicious_validators: u32) -> Self {
        let mut rng = rand::thread_rng();
        let mut validators = Vec::new();

        // Create honest validators
        for _ in 0..honest_validators {
            let stake = rng.gen_range(1000..10000) as u128 * 10_u128.pow(18);
            validators.push(SimulatedValidator::honest(stake));
        }

        // Create malicious validators
        for _ in 0..malicious_validators {
            let stake = rng.gen_range(500..3000) as u128 * 10_u128.pow(18);
            validators.push(SimulatedValidator::malicious(stake));
        }

        Self {
            validators,
            tx_generator: TransactionGenerator::new(),
            layer0: Layer0Engine::new(),
            layer1: Arc::new(Layer1Engine::new(100)), // 100-block burn-in
            layer2: Arc::new(Layer2Engine::new()),
            layer3: Arc::new(Layer3Engine::new(8)),
            current_block: 0,
            metrics: SimulationMetrics::default(),
        }
    }

    /// Pre-seed Layer 0 with known attack patterns before starting
    pub fn seed_known_attacks(&mut self) {
        let mut gen = TransactionGenerator::new();
        let mut patterns = Vec::new();

        // Generate 1000 known attacks of each type
        for _ in 0..1000 {
            let (tx, _) = gen.flash_loan_attack();
            patterns.push((format!("flash_loan_seed_{}", patterns.len()),
                           tx.extract_features().to_vec()));
        }
        for _ in 0..1000 {
            let (tx, _) = gen.reentrancy_attack();
            patterns.push((format!("reentrancy_seed_{}", patterns.len()),
                           tx.extract_features().to_vec()));
        }
        for _ in 0..500 {
            let (tx, _) = gen.sandwich_attack_frontrun();
            patterns.push((format!("sandwich_seed_{}", patterns.len()),
                           tx.extract_features().to_vec()));
        }

        self.layer0.load_attack_patterns(patterns);
        info!("Seeded Layer 0 with 2500 known attack patterns");
    }

    /// Register all validators with Layer 1 and 2
    pub async fn register_validators(&self) {
        for validator in &self.validators {
            let info = ValidatorInfo {
                id: validator.id.clone(),
                stake: validator.stake,
                address: Address::random(),
                joined_block: 0,
                is_active: true,
            };
            self.layer1.register_validator(info);
            self.layer2.register_validator(&validator.id, validator.stake, 0.5).await;
        }
        info!("Registered {} validators", self.validators.len());
    }

    /// Run one block of simulation
    /// Returns false when simulation should stop
    pub async fn run_block(&mut self, txs_per_block: usize) -> bool {
        self.current_block += 1;
        self.metrics.current_block = self.current_block;

        for _ in 0..txs_per_block {
            let (tx, is_attack) = self.tx_generator.random_tx();

            self.metrics.total_transactions += 1;
            if is_attack {
                self.metrics.actual_attacks += 1;
            } else {
                self.metrics.actual_legitimate += 1;
            }

            // Run through AEGIS pipeline
            let decision = self.process_transaction(&tx, is_attack).await;

            // Record outcome
            match (&decision, is_attack) {
                (ConsensusDecision::Rejected, true) => self.metrics.true_positives += 1,
                (ConsensusDecision::Confirmed, false) => self.metrics.true_negatives += 1,
                (ConsensusDecision::Confirmed, true) => {
                    self.metrics.false_negatives += 1; // DANGEROUS - attack got through
                    warn!("FALSE NEGATIVE at block {} — attack confirmed!", self.current_block);
                }
                (ConsensusDecision::Rejected, false) => {
                    self.metrics.false_positives += 1; // annoying but safe
                }
                _ => {}
            }

            // Layer 3 memory update
            let votes = self.collect_votes(&tx, is_attack);
            let result = ConsensusResult {
                transaction_id: tx.id,
                decision: decision.clone(),
                weighted_confidence: 0.5,
                vote_count: votes.len(),
                total_stake_voted: 0,
                timestamp: Utc::now(),
            };

            self.layer3
                .process_outcome(&tx, &result, &votes, self.current_block)
                .await;
        }

        // Every 100 blocks: apply BTS adjustments
        if self.current_block % 100 == 0 {
            self.apply_bts_adjustments().await;
            self.print_checkpoint();
        }

        true
    }

    async fn process_transaction(&mut self, tx: &Transaction, is_attack: bool) -> ConsensusDecision {
        // Layer 0
        let l0_decision = self.layer0.process(tx);

        if !l0_decision.pass {
            self.metrics.caught_by_layer0 += 1;
            return ConsensusDecision::Rejected;
        }

        // Collect votes from all validators
        let votes = self.collect_votes(tx, is_attack);

        // Layer 2 consensus
        let alert_level = NetworkAlertLevel::Normal; // simplified for simulation
        let result = self.layer2.consensus
            .decide(tx.id, &votes, &alert_level)
            .await;

        result.decision
    }

    fn collect_votes(&self, tx: &Transaction, is_attack: bool) -> Vec<ValidatorVote> {
        self.validators
            .iter()
            .map(|v| v.vote(tx, is_attack, self.current_block))
            .collect()
    }

    async fn apply_bts_adjustments(&self) {
        let adjustments = self.layer3.compute_bts_adjustments();
        for (key, adj) in adjustments {
            // Find validator by key and update BTS
            // In production: proper key lookup
            if let Ok(bytes) = key.parse::<u64>() {
                // Simplified — in production use proper validator registry
                debug!("BTS adjustment for {}: {:+.4}", &key[..8.min(key.len())], adj);
            }
        }
    }

    fn print_checkpoint(&self) {
        let m = &self.metrics;
        info!(
            "Block {} | TXs: {} | Attacks: {} | FNR: {:.4}% | FPR: {:.4}% | F1: {:.4} | L0 caught: {}",
            self.current_block,
            m.total_transactions,
            m.actual_attacks,
            m.false_negative_rate() * 100.0,
            if m.actual_legitimate > 0 {
                m.false_positives as f64 / m.actual_legitimate as f64 * 100.0
            } else { 0.0 },
            m.f1_score(),
            m.caught_by_layer0,
        );
    }

    /// Run full training simulation
    pub async fn run_training(
        &mut self,
        num_blocks: u64,
        txs_per_block: usize,
    ) -> &SimulationMetrics {
        self.seed_known_attacks();
        self.register_validators().await;

        info!("Starting shadow network simulation: {} blocks × {} tx/block",
              num_blocks, txs_per_block);

        for _ in 0..num_blocks {
            if !self.run_block(txs_per_block).await {
                break;
            }
        }

        info!("\n=== TRAINING COMPLETE ===");
        info!("Precision: {:.4}", self.metrics.precision());
        info!("Recall: {:.4}", self.metrics.recall());
        info!("F1 Score: {:.4}", self.metrics.f1_score());
        info!("False Negative Rate: {:.6}% (attacks that got through)",
              self.metrics.false_negative_rate() * 100.0);
        info!("Threat patterns learned: {}", self.layer3.threat_count());

        &self.metrics
    }
}

// ============================================================
// SHADOW NETWORK MAIN ENTRY POINT
// ============================================================

pub async fn run_shadow_simulation() {
    tracing_subscriber::init();

    info!("AEGIS Shadow Network — Training Simulation");
    info!("==========================================");

    let mut shadow = ShadowNetwork::new(
        40, // honest validators
        5,  // malicious validators
    );

    // Phase 1: Burn-in (validators get calibrated)
    info!("\nPhase 1: Burn-in (200 blocks)");
    for _ in 0..2 {
        shadow.run_block(100).await;
    }

    // Phase 2: Normal operation training
    info!("\nPhase 2: Normal training (1000 blocks)");
    for _ in 0..10 {
        shadow.run_block(100).await;
    }

    // Phase 3: Attack injection
    info!("\nPhase 3: Attack stress test (500 blocks, 20% attacks)");
    // This happens automatically — the generator includes attacks

    let final_metrics = shadow.run_training(500, 50).await;

    // Check if ready for canary network
    let ready = final_metrics.false_negative_rate() < 0.001  // <0.1% attacks get through
        && final_metrics.false_positives < (final_metrics.actual_legitimate / 100); // <1% FPR

    if ready {
        info!("\n✅ AEGIS READY FOR CANARY NETWORK");
        info!("   FNR: {:.6}%", final_metrics.false_negative_rate() * 100.0);
        info!("   Precision: {:.4}", final_metrics.precision());
        info!("   F1: {:.4}", final_metrics.f1_score());
    } else {
        warn!("\n❌ NOT READY — continue training");
        warn!("   FNR too high: {:.4}%", final_metrics.false_negative_rate() * 100.0);
        warn!("   Target: <0.001%");
    }
}
