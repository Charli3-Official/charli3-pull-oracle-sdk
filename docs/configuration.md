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
    ogmios_url: "http://localhost:1337"
    kupo_url: "http://localhost:1442"
```

### Wallet Configuration

Using mnemonic:
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
  # Policy ID of the platform authorization NFT
  platform_auth_policy: "hex_policy_id"

  # Fee token details
  fee_token_policy: "hex_policy_id"
  fee_token_name: "hex_asset_name"
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
  # Fee for oracle nodes in lovelace
  node_fee: 1000000      # 1 ADA

  # Fee for platform in lovelace
  platform_fee: 500000   # 0.5 ADA
```

## Timing Configuration

```yaml
timing:
  # Period during which oracle can be closed (milliseconds)
  closing_period: 3600000        # 1 hour

  # Period for dismissing unclaimed rewards (milliseconds)
  reward_dismissing_period: 7200000  # 2 hours

  # Time window for aggregating oracle data (milliseconds)
  aggregation_liveness: 300000   # 5 minutes

  # Allowed time uncertainty for oracle operations (milliseconds)
  time_uncertainty: 60000        # 1 minute

  # Multiplier for IQR-based outlier detection (percentage)
  iqr_multiplier: 150           # 1.5x
```

## Deployment Options

```yaml
# Number of reward transport UTxOs to create
transport_count: 4

# Path to Aiken blueprint file
blueprint_path: "artifacts/plutus.json"

# Reference script creation options
create_reference: true       # Create manager reference script
create_nft_reference: false  # Create NFT policy reference script
```

## Environment Variables

The configuration system supports using environment variables for sensitive data:

```bash
export BLOCKFROST_PROJECT_ID="your-project-id"
export WALLET_MNEMONIC="your 24 word mnemonic"
```

Then in your YAML:
```yaml
network:
  blockfrost:
    project_id: $BLOCKFROST_PROJECT_ID
  wallet:
    mnemonic: $WALLET_MNEMONIC
```

## Validation Rules

The configuration system enforces several validation rules:

1. **Network Backend**
   - Must specify either Blockfrost or Kupo/Ogmios backend
   - Cannot specify both backends simultaneously

2. **Wallet Configuration**
   - Must provide either mnemonic or all key file paths
   - Key files must exist and be readable

3. **Transport Count**
   - Must be greater than 0
   - Mainnet requires minimum of 4 transport UTxOs
   - Testnet allows custom transport count

4. **Timing Parameters**
   - All periods must be positive
   - Reward dismissing period must be greater than closing period

5. **Fees**
   - Both node and platform fees must be positive
   - Fees are specified in lovelace (1 ADA = 1,000,000 lovelace)

## Example Configurations

### Minimal Testnet Configuration

```yaml
network:
  network: "testnet"
  blockfrost:
    project_id: "testnet-xyz"
  wallet:
    mnemonic: "your 24 word mnemonic"

timing:
  closing_period: 3600000
  reward_dismissing_period: 7200000
  aggregation_liveness: 300000
  time_uncertainty: 60000
  iqr_multiplier: 150

tokens:
  platform_auth_policy: "policy_id"
  fee_token_policy: "policy_id"
  fee_token_name: "hex_name"

fees:
  node_fee: 1000000
  platform_fee: 500000

transport_count: 4
```

### Full Mainnet Configuration

```yaml
network:
  network: "mainnet"
  ogmios_kupo:
    ogmios_url: "http://localhost:1337"
    kupo_url: "http://localhost:1442"
  wallet:
    payment_skey_path: "keys/payment.skey"
    payment_vkey_path: "keys/payment.vkey"
    stake_vkey_path: "keys/stake.vkey"

tokens:
  platform_auth_policy: "policy_id"
  fee_token_policy: "policy_id"
  fee_token_name: "hex_name"

fees:
  node_fee: 2000000
  platform_fee: 1000000

timing:
  closing_period: 3600000
  reward_dismissing_period: 7200000
  aggregation_liveness: 300000
  time_uncertainty: 60000
  iqr_multiplier: 150

transport_count: 8
blueprint_path: "artifacts/plutus.json"
create_reference: true
create_nft_reference: true
```
