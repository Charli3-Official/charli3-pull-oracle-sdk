# Deployment Guide

This guide covers the process of deploying a new Oracle using the ODV Multisig Charli3 Oracle system.

## Prerequisites

1. **System Requirements**
   - Python 3.10 or later
   - Poetry package manager
   - Git

2. **Network Access**
   - Blockfrost API access, or
   - Running Kupo/Ogmios nodes (Recommended)

3. **Resources**
   - Wallet with sufficient ADA
   - Platform authorization NFT
   - Aiken blueprint file

## Installation

1. Clone and setup:
```bash
git clone https://github.com/Charli3-Official/odv-multisig-charli3-offchain-core.git
cd odv-multisig-charli3-offchain-core
poetry install
```

2. Verify installation:
```bash
poetry run charli3 --help
```

## Deployment Process

### 1. Configuration Setup

1. Create deployment configuration file:
```bash
cp config/examples/testnet.yaml deploy-config.yaml
```

2. Edit configuration:
   - Set network backend details
   - Configure wallet access
   - Set token parameters
   - Adjust timing configuration
   - Review all parameters

3. Set environment variables:
```bash
export BLOCKFROST_PROJECT_ID="your-project-id"
# Add other required variables
```

### 2. Oracle Deployment

The main deployment command:

```bash
charli3 oracle deploy --config deploy-config.yaml
```

This process:

1. **Preparation Phase**
   - Validates configuration
   - Loads contracts
   - Checks prerequisites
   - Verifies platform auth NFT

2. **Reference Script Phase**
   - Checks for existing scripts
   - Creates manager reference script if needed
   - Waits for confirmation

3. **Oracle Creation Phase**
   - Creates oracle configuration
   - Builds start transaction
   - Mints oracle NFTs
   - Creates initial UTxOs
   - Distributes tokens

4. **Verification Phase**
   - Confirms transaction success
   - Verifies UTxO creation
   - Checks token distribution

### 3. Deployment Verification

After deployment completes, verify:

1. **Reference Scripts**
   ```bash
   # Check script address for:
   - Manager reference script
   - Correct script hash
   - Minimum ADA amount
   ```

2. **Oracle UTxOs**
   ```bash
   # Verify creation of:
   - Settings UTxO with CoreSettings NFT
   - Reward Account UTxO with RewardAccount NFT
   - Reward Transport UTxOs (configured count)
   - Aggregation State UTxOs (matching count)
   ```

3. **Token Distribution**
   ```bash
   # Confirm for each UTxO:
   - Correct NFT assignment
   - Proper datum structure
   - Sufficient ADA amount
   ```

## Resource Requirements

1. **ADA Requirements**
   - Reference Script: 64 ADA
   - Each UTxO: 2 ADA minimum
   - Transaction fees: ~1 ADA per transaction
   - Total: ~65 ADA + (4 ADA * transport_count)

2. **Token Requirements**
   - Platform authorization NFT
   - Fee token policy access (if using custom token)


## Troubleshooting

### Common Issues

1. **Configuration Errors**
   ```
   Error: ValidationError - Invalid configuration
   Solution: Check configuration guide for correct values
   ```

2. **Network Issues**
   ```
   Error: ChainQueryError - Failed to connect
   Solution: Verify backend services and credentials
   ```

3. **Resource Issues**
   ```
   Error: UTxOQueryError - Insufficient funds
   Solution: Ensure wallet has required ADA
   ```

4. **Authorization Issues**
   ```
   Error: Platform auth NFT not found
   Solution: Verify NFT in wallet and policy ID
   ```

### Recovery Procedures

1. **Failed Reference Script**
   ```bash
   # Create reference script separately
   poetry run charli3 oracle create-reference-script --config deploy-config.yaml
   ```

2. **Failed Deployment**
   - Check transaction status
   - Verify UTxOs and tokens
   - Clean up if needed
   - Retry deployment
