/// AEGIS Shadow Network — Training Binary
///
/// Trains AEGIS on ALL known blockchain attack types:
/// - DeFi: flash loans, reentrancy, sandwich, oracle manipulation, governance, infinite mint, rugpulls
/// - Protocol: double spend, sybil, selfish mining, eclipse, long-range, nothing-at-stake
/// - Smart Contract: integer overflow, access control, delegatecall, tx.origin, signature replay
/// - Bridge: bridge exploits, fake deposits, validator key compromise, cross-chain replay
/// - Network: dust attacks, mempool flooding, block stuffing, tx malleability
///
/// Usage: cargo run --release --bin aegis-shadow

#[tokio::main]
async fn main() {
    aegis::shadow::run_shadow_simulation().await;
}
