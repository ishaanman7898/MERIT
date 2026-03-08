use serde::{Deserialize, Serialize};
use uuid::Uuid;
use chrono::{DateTime, Utc};
use std::collections::HashMap;

// ============================================================
// CORE TRANSACTION TYPES
// ============================================================

/// A raw transaction submitted to the network
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Transaction {
    pub id: Uuid,
    pub sender: Address,
    pub recipient: Address,
    pub value: u128,           // in smallest unit (like lamports)
    pub gas_price: u64,
    pub gas_limit: u64,
    pub nonce: u64,
    pub data: Vec<u8>,         // contract call data
    pub signature: Signature,
    pub timestamp: DateTime<Utc>,
    pub tx_type: TransactionType,
}

impl Transaction {
    pub fn new(
        sender: Address,
        recipient: Address,
        value: u128,
        gas_price: u64,
        gas_limit: u64,
        nonce: u64,
        data: Vec<u8>,
        tx_type: TransactionType,
    ) -> Self {
        Self {
            id: Uuid::new_v4(),
            sender,
            recipient,
            value,
            gas_price,
            gas_limit,
            nonce,
            data,
            signature: Signature::default(),
            timestamp: Utc::now(),
            tx_type,
        }
    }

    /// Compute the behavioral fingerprint of this transaction
    /// Used by Layer 0 for rapid pattern matching
    pub fn fingerprint(&self) -> ThreatFingerprint {
        use blake3::Hasher;
        let mut hasher = Hasher::new();

        // Hash structural properties, not just content
        hasher.update(&self.value.to_le_bytes());
        hasher.update(&self.gas_price.to_le_bytes());
        hasher.update(&self.gas_limit.to_le_bytes());
        hasher.update(&(self.data.len() as u64).to_le_bytes());

        // Call depth signature (first 4 bytes = function selector)
        if self.data.len() >= 4 {
            hasher.update(&self.data[..4]);
        }

        // Value-to-gas ratio (key indicator for flash loan attacks)
        let ratio = if self.gas_limit > 0 {
            self.value / self.gas_limit as u128
        } else {
            0
        };
        hasher.update(&ratio.to_le_bytes());

        ThreatFingerprint(hasher.finalize().into())
    }

    /// Extract behavioral features for ML scoring
    pub fn extract_features(&self) -> TransactionFeatures {
        TransactionFeatures {
            value_log: (self.value as f64 + 1.0).ln(),
            gas_price_normalized: self.gas_price as f64,
            gas_limit_normalized: self.gas_limit as f64,
            data_length: self.data.len(),
            has_contract_call: self.data.len() >= 4,
            value_to_gas_ratio: if self.gas_limit > 0 {
                self.value as f64 / self.gas_limit as f64
            } else {
                0.0
            },
            nonce: self.nonce,
            tx_type_encoded: self.tx_type.encode(),
        }
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum TransactionType {
    Transfer,
    ContractDeploy,
    ContractCall,
    FlashLoan,
    Bridge,
    Governance,
    Stake,
    Unstake,
    OracleUpdate,
    LiquidityAdd,
    LiquidityRemove,
    DelegateCall,
    SelfDestruct,
    BatchTransaction,
}

impl TransactionType {
    pub fn encode(&self) -> f64 {
        match self {
            TransactionType::Transfer => 0.0,
            TransactionType::ContractDeploy => 1.0,
            TransactionType::ContractCall => 2.0,
            TransactionType::FlashLoan => 3.0,
            TransactionType::Bridge => 4.0,
            TransactionType::Governance => 5.0,
            TransactionType::Stake => 6.0,
            TransactionType::Unstake => 7.0,
            TransactionType::OracleUpdate => 8.0,
            TransactionType::LiquidityAdd => 9.0,
            TransactionType::LiquidityRemove => 10.0,
            TransactionType::DelegateCall => 11.0,
            TransactionType::SelfDestruct => 12.0,
            TransactionType::BatchTransaction => 13.0,
        }
    }
}

// ============================================================
// ATTACK TYPE CLASSIFICATION
// ============================================================

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum AttackType {
    // DeFi attacks
    FlashLoan,
    Reentrancy,
    SandwichFrontrun,
    SandwichBackrun,
    OracleManipulation,
    GovernanceAttack,
    InfiniteMint,
    Rugpull,
    // Protocol/consensus attacks
    DoubleSpend,
    SybilFlood,
    SelfishMining,
    EclipseAttack,
    LongRangeAttack,
    NothingAtStake,
    // Smart contract attacks
    IntegerOverflow,
    AccessControlExploit,
    DelegatecallInjection,
    TxOriginPhishing,
    SignatureReplay,
    TimestampManipulation,
    FrontrunGeneric,
    // Bridge/cross-chain attacks
    BridgeExploit,
    FakeDeposit,
    ValidatorKeyCompromise,
    CrossChainReplay,
    // Network-level attacks
    DustAttack,
    MempoolFlooding,
    BlockStuffing,
    TransactionMalleability,
}

impl std::fmt::Display for AttackType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?}", self)
    }
}

/// Feature vector extracted from a transaction for ML
#[derive(Debug, Clone)]
pub struct TransactionFeatures {
    pub value_log: f64,
    pub gas_price_normalized: f64,
    pub gas_limit_normalized: f64,
    pub data_length: usize,
    pub has_contract_call: bool,
    pub value_to_gas_ratio: f64,
    pub nonce: u64,
    pub tx_type_encoded: f64,
}

impl TransactionFeatures {
    pub fn to_vec(&self) -> Vec<f64> {
        vec![
            self.value_log,
            self.gas_price_normalized,
            self.gas_limit_normalized,
            self.data_length as f64,
            self.has_contract_call as u8 as f64,
            self.value_to_gas_ratio,
            self.nonce as f64,
            self.tx_type_encoded,
        ]
    }
}

// ============================================================
// CRYPTOGRAPHIC PRIMITIVES
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq, Hash)]
pub struct Address(pub [u8; 32]);

impl Address {
    pub fn random() -> Self {
        use rand::RngCore;
        let mut bytes = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut bytes);
        Address(bytes)
    }

    pub fn to_hex(&self) -> String {
        hex::encode(&self.0)
    }
}

impl std::fmt::Display for Address {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "0x{}", &hex::encode(&self.0)[..8])
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Signature(pub Vec<u8>);

/// 32-byte threat fingerprint for bloom filter lookups
#[derive(Debug, Clone, PartialEq, Eq, Hash)]
pub struct ThreatFingerprint(pub [u8; 32]);

impl ThreatFingerprint {
    pub fn as_bytes(&self) -> &[u8] {
        &self.0
    }
}

// ============================================================
// VALIDATOR TYPES
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidatorId(pub [u8; 32]);

impl ValidatorId {
    pub fn random() -> Self {
        use rand::RngCore;
        let mut bytes = [0u8; 32];
        rand::thread_rng().fill_bytes(&mut bytes);
        ValidatorId(bytes)
    }
}

impl std::fmt::Display for ValidatorId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "VAL-{}", &hex::encode(&self.0)[..8])
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidatorInfo {
    pub id: ValidatorId,
    pub stake: u128,
    pub address: Address,
    pub joined_block: u64,
    pub is_active: bool,
}

/// A validator's vote on a transaction
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidatorVote {
    pub validator_id: ValidatorId,
    pub transaction_id: Uuid,
    pub confidence: f64,       // 0.0 - 1.0 (the novel part)
    pub is_valid: bool,
    pub timestamp: DateTime<Utc>,
    pub reasoning: VoteReasoning,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoteReasoning {
    pub layer0_passed: bool,
    pub layer1_score: f64,
    pub anomaly_flags: Vec<AnomalyFlag>,
    pub bts_at_vote_time: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum AnomalyFlag {
    HighValueToGasRatio,
    UnusualCallPattern,
    VelocityExceeded,
    SimilarToKnownAttack(f64),  // similarity score
    ValidatorCollusion,
    TemporalAnomaly,
}

// ============================================================
// CONSENSUS TYPES
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ConsensusDecision {
    Confirmed,
    Rejected,
    Escalated,   // needs more votes
    Quarantined, // suspicious, held for review
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConsensusResult {
    pub transaction_id: Uuid,
    pub decision: ConsensusDecision,
    pub weighted_confidence: f64,
    pub vote_count: usize,
    pub total_stake_voted: u128,
    pub timestamp: DateTime<Utc>,
}

// ============================================================
// BLOCK TYPES
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Block {
    pub height: u64,
    pub hash: [u8; 32],
    pub parent_hash: [u8; 32],
    pub transactions: Vec<Transaction>,
    pub validator: ValidatorId,
    pub timestamp: DateTime<Utc>,
    pub aegis_metrics: AegisBlockMetrics,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AegisBlockMetrics {
    pub layer0_rejections: u32,
    pub layer1_escalations: u32,
    pub layer2_quarantines: u32,
    pub alert_mode_active: bool,
    pub avg_bts: f64,
    pub threat_patterns_added: u32,
}

// ============================================================
// NETWORK STATE
// ============================================================

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum NetworkAlertLevel {
    Normal,
    Elevated,   // unusual patterns detected
    Alert,      // active attack suspected
    Emergency,  // confirmed attack in progress
}

impl NetworkAlertLevel {
    pub fn confirmation_threshold(&self) -> f64 {
        match self {
            NetworkAlertLevel::Normal => 0.67,
            NetworkAlertLevel::Elevated => 0.75,
            NetworkAlertLevel::Alert => 0.85,
            NetworkAlertLevel::Emergency => 0.95,
        }
    }

    pub fn min_bts_to_vote(&self) -> f64 {
        match self {
            NetworkAlertLevel::Normal => 0.3,
            NetworkAlertLevel::Elevated => 0.5,
            NetworkAlertLevel::Alert => 0.7,
            NetworkAlertLevel::Emergency => 0.85,
        }
    }
}

// ============================================================
// HEX HELPER (since hex crate not in deps, implement manually)
// ============================================================

pub mod hex {
    pub fn encode(bytes: &[u8]) -> String {
        bytes.iter().map(|b| format!("{:02x}", b)).collect()
    }
}
