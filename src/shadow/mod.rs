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
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{info, warn, debug};
use serde::{Serialize, Deserialize};
use chrono::Utc;

// ============================================================
// SYNTHETIC TRANSACTION GENERATOR
// Covers ALL known blockchain attack types in history
// ============================================================

pub struct TransactionGenerator {
    rng: rand::rngs::ThreadRng,
}

impl TransactionGenerator {
    pub fn new() -> Self {
        Self { rng: rand::thread_rng() }
    }

    // ========================================
    // LEGITIMATE TRANSACTIONS
    // ========================================

    /// Normal ETH/token transfer
    pub fn normal_transfer(&mut self) -> (Transaction, Option<AttackType>) {
        let value = (10_u128.pow(self.rng.gen_range(0..6))) * self.rng.gen_range(1..1000) as u128;
        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            value,
            self.rng.gen_range(10..200),
            21000,
            self.rng.gen_range(0..1000),
            vec![],
            TransactionType::Transfer,
        );
        (tx, None)
    }

    /// Normal contract call (ERC20 transfer, etc.)
    pub fn normal_contract_call(&mut self) -> (Transaction, Option<AttackType>) {
        let data_len = self.rng.gen_range(4..256);
        let mut data = vec![0u8; data_len];
        self.rng.fill(data.as_mut_slice());
        // ERC20 transfer selector: 0xa9059cbb
        data[0] = 0xa9; data[1] = 0x05; data[2] = 0x9c; data[3] = 0xbb;

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
        (tx, None)
    }

    /// Normal liquidity add
    pub fn normal_liquidity_add(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 128];
        self.rng.fill(data.as_mut_slice());
        // addLiquidity selector
        data[0] = 0xe8; data[1] = 0xe3; data[2] = 0x37; data[3] = 0x00;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1..100) * 10_u128.pow(18),
            self.rng.gen_range(20..100),
            self.rng.gen_range(150_000..400_000),
            self.rng.gen_range(5..200),
            data,
            TransactionType::LiquidityAdd,
        );
        (tx, None)
    }

    /// Normal governance vote
    pub fn normal_governance_vote(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 68];
        self.rng.fill(data.as_mut_slice());
        data[0] = 0x56; data[1] = 0x78; data[2] = 0x13; data[3] = 0x88;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(20..80),
            self.rng.gen_range(80_000..200_000),
            self.rng.gen_range(10..500),
            data,
            TransactionType::Governance,
        );
        (tx, None)
    }

    // ========================================
    // DEFI ATTACKS (8 types)
    // ========================================

    /// Flash loan attack — The DAO, bZx, dForce, Harvest, Cream, Euler, Beanstalk
    /// Signature: extreme value, complex calldata, max gas
    pub fn flash_loan_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let value = 10_u128.pow(21) * self.rng.gen_range(1..100) as u128;
        let data_len = self.rng.gen_range(500..2000);
        let mut data = vec![0u8; data_len];
        self.rng.fill(data.as_mut_slice());

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            value,
            self.rng.gen_range(100..2000),
            self.rng.gen_range(1_000_000..10_000_000),
            0,
            data,
            TransactionType::FlashLoan,
        );
        (tx, Some(AttackType::FlashLoan))
    }

    /// Mutated flash loan — slightly different to evade exact matching
    pub fn mutated_flash_loan_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let (mut tx, _) = self.flash_loan_attack();
        tx.gas_price += self.rng.gen_range(0..50);
        tx.gas_limit += self.rng.gen_range(0..10000);
        (tx, Some(AttackType::FlashLoan))
    }

    /// Reentrancy attack — The DAO 2016, Cream Finance, Fei Protocol
    /// Signature: withdraw() selector, recursive call structure
    pub fn reentrancy_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let data_len = self.rng.gen_range(100..500);
        let mut data = vec![0u8; data_len];
        self.rng.fill(data.as_mut_slice());
        // withdraw() selector: 0x3ccfd60b
        data[0] = 0x3c; data[1] = 0xcf; data[2] = 0xd6; data[3] = 0x0b;

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
        (tx, Some(AttackType::Reentrancy))
    }

    /// Sandwich attack front-run — MEV extraction
    /// Signature: swap selector + extreme gas price to get ahead of victim
    pub fn sandwich_attack_frontrun(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 68];
        self.rng.fill(data.as_mut_slice());
        // swapExactTokensForTokens: 0x38ed1739
        data[0] = 0x38; data[1] = 0xed; data[2] = 0x17; data[3] = 0x39;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            999999, // extreme gas price
            self.rng.gen_range(150_000..400_000),
            0,
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::SandwichFrontrun))
    }

    /// Sandwich attack back-run — completes the sandwich after victim tx
    /// Signature: same swap selector but gas_price=1 (back of block)
    pub fn sandwich_attack_backrun(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 68];
        self.rng.fill(data.as_mut_slice());
        data[0] = 0x38; data[1] = 0xed; data[2] = 0x17; data[3] = 0x39;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            1, // minimum gas price — back of block
            self.rng.gen_range(150_000..400_000),
            1, // second tx in sequence
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::SandwichBackrun))
    }

    /// Oracle manipulation — Mango Markets ($114M), Harvest Finance ($34M)
    /// Signature: price update function with extreme price values encoded
    pub fn oracle_manipulation_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 100];
        self.rng.fill(data.as_mut_slice());
        // setPrice / updatePrice selector
        data[0] = 0x91; data[1] = 0xb7; data[2] = 0xf5; data[3] = 0xed;
        // Encode extreme price in calldata (bytes 36-68 all 0xFF = max uint)
        for i in 36..68 {
            data[i] = 0xFF;
        }

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(200..1000),
            self.rng.gen_range(100_000..500_000),
            self.rng.gen_range(0..3),
            data,
            TransactionType::OracleUpdate,
        );
        (tx, Some(AttackType::OracleManipulation))
    }

    /// Governance attack — Beanstalk ($182M governance takeover)
    /// Signature: flash-loan-sized value + castVote function + high urgency
    pub fn governance_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 100];
        self.rng.fill(data.as_mut_slice());
        // castVote selector: 0x56781388
        data[0] = 0x56; data[1] = 0x78; data[2] = 0x13; data[3] = 0x88;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            10_u128.pow(21) * self.rng.gen_range(1..50) as u128, // flash-loan sized
            self.rng.gen_range(500..5000), // high gas price for urgency
            self.rng.gen_range(200_000..1_000_000),
            1, // second tx (after flash loan)
            data,
            TransactionType::Governance,
        );
        (tx, Some(AttackType::GovernanceAttack))
    }

    /// Infinite mint — Cover Protocol, Paid Network
    /// Signature: mint selector + 0xFF-filled amount (overflow)
    pub fn infinite_mint_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 68];
        self.rng.fill(data.as_mut_slice());
        // mint(address,uint256) selector: 0x40c10f19
        data[0] = 0x40; data[1] = 0xc1; data[2] = 0x0f; data[3] = 0x19;
        // Extremely large mint amount (bytes 36-67 all 0xFF)
        for i in 36..68 {
            data[i] = 0xFF;
        }

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(50..300),
            self.rng.gen_range(100_000..500_000),
            self.rng.gen_range(0..5),
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::InfiniteMint))
    }

    /// Rugpull — liquidity removal drain
    /// Signature: removeLiquidity with 100% amount, high urgency gas
    pub fn rugpull_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 164];
        self.rng.fill(data.as_mut_slice());
        // removeLiquidity selector: 0xbaa2abde
        data[0] = 0xba; data[1] = 0xa2; data[2] = 0xab; data[3] = 0xde;
        // Max liquidity amount (100% removal)
        for i in 100..132 {
            data[i] = 0xFF;
        }

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(1000..10000), // urgency
            self.rng.gen_range(200_000..600_000),
            self.rng.gen_range(50..500), // established account
            data,
            TransactionType::LiquidityRemove,
        );
        (tx, Some(AttackType::Rugpull))
    }

    // ========================================
    // PROTOCOL / CONSENSUS ATTACKS (6 types)
    // ========================================

    /// Double spend — same nonce, different recipients
    /// Signature: duplicate nonce with moderate value
    pub fn double_spend_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let value = self.rng.gen_range(10..1000) * 10_u128.pow(18);
        let nonce = self.rng.gen_range(100..500);

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            value,
            self.rng.gen_range(100..500), // slightly elevated gas
            21000,
            nonce,
            vec![],
            TransactionType::Transfer,
        );
        (tx, Some(AttackType::DoubleSpend))
    }

    /// Sybil flood — many fresh addresses sending small txs
    /// Signature: nonce=0 (fresh address), dust value
    pub fn sybil_flood_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let tx = Transaction::new(
            Address::random(), // fresh address each time
            Address::random(),
            self.rng.gen_range(1..100), // dust value
            self.rng.gen_range(1..10),  // minimum gas
            21000,
            0, // nonce=0 (new address)
            vec![],
            TransactionType::Transfer,
        );
        (tx, Some(AttackType::SybilFlood))
    }

    /// Selfish mining indicator — suspicious block proposal pattern
    /// Signature: stake tx with high gas, zero value
    pub fn selfish_mining_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 64];
        self.rng.fill(data.as_mut_slice());

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(5000..50000), // extreme gas
            self.rng.gen_range(100_000..500_000),
            0,
            data,
            TransactionType::Stake,
        );
        (tx, Some(AttackType::SelfishMining))
    }

    /// Eclipse attack — burst of zero-value txs to isolate a node
    /// Signature: zero value, zero gas, IP-like data payload
    pub fn eclipse_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 32];
        self.rng.fill(data.as_mut_slice());

        let tx = Transaction::new(
            Address::random(),
            Address::random(), // same target (in batch)
            0,
            0, // zero gas
            21000,
            0,
            data,
            TransactionType::Transfer,
        );
        (tx, Some(AttackType::EclipseAttack))
    }

    /// Long-range attack (PoS) — unstake with old block reference
    /// Signature: unstake tx referencing very old block height
    pub fn long_range_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 40];
        self.rng.fill(data.as_mut_slice());
        // Encode very old block height in first 8 bytes (e.g., block 100 when current is 10000)
        let old_block: u64 = self.rng.gen_range(1..100);
        data[0..8].copy_from_slice(&old_block.to_le_bytes());

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1000..100000) * 10_u128.pow(18), // full stake withdrawal
            self.rng.gen_range(100..500),
            self.rng.gen_range(100_000..300_000),
            self.rng.gen_range(0..5),
            data,
            TransactionType::Unstake,
        );
        (tx, Some(AttackType::LongRangeAttack))
    }

    /// Nothing-at-stake — validator voting on two conflicting forks
    /// Signature: stake tx with two 32-byte block hashes in calldata
    pub fn nothing_at_stake_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 64]; // two 32-byte hashes
        self.rng.fill(data.as_mut_slice());

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(50..200),
            self.rng.gen_range(100_000..200_000),
            self.rng.gen_range(0..10),
            data,
            TransactionType::Stake,
        );
        (tx, Some(AttackType::NothingAtStake))
    }

    // ========================================
    // SMART CONTRACT ATTACKS (7 types)
    // ========================================

    /// Integer overflow — BeautyChain BEC, early Solidity
    /// Signature: transfer with near-max uint256 amount
    pub fn integer_overflow_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 68];
        self.rng.fill(data.as_mut_slice());
        // transfer(address,uint256): 0xa9059cbb
        data[0] = 0xa9; data[1] = 0x05; data[2] = 0x9c; data[3] = 0xbb;
        // Near-max amount (causes overflow when added)
        for i in 36..68 {
            data[i] = 0xFF;
        }
        // But keep last byte slightly different from legit
        data[67] = 0xFE;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(20..100),
            self.rng.gen_range(60_000..200_000),
            self.rng.gen_range(0..10),
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::IntegerOverflow))
    }

    /// Access control exploit — Parity wallet freeze ($150M)
    /// Signature: admin function called by non-owner
    pub fn access_control_exploit(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 36];
        self.rng.fill(data.as_mut_slice());
        // transferOwnership selector: 0xf2fde38b
        data[0] = 0xf2; data[1] = 0xfd; data[2] = 0xe3; data[3] = 0x8b;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(10..50),
            self.rng.gen_range(30_000..100_000),
            self.rng.gen_range(0..3),
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::AccessControlExploit))
    }

    /// Delegatecall injection — Parity wallet hack ($30M)
    /// Signature: delegatecall with nested contract address in calldata
    pub fn delegatecall_injection(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 256];
        self.rng.fill(data.as_mut_slice());
        // delegatecall-related pattern
        data[0] = 0xda; data[1] = 0x7b; data[2] = 0xfa; data[3] = 0x36;
        // Nested contract address in bytes 4-36
        let nested_addr = Address::random();
        data[4..36].copy_from_slice(&nested_addr.0);

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(50..300),
            self.rng.gen_range(500_000..2_000_000),
            self.rng.gen_range(0..5),
            data,
            TransactionType::DelegateCall,
        );
        (tx, Some(AttackType::DelegatecallInjection))
    }

    /// tx.origin phishing — disguised transfer to phishing contract
    /// Signature: simple transfer to a contract (has_contract_call=true with short data)
    pub fn tx_origin_phishing(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 4]; // minimal calldata
        data[0] = 0xd0; data[1] = 0xe3; data[2] = 0x0d; data[3] = 0xb0; // random selector

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1..50) * 10_u128.pow(18),
            self.rng.gen_range(20..100),
            self.rng.gen_range(50_000..150_000),
            self.rng.gen_range(0..20),
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::TxOriginPhishing))
    }

    /// Signature replay attack — reused signature across chains
    /// Signature: transfer with reused nonce and suspicious signature bytes
    pub fn signature_replay_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1..100) * 10_u128.pow(18),
            self.rng.gen_range(20..100),
            21000,
            42, // suspiciously specific nonce (reused)
            vec![],
            TransactionType::Transfer,
        );
        // Duplicate signature pattern (same 32 bytes repeated)
        let mut sig = vec![0xAB; 65];
        self.rng.fill(sig.as_mut_slice());
        // Mark as replay: first and last 8 bytes identical
        let prefix: [u8; 8] = sig[0..8].try_into().unwrap();
        sig[57..65].copy_from_slice(&prefix);
        tx.signature = Signature(sig);

        (tx, Some(AttackType::SignatureReplay))
    }

    /// Timestamp manipulation — exploiting block.timestamp dependency
    /// Signature: time-sensitive function call with precise gas targeting
    pub fn timestamp_manipulation_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 36];
        self.rng.fill(data.as_mut_slice());
        // claimReward / unlock selector (time-dependent function)
        data[0] = 0x4e; data[1] = 0x71; data[2] = 0xd9; data[3] = 0x2d;

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(50..150), // precise gas (miner cooperation)
            self.rng.gen_range(80_000..200_000),
            self.rng.gen_range(0..5),
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::TimestampManipulation))
    }

    /// Generic front-running — extreme gas price to jump ahead
    /// Signature: 99th percentile gas price, mirrors pending tx structure
    pub fn frontrun_generic(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; self.rng.gen_range(36..200)];
        self.rng.fill(data.as_mut_slice());

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(0..10) * 10_u128.pow(18),
            self.rng.gen_range(50000..999999), // extreme gas price
            self.rng.gen_range(100_000..500_000),
            self.rng.gen_range(0..10),
            data,
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::FrontrunGeneric))
    }

    // ========================================
    // BRIDGE / CROSS-CHAIN ATTACKS (4 types)
    // ========================================

    /// Bridge exploit — Ronin ($625M), Wormhole ($326M), Nomad ($190M)
    /// Signature: bridge tx with extreme value and malformed proof
    pub fn bridge_exploit(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 400];
        self.rng.fill(data.as_mut_slice());
        // completeTransfer selector
        data[0] = 0xc6; data[1] = 0x87; data[2] = 0x85; data[3] = 0x19;
        // Malformed proof section (bytes 200-400 — random, invalid merkle proof)
        for i in 200..250 {
            data[i] = 0x00; // zeroed out proof = invalid
        }

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            10_u128.pow(22) * self.rng.gen_range(1..50) as u128, // massive value
            self.rng.gen_range(100..1000),
            self.rng.gen_range(500_000..2_000_000),
            self.rng.gen_range(0..3),
            data,
            TransactionType::Bridge,
        );
        (tx, Some(AttackType::BridgeExploit))
    }

    /// Fake deposit — claims large deposit but sends nothing
    /// Signature: bridge deposit with value=0 but encoded amount is huge
    pub fn fake_deposit_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 100];
        self.rng.fill(data.as_mut_slice());
        // deposit selector
        data[0] = 0xb6; data[1] = 0xb5; data[2] = 0x5f; data[3] = 0x25;
        // Encode huge amount in calldata while sending 0 value
        for i in 36..68 {
            data[i] = 0xFF;
        }

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0, // sending NOTHING
            self.rng.gen_range(50..300),
            self.rng.gen_range(100_000..400_000),
            self.rng.gen_range(0..5),
            data,
            TransactionType::Bridge,
        );
        (tx, Some(AttackType::FakeDeposit))
    }

    /// Validator key compromise — Ronin bridge validators
    /// Signature: withdrawal credential change with extreme urgency
    pub fn validator_key_compromise(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 68];
        self.rng.fill(data.as_mut_slice());
        // setWithdrawalCredentials selector
        data[0] = 0x0f; data[1] = 0x4e; data[2] = 0xf5; data[3] = 0xa2;
        // New withdrawal address (attacker's)
        let attacker = Address::random();
        data[36..68].copy_from_slice(&attacker.0);

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(5000..50000), // extreme urgency
            self.rng.gen_range(100_000..300_000),
            0,
            data,
            TransactionType::Stake,
        );
        (tx, Some(AttackType::ValidatorKeyCompromise))
    }

    /// Cross-chain replay — replaying tx from chain A on chain B
    /// Signature: bridge tx with wrong chain ID encoded
    pub fn cross_chain_replay(&mut self) -> (Transaction, Option<AttackType>) {
        let mut data = vec![0u8; 100];
        self.rng.fill(data.as_mut_slice());
        data[0] = 0xc6; data[1] = 0x87; data[2] = 0x85; data[3] = 0x19;
        // Wrong chain ID encoded (chain 1 tx replayed on chain 56)
        let wrong_chain: u64 = self.rng.gen_range(1..10);
        data[68..76].copy_from_slice(&wrong_chain.to_le_bytes());

        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1..100) * 10_u128.pow(18),
            self.rng.gen_range(20..100),
            self.rng.gen_range(100_000..300_000),
            self.rng.gen_range(0..5),
            data,
            TransactionType::Bridge,
        );
        (tx, Some(AttackType::CrossChainReplay))
    }

    // ========================================
    // NETWORK-LEVEL ATTACKS (4 types)
    // ========================================

    /// Dust attack — tiny amounts to many addresses for UTXO linking
    /// Signature: extremely small value, automated sequential nonces
    pub fn dust_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1..546), // sub-dust threshold
            self.rng.gen_range(1..5),   // minimum gas
            21000,
            self.rng.gen_range(1000..10000), // sequential nonce (automated)
            vec![],
            TransactionType::Transfer,
        );
        (tx, Some(AttackType::DustAttack))
    }

    /// Mempool flooding — spam to clog the network
    /// Signature: burst of zero-value txs with sequential nonces
    pub fn mempool_flooding_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0, // zero value
            self.rng.gen_range(1..3), // minimum gas
            21000,
            self.rng.gen_range(5000..100000), // very high sequential nonce
            vec![], // no data
            TransactionType::Transfer,
        );
        (tx, Some(AttackType::MempoolFlooding))
    }

    /// Block stuffing — fill entire block to deny others
    /// Signature: gas_limit = full block gas, extreme gas price
    pub fn block_stuffing_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let tx = Transaction::new(
            Address::random(),
            Address::random(),
            0,
            self.rng.gen_range(100000..999999), // willing to pay any price
            30_000_000, // full block gas limit
            self.rng.gen_range(0..5),
            vec![0u8; 32], // minimal data
            TransactionType::ContractCall,
        );
        (tx, Some(AttackType::BlockStuffing))
    }

    /// Transaction malleability — Mt. Gox style
    /// Signature: valid tx content but mutated signature (S-value flipped)
    pub fn transaction_malleability_attack(&mut self) -> (Transaction, Option<AttackType>) {
        let mut tx = Transaction::new(
            Address::random(),
            Address::random(),
            self.rng.gen_range(1..100) * 10_u128.pow(18),
            self.rng.gen_range(20..100),
            21000,
            self.rng.gen_range(0..100),
            vec![],
            TransactionType::Transfer,
        );
        // Mutated signature — S-value complemented
        let mut sig = vec![0u8; 65];
        self.rng.fill(sig.as_mut_slice());
        // Set high-S indicator (byte 32 has high bit set)
        sig[32] |= 0x80;
        tx.signature = Signature(sig);

        (tx, Some(AttackType::TransactionMalleability))
    }

    // ========================================
    // RANDOM GENERATION WITH WEIGHTS
    // ========================================

    /// Generate a random transaction — 40% legitimate, 60% attacks
    pub fn random_tx(&mut self) -> (Transaction, Option<AttackType>) {
        let roll: u32 = self.rng.gen_range(0..100);
        match roll {
            // 40% legitimate
            0..=14 => self.normal_transfer(),
            15..=29 => self.normal_contract_call(),
            30..=34 => self.normal_liquidity_add(),
            35..=39 => self.normal_governance_vote(),
            // DeFi attacks (24%)
            40..=44 => self.flash_loan_attack(),
            45..=47 => self.mutated_flash_loan_attack(),
            48..=51 => self.reentrancy_attack(),
            52..=54 => self.sandwich_attack_frontrun(),
            55..=56 => self.sandwich_attack_backrun(),
            57..=58 => self.oracle_manipulation_attack(),
            59..=60 => self.governance_attack(),
            61..=62 => self.infinite_mint_attack(),
            63 => self.rugpull_attack(),
            // Protocol attacks (12%)
            64..=66 => self.double_spend_attack(),
            67..=69 => self.sybil_flood_attack(),
            70..=71 => self.selfish_mining_attack(),
            72..=73 => self.eclipse_attack(),
            74 => self.long_range_attack(),
            75 => self.nothing_at_stake_attack(),
            // Smart contract attacks (12%)
            76..=77 => self.integer_overflow_attack(),
            78..=79 => self.access_control_exploit(),
            80..=81 => self.delegatecall_injection(),
            82 => self.tx_origin_phishing(),
            83..=84 => self.signature_replay_attack(),
            85 => self.timestamp_manipulation_attack(),
            86..=87 => self.frontrun_generic(),
            // Bridge attacks (6%)
            88..=90 => self.bridge_exploit(),
            91..=92 => self.fake_deposit_attack(),
            93 => self.validator_key_compromise(),
            94 => self.cross_chain_replay(),
            // Network attacks (6%)
            95..=96 => self.dust_attack(),
            97 => self.mempool_flooding_attack(),
            98 => self.block_stuffing_attack(),
            _ => self.transaction_malleability_attack(),
        }
    }

    /// Generate training data: (features, is_attack) pairs
    pub fn generate_training_set(&mut self, count: usize) -> Vec<(Vec<f64>, bool)> {
        (0..count)
            .map(|_| {
                let (tx, attack_type) = self.random_tx();
                (tx.extract_features().to_vec(), attack_type.is_some())
            })
            .collect()
    }
}

// ============================================================
// PER-ATTACK METRICS
// ============================================================

#[derive(Debug, Default, Clone, Serialize)]
pub struct PerAttackMetrics {
    pub total: u64,
    pub caught: u64,
    pub missed: u64,
}

impl PerAttackMetrics {
    pub fn recall(&self) -> f64 {
        if self.total == 0 { return 1.0; }
        self.caught as f64 / self.total as f64
    }
}

// ============================================================
// SYNTHETIC VALIDATOR SIMULATOR
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
    Malicious,
    ColludingLeader,
    ColludingFollower(ValidatorId),
    Sleepy,
    RandomDrift,
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

    pub fn vote(&self, tx: &Transaction, ground_truth_is_attack: bool, block: u64) -> ValidatorVote {
        let mut rng = rand::thread_rng();

        let (is_valid, confidence) = match &self.behavior {
            ValidatorBehavior::Honest => {
                let correct = rng.gen::<f64>() < 0.95;
                let is_valid = if correct { !ground_truth_is_attack } else { ground_truth_is_attack };
                let confidence = if correct {
                    rng.gen_range(0.75..0.99)
                } else {
                    rng.gen_range(0.51..0.70)
                };
                (is_valid, confidence)
            }
            ValidatorBehavior::Malicious => {
                (ground_truth_is_attack, rng.gen_range(0.8..0.99))
            }
            ValidatorBehavior::Sleepy => {
                (!ground_truth_is_attack, rng.gen_range(0.51..0.65))
            }
            ValidatorBehavior::RandomDrift => {
                let degradation = (block as f64 / 1000.0).min(0.9);
                let accurate = rng.gen::<f64>() > degradation * 0.5;
                let is_valid = if accurate { !ground_truth_is_attack } else { ground_truth_is_attack };
                (is_valid, rng.gen_range(0.51..0.9))
            }
            ValidatorBehavior::ColludingLeader | ValidatorBehavior::ColludingFollower(_) => {
                (ground_truth_is_attack, rng.gen_range(0.85..0.99))
            }
        };

        let _latency = (self.latency_mean_ms
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
                bts_at_vote_time: 0.5,
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

    pub true_positives: u64,
    pub true_negatives: u64,
    pub false_positives: u64,
    pub false_negatives: u64,

    pub caught_by_layer0: u64,
    pub caught_by_layer1: u64,
    pub caught_by_layer2: u64,

    pub current_block: u64,

    pub per_attack: HashMap<String, PerAttackMetrics>,
}

impl SimulationMetrics {
    pub fn precision(&self) -> f64 {
        let detected = self.true_positives + self.false_positives;
        if detected == 0 { return 1.0; }
        self.true_positives as f64 / detected as f64
    }

    pub fn recall(&self) -> f64 {
        let actual = self.true_positives + self.false_negatives;
        if actual == 0 { return 1.0; }
        self.true_positives as f64 / actual as f64
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

    pub fn false_positive_rate(&self) -> f64 {
        if self.actual_legitimate == 0 { return 0.0; }
        self.false_positives as f64 / self.actual_legitimate as f64
    }

    pub fn reset(&mut self) {
        self.total_transactions = 0;
        self.actual_attacks = 0;
        self.actual_legitimate = 0;
        self.true_positives = 0;
        self.true_negatives = 0;
        self.false_positives = 0;
        self.false_negatives = 0;
        self.caught_by_layer0 = 0;
        self.caught_by_layer1 = 0;
        self.caught_by_layer2 = 0;
        self.per_attack.clear();
    }
}

impl ShadowNetwork {
    pub fn new(honest_validators: u32, malicious_validators: u32) -> Self {
        let mut rng = rand::thread_rng();
        let mut validators = Vec::new();

        for _ in 0..honest_validators {
            let stake = rng.gen_range(1000..10000) as u128 * 10_u128.pow(18);
            validators.push(SimulatedValidator::honest(stake));
        }

        for _ in 0..malicious_validators {
            let stake = rng.gen_range(500..3000) as u128 * 10_u128.pow(18);
            validators.push(SimulatedValidator::malicious(stake));
        }

        Self {
            validators,
            tx_generator: TransactionGenerator::new(),
            layer0: Layer0Engine::new(),
            layer1: Arc::new(Layer1Engine::new(100)),
            layer2: Arc::new(Layer2Engine::new()),
            layer3: Arc::new(Layer3Engine::new(8)),
            current_block: 0,
            metrics: SimulationMetrics::default(),
        }
    }

    /// Seed Layer 0 with ALL known attack patterns (~200 variants per type)
    pub fn seed_all_attack_patterns(&mut self) {
        let mut gen = TransactionGenerator::new();
        let mut patterns: Vec<(String, Vec<f64>)> = Vec::new();

        // Generate 200 variants of each attack type for the bloom filter + LSH
        let attack_generators: Vec<(&str, fn(&mut TransactionGenerator) -> (Transaction, Option<AttackType>))> = vec![
            ("flash_loan", TransactionGenerator::flash_loan_attack),
            ("flash_loan_mutated", TransactionGenerator::mutated_flash_loan_attack),
            ("reentrancy", TransactionGenerator::reentrancy_attack),
            ("sandwich_front", TransactionGenerator::sandwich_attack_frontrun),
            ("sandwich_back", TransactionGenerator::sandwich_attack_backrun),
            ("oracle_manipulation", TransactionGenerator::oracle_manipulation_attack),
            ("governance", TransactionGenerator::governance_attack),
            ("infinite_mint", TransactionGenerator::infinite_mint_attack),
            ("rugpull", TransactionGenerator::rugpull_attack),
            ("double_spend", TransactionGenerator::double_spend_attack),
            ("sybil_flood", TransactionGenerator::sybil_flood_attack),
            ("selfish_mining", TransactionGenerator::selfish_mining_attack),
            ("eclipse", TransactionGenerator::eclipse_attack),
            ("long_range", TransactionGenerator::long_range_attack),
            ("nothing_at_stake", TransactionGenerator::nothing_at_stake_attack),
            ("integer_overflow", TransactionGenerator::integer_overflow_attack),
            ("access_control", TransactionGenerator::access_control_exploit),
            ("delegatecall", TransactionGenerator::delegatecall_injection),
            ("tx_origin_phishing", TransactionGenerator::tx_origin_phishing),
            ("signature_replay", TransactionGenerator::signature_replay_attack),
            ("timestamp_manipulation", TransactionGenerator::timestamp_manipulation_attack),
            ("frontrun_generic", TransactionGenerator::frontrun_generic),
            ("bridge_exploit", TransactionGenerator::bridge_exploit),
            ("fake_deposit", TransactionGenerator::fake_deposit_attack),
            ("validator_key_compromise", TransactionGenerator::validator_key_compromise),
            ("cross_chain_replay", TransactionGenerator::cross_chain_replay),
            ("dust", TransactionGenerator::dust_attack),
            ("mempool_flooding", TransactionGenerator::mempool_flooding_attack),
            ("block_stuffing", TransactionGenerator::block_stuffing_attack),
            ("tx_malleability", TransactionGenerator::transaction_malleability_attack),
        ];

        for (name, generator_fn) in &attack_generators {
            for i in 0..200 {
                let (tx, _) = generator_fn(&mut gen);
                patterns.push((
                    format!("{}_seed_{}", name, i),
                    tx.extract_features().to_vec(),
                ));
            }
        }

        let count = patterns.len();
        self.layer0.load_attack_patterns(patterns);
        info!("Seeded Layer 0 with {} attack patterns across {} attack types", count, attack_generators.len());
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
        info!("Registered {} validators ({} honest, others malicious)",
              self.validators.len(),
              self.validators.iter().filter(|v| matches!(v.behavior, ValidatorBehavior::Honest)).count());
    }

    /// Run one block of simulation
    pub async fn run_block(&mut self, txs_per_block: usize) -> bool {
        self.current_block += 1;
        self.metrics.current_block = self.current_block;

        for _ in 0..txs_per_block {
            let (tx, attack_type) = self.tx_generator.random_tx();
            let is_attack = attack_type.is_some();

            self.metrics.total_transactions += 1;
            if is_attack {
                self.metrics.actual_attacks += 1;
            } else {
                self.metrics.actual_legitimate += 1;
            }

            // Track per-attack metrics
            if let Some(ref at) = attack_type {
                let key = format!("{:?}", at);
                let entry = self.metrics.per_attack.entry(key).or_default();
                entry.total += 1;
            }

            // Run through AEGIS pipeline
            let decision = self.process_transaction(&tx, is_attack).await;

            // Record outcome
            match (&decision, is_attack) {
                (ConsensusDecision::Rejected, true) => {
                    self.metrics.true_positives += 1;
                    if let Some(ref at) = attack_type {
                        let key = format!("{:?}", at);
                        self.metrics.per_attack.entry(key).or_default().caught += 1;
                    }
                }
                (ConsensusDecision::Confirmed, false) => {
                    self.metrics.true_negatives += 1;
                }
                (ConsensusDecision::Confirmed, true) => {
                    self.metrics.false_negatives += 1;
                    if let Some(ref at) = attack_type {
                        let key = format!("{:?}", at);
                        self.metrics.per_attack.entry(key).or_default().missed += 1;
                    }
                    warn!("FALSE NEGATIVE block {} — {:?} attack confirmed!", self.current_block, attack_type);
                }
                (ConsensusDecision::Rejected, false) => {
                    self.metrics.false_positives += 1;
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

        // Every 100 blocks: BTS adjustments + live-learning propagation
        if self.current_block % 100 == 0 {
            self.apply_bts_adjustments().await;
            self.propagate_learned_patterns().await;
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
        let alert_level = NetworkAlertLevel::Normal;
        let result = self.layer2
            .decide_transaction(tx.id, &votes, &alert_level)
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
            if adj.abs() > 0.001 {
                debug!("BTS adjustment for {}: {:+.4}", &key[..8.min(key.len())], adj);
            }
        }
    }

    /// Propagate learned patterns from Layer 3 back to Layer 0
    async fn propagate_learned_patterns(&mut self) {
        let broadcasts = self.layer3.drain_broadcasts().await;
        for broadcast in broadcasts {
            for pattern in &broadcast.new_patterns {
                self.layer0.add_attack_pattern(
                    pattern.pattern_id.clone(),
                    pattern.features.clone(),
                );
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
            m.false_positive_rate() * 100.0,
            m.f1_score(),
            m.caught_by_layer0,
        );
    }

    /// Print comprehensive final training report
    pub fn print_final_report(&self) {
        let m = &self.metrics;

        info!("");
        info!("================================================================");
        info!("               AEGIS TRAINING REPORT");
        info!("================================================================");
        info!("");
        info!("Overall Metrics:");
        info!("  Total Transactions: {}", m.total_transactions);
        info!("  Attacks Seen:       {}", m.actual_attacks);
        info!("  Legitimate Seen:    {}", m.actual_legitimate);
        info!("  True Positives:     {} (attacks correctly rejected)", m.true_positives);
        info!("  True Negatives:     {} (legitimate correctly confirmed)", m.true_negatives);
        info!("  False Positives:    {} (legitimate incorrectly rejected)", m.false_positives);
        info!("  False Negatives:    {} (ATTACKS THAT GOT THROUGH)", m.false_negatives);
        info!("");
        info!("  Precision:          {:.4}", m.precision());
        info!("  Recall:             {:.4}", m.recall());
        info!("  F1 Score:           {:.4}", m.f1_score());
        info!("  FNR:                {:.4}%", m.false_negative_rate() * 100.0);
        info!("  FPR:                {:.4}%", m.false_positive_rate() * 100.0);
        info!("");
        info!("Layer Contribution:");
        if m.true_positives > 0 {
            info!("  Layer 0 caught:     {} ({:.1}%)", m.caught_by_layer0,
                  m.caught_by_layer0 as f64 / m.true_positives as f64 * 100.0);
            let l2_caught = m.true_positives - m.caught_by_layer0;
            info!("  Layer 2 caught:     {} ({:.1}%)", l2_caught,
                  l2_caught as f64 / m.true_positives as f64 * 100.0);
        }
        info!("");
        info!("Per-Attack-Type Recall:");

        // Sort by attack type name for consistent output
        let mut attack_types: Vec<_> = m.per_attack.iter().collect();
        attack_types.sort_by_key(|(k, _)| k.clone());

        for (attack_type, metrics) in &attack_types {
            info!("  {:<30} {:>6.2}% ({}/{})",
                  attack_type,
                  metrics.recall() * 100.0,
                  metrics.caught,
                  metrics.total);
        }

        info!("");
        info!("Threat patterns learned: {}", self.layer3.threat_count());
        info!("");

        // Readiness check
        let fnr_ok = m.false_negative_rate() < 0.001; // < 0.1%
        let fpr_ok = m.false_positive_rate() < 0.01;  // < 1%

        if fnr_ok && fpr_ok {
            info!("READINESS: PASS");
            info!("  FNR {:.4}% < 0.1%  OK", m.false_negative_rate() * 100.0);
            info!("  FPR {:.4}% < 1.0%  OK", m.false_positive_rate() * 100.0);
        } else {
            warn!("READINESS: FAIL");
            if !fnr_ok {
                warn!("  FNR {:.4}% >= 0.1%  NEEDS IMPROVEMENT", m.false_negative_rate() * 100.0);
            }
            if !fpr_ok {
                warn!("  FPR {:.4}% >= 1.0%  NEEDS IMPROVEMENT", m.false_positive_rate() * 100.0);
            }
        }
        info!("================================================================");
    }

    /// Run full training simulation
    pub async fn run_training(
        &mut self,
        num_blocks: u64,
        txs_per_block: usize,
    ) -> &SimulationMetrics {
        info!("Starting training: {} blocks x {} tx/block", num_blocks, txs_per_block);

        for _ in 0..num_blocks {
            if !self.run_block(txs_per_block).await {
                break;
            }
        }

        &self.metrics
    }
}

// ============================================================
// SHADOW NETWORK MAIN ENTRY POINT (called from shadow/main.rs)
// ============================================================

pub async fn run_shadow_simulation() {
    tracing_subscriber::fmt::init();

    info!("================================================================");
    info!("  AEGIS Shadow Network — Comprehensive Training Pipeline");
    info!("  Training on ALL known blockchain attack types");
    info!("================================================================");

    let honest = 40;
    let malicious = 5;
    let burn_in_blocks = 200;
    let training_blocks = 2000;
    let eval_blocks = 500;
    let txs_per_block = 50;

    let mut shadow = ShadowNetwork::new(honest, malicious);

    // Phase 1: Seed all attack patterns
    info!("");
    info!("Phase 1: Seeding Layer 0 with attack patterns...");
    shadow.seed_all_attack_patterns();
    shadow.register_validators().await;

    // Phase 2: Burn-in (establish behavioral baselines)
    info!("");
    info!("Phase 2: Burn-in ({} blocks — no scoring, just calibration)...", burn_in_blocks);
    for _ in 0..burn_in_blocks {
        shadow.run_block(txs_per_block).await;
    }

    // Phase 3: Training (all 4 layers active)
    info!("");
    info!("Phase 3: Training ({} blocks — all layers active)...", training_blocks);
    shadow.metrics.reset();
    shadow.run_training(training_blocks, txs_per_block).await;

    info!("");
    info!("Training phase complete. Resetting metrics for evaluation...");

    // Phase 4: Evaluation (fresh metrics)
    shadow.metrics.reset();
    info!("");
    info!("Phase 4: Evaluation ({} blocks — measuring final performance)...", eval_blocks);
    shadow.run_training(eval_blocks, txs_per_block).await;

    // Phase 5: Final report
    shadow.print_final_report();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_all_attack_generators_produce_attacks() {
        let mut gen = TransactionGenerator::new();

        let attacks: Vec<(Transaction, Option<AttackType>)> = vec![
            gen.flash_loan_attack(),
            gen.reentrancy_attack(),
            gen.sandwich_attack_frontrun(),
            gen.sandwich_attack_backrun(),
            gen.oracle_manipulation_attack(),
            gen.governance_attack(),
            gen.infinite_mint_attack(),
            gen.rugpull_attack(),
            gen.double_spend_attack(),
            gen.sybil_flood_attack(),
            gen.selfish_mining_attack(),
            gen.eclipse_attack(),
            gen.long_range_attack(),
            gen.nothing_at_stake_attack(),
            gen.integer_overflow_attack(),
            gen.access_control_exploit(),
            gen.delegatecall_injection(),
            gen.tx_origin_phishing(),
            gen.signature_replay_attack(),
            gen.timestamp_manipulation_attack(),
            gen.frontrun_generic(),
            gen.bridge_exploit(),
            gen.fake_deposit_attack(),
            gen.validator_key_compromise(),
            gen.cross_chain_replay(),
            gen.dust_attack(),
            gen.mempool_flooding_attack(),
            gen.block_stuffing_attack(),
            gen.transaction_malleability_attack(),
        ];

        for (i, (_, attack_type)) in attacks.iter().enumerate() {
            assert!(attack_type.is_some(), "Attack generator {} should produce an attack type", i);
        }

        assert_eq!(attacks.len(), 29, "Should have 29 distinct attack generators");
    }

    #[test]
    fn test_legitimate_generators_produce_none() {
        let mut gen = TransactionGenerator::new();
        let (_, at) = gen.normal_transfer();
        assert!(at.is_none());
        let (_, at) = gen.normal_contract_call();
        assert!(at.is_none());
        let (_, at) = gen.normal_liquidity_add();
        assert!(at.is_none());
        let (_, at) = gen.normal_governance_vote();
        assert!(at.is_none());
    }

    #[test]
    fn test_attack_features_differ_from_normal() {
        let mut gen = TransactionGenerator::new();

        // Collect normal feature vectors
        let normal_features: Vec<Vec<f64>> = (0..100).map(|_| {
            let (tx, _) = if rand::thread_rng().gen_bool(0.5) {
                gen.normal_transfer()
            } else {
                gen.normal_contract_call()
            };
            tx.extract_features().to_vec()
        }).collect();

        // Compute normal mean
        let dim = normal_features[0].len();
        let normal_mean: Vec<f64> = (0..dim).map(|d| {
            normal_features.iter().map(|f| f[d]).sum::<f64>() / normal_features.len() as f64
        }).collect();

        // Each attack type should have at least one feature significantly different from normal mean
        let attack_generators: Vec<fn(&mut TransactionGenerator) -> (Transaction, Option<AttackType>)> = vec![
            TransactionGenerator::flash_loan_attack,
            TransactionGenerator::bridge_exploit,
            TransactionGenerator::block_stuffing_attack,
            TransactionGenerator::frontrun_generic,
        ];

        for gen_fn in attack_generators {
            let (tx, _) = gen_fn(&mut gen);
            let features = tx.extract_features().to_vec();
            let max_diff = features.iter().zip(&normal_mean)
                .map(|(a, b)| (a - b).abs())
                .fold(0.0_f64, f64::max);
            assert!(max_diff > 0.1, "Attack should differ significantly from normal");
        }
    }

    #[tokio::test]
    async fn test_shadow_network_basic() {
        let mut shadow = ShadowNetwork::new(10, 2);
        shadow.seed_all_attack_patterns();
        shadow.register_validators().await;

        // Run a short simulation
        for _ in 0..10 {
            shadow.run_block(20).await;
        }

        assert!(shadow.metrics.total_transactions > 0);
        assert!(shadow.metrics.actual_attacks > 0);
        assert!(shadow.metrics.true_positives > 0, "Should catch some attacks");
    }
}
