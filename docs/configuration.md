# Configuration Guide

This document covers all configuration options available in the ODV Multisig Charli3 Oracle deployment system.

## Configuration File Format

The deployment configuration uses YAML format and supports environment variable resolution. Environment variables can be referenced using the `$` prefix.

Example:
```yaml
network:
  blockfrost:
    project_id: $BLOCKFROST_PROJECT_ID
```

## Network Configuration

The system supports two backend options: Blockfrost or Kupo/Ogmios. You must configure exactly one of these.

### Blockfrost Backend

```yaml
network:
  network: "mainnet"  # or "testnet"
  blockfrost:
    project_id: "your-project-id"
    api_url: "optional-custom-url"  # Optional
```

### Kupo/Ogmios Backend

```yaml
network:
  network: "mainnet"  # or "testnet"
  ogmios_kupo:
    ogmios_url: "ws://localhost:1337"    # WebSocket URL required
    kupo_url: "http://localhost:1442"     # HTTP URL required
```

### Wallet Configuration

Two options are available for wallet configuration:

Using mnemonic (recommended for development):
```yaml
network:
  wallet:
    mnemonic: "your 24 word mnemonic"
```

Using key files:
```yaml
network:
  wallet:
    payment_skey_path: "path/to/payment.skey"
    payment_vkey_path: "path/to/payment.vkey"
    stake_vkey_path: "path/to/stake.vkey"
```

## Token Configuration

```yaml
tokens:
  # Policy ID of the platform authorization NFT (28 bytes)
  platform_auth_policy: "hex_policy_id"

  # Reward and Rate token details
  # Use empty strings for ADA (Lovelace) or when the rate is not specified
  reward_token_policy: "hex_policy_id"  # 28 bytes
  reward_token_name: "hex_asset_name"   # Asset name in hex

  rate_token_policy: "hex_policy_id"  # 28 bytes
  rate_token_name: "hex_asset_name"   # Asset name in hex
```

### Oracle NFT Token Names

Token names are automatically configured based on the network:

**Mainnet:**
- Core Settings: "C3CS"
- Reward Account: "C3RA"
- Reward Transport: "C3RT"
- Aggregation State: "C3AS"

**Testnet:**
- Core Settings: "CoreSettings"
- Reward Account: "RewardAccount"
- Reward Transport: "RewardTransport"
- Aggregation State: "AggregationState"

## Fee Configuration

```yaml
fees:
  # Fee for oracle nodes (in lovelace)
  node_fee: 1000000      # 1 ADA

  # Fee for platform (in lovelace)
  platform_fee: 500000   # 0.5 ADA
```

## Timing Configuration

```yaml
timing:
  # Period during which oracle can be paused
  pause_period: 3600000        # 1 hour

  # Period for dismissing unclaimed rewards
  reward_dismissing_period: 7200000  # 2 hours (must be > pause_period)

  # Time window for aggregating oracle data
  aggregation_liveness: 300000   # 5 minutes

  # Allowed time uncertainty for oracle operations
  time_uncertainty_aggregation: 120000 # 2 minutes in ms
  time_uncertainty_platform: 180000 # 3 minutes in ms

  # Multiplier for IQR-based outlier detection (percentage)
  iqr_multiplier: 150           # 1.5x
```

## Deployment Options

```yaml
# Number of reward transport UTxOs (minimum 4)
transport_count: 4

# Path to Aiken blueprint file
blueprint_path: "artifacts/plutus.json"

# Create manager reference script
create_reference: true
```

## Validation Rules

The configuration system enforces these validation rules:

1. **Network Backend**
   - Must specify either Blockfrost or Kupo/Ogmios backend
   - Cannot specify both backends
   - Valid network type (mainnet/testnet)

2. **Wallet Configuration**
   - Must provide either mnemonic or all key file paths
   - Key files must exist and be readable

3. **Token Configuration**
   - Platform auth policy ID must be 28 bytes
   - Fee token policy ID must be 28 bytes
   - Valid hex values for all IDs and names

4. **Transport Count**
   - Minimum of 4 transport UTxOs required
   - Must be greater than 0

5. **Timing Parameters**
   - All periods must be positive
   - Reward dismissing period must be greater than pause period
   - Valid ranges for all time values

6. **Fees**
   - Both node and platform fees must be positive
   - Values in lovelace (1 ADA = 1,000,000 lovelace)

## Example Configuration

### Complete Configuration Example

```yaml
network:
  network: "testnet"
  blockfrost:
    project_id: "testnet-xyz"
  wallet:
    mnemonic: "your 24 word mnemonic"

tokens:
  platform_auth_policy: "1234...cdef"  # 28 bytes hex
  reward_token_policy: "5678...abcd"      # 28 bytes hex
  reward_token_name: "434841524C4933"     # "CHARLI3" in hex

  rate_token_policy: "5678...abcd"      # 28 bytes hex
  rate_token_name: "434841524C4933"     # "CHARLI3" in hex
fees:
  node_fee: 1000000    # 1 ADA
  platform_fee: 500000 # 0.5 ADA

timing:
  pause_period: 3600000
  reward_dismissing_period: 7200000
  aggregation_liveness: 300000
  time_uncertainty_aggregation: 120000 # 2 minutes in ms
  time_uncertainty_platform: 180000 # 3 minutes in ms
  iqr_multiplier: 150

transport_count: 4
blueprint_path: "artifacts/plutus.json"
create_reference: true
```

## Environment Variables

Use environment variables for sensitive data:

```bash
export BLOCKFROST_PROJECT_ID="your-project-id"
export WALLET_MNEMONIC="your 24 word mnemonic"
export OGMIOS_URL="ws://localhost:1337"
export KUPO_URL="http://localhost:1442"
```
