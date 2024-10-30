# Deployment Guide

This guide walks through the process of deploying a new Oracle using the ODV Multisig Charli3 Oracle system.

## Prerequisites

Before starting the deployment process, ensure you have:

1. Python 3.10 or later installed
2. Poetry package manager installed
3. Access to a Cardano node (via Blockfrost or Kupo/Ogmios)
4. Sufficient funds in your wallet
5. The platform authorization NFT
6. The Aiken blueprint file from the on-chain repository

## Installation

1. Clone the repository:
```bash
git clone https://github.com/Charli3-Official/odv-multisig-charli3-offchain-core.git
cd odv-multisig-charli3-offchain-core
```

2. Install dependencies:
```bash
poetry install
```

## Deployment Process

### 1. Prepare Configuration

Create a deployment configuration file (e.g., `deploy-testnet.yaml`) based on the templates in the Configuration Guide.

Key considerations:
- Choose appropriate network backend (Blockfrost or Kupo/Ogmios)
- Configure wallet access (mnemonic or key files)
- Set correct network addresses
- Configure token parameters
- Adjust timing parameters for your use case

### 2. Create Reference Scripts

Reference scripts can be created separately from the main deployment:

```bash
poetry run charli3 oracle create-reference-scripts \
    --config deploy-testnet.yaml \
    --manager \
    --nft
```

Options:
- `--manager`: Create oracle manager reference script
- `--nft`: Create NFT policy reference script
- `--force`: Force creation even if scripts exist

The manager reference script is reusable across deployments with the same configuration. The NFT policy script is unique per deployment.

### 3. Deploy Oracle

Run the main deployment command:

```bash
poetry run charli3 oracle deploy --config deploy-testnet.yaml
```

This process:
1. Creates reference scripts (if needed)
2. Mints oracle NFTs
3. Creates initial UTxOs with proper datums
4. Sets up the reward transport system

### 4. Verify Deployment

After deployment, verify:

1. Reference Scripts:
   - Manager script is available at reference address
   - NFT policy script is available (if created)

2. Oracle UTxOs:
   - Settings UTxO with CoreSettings NFT
   - Reward Account UTxO with RewardAccount NFT
   - Reward Transport UTxOs with RewardTransport NFTs
   - Aggregation State UTxOs with AggregationState NFTs

3. Token Distribution:
   - All NFTs minted correctly
   - NFTs distributed to correct UTxOs

## Cost Estimation

Deployment requires funds for:

1. Reference Scripts:
   - Manager script: ~55 ADA
   - NFT policy script: ~55 ADA (if created)

2. Oracle UTxOs:
   - Minimum UTxO value per output
   - Transaction fees
   - NFT minting fees

Ensure your wallet has sufficient funds before deployment.


## Transaction Monitoring

The deployment process provides status updates at each stage:

1. Reference Script Creation:
   ```
   [CHECKING_REFERENCE_SCRIPTS] Checking for existing reference scripts...
   [CREATING_MANAGER_REFERENCE] Creating manager reference script...
   [CREATING_NFT_REFERENCE] Creating NFT reference script...
   ```

2. Oracle Deployment:
   ```
   [BUILDING_START_TX] Building oracle start transaction...
   [SUBMITTING_START_TX] Submitting oracle start transaction...
   [WAITING_CONFIRMATION] Waiting for transaction confirmation...
   [COMPLETED] Oracle deployment completed!
   ```

3. Success Output:
   ```
   Deployment completed successfully!

   Reference Scripts:
   ✓ Manager reference script created
     TxHash: 1234...abcd
   ✓ NFT reference script created
     TxHash: 5678...efgh

   Oracle UTxOs:
   ✓ Settings UTxO created
   ✓ Reward Account UTxO created
   ✓ 4 Reward Transport UTxOs created
   ✓ 4 Aggregation State UTxOs created

   Start Transaction Hash: 90ab...cdef
   ```

## Troubleshooting

### Common Issues

1. **Insufficient Funds**
   ```
   Error: Failed to build transaction: INPUTS_EXHAUSTED
   ```
   Solution: Ensure wallet has sufficient ADA for all UTxOs and fees

2. **Missing Platform Auth NFT**
   ```
   Error: No UTxO found with platform auth NFT
   ```
   Solution: Verify platform auth NFT policy ID and ensure it's in the reference address

3. **Invalid Configuration**
   ```
   Error: Transport count must be at least 4
   ```
   Solution: Check configuration against requirements in Configuration Guide

4. **Network Issues**
   ```
   Error: Failed to submit transaction: Network timeout
   ```
   Solution: Verify network connectivity and backend service status

### Recovery Steps

1. **Failed Reference Scripts**
   - Reference scripts can be created separately
   - Use `--force` flag to recreate if needed
   ```bash
   poetry run charli3 oracle create-reference-scripts --config deploy.yaml --force
   ```

2. **Failed Start Transaction**
   - Check transaction status on chain
   - Verify UTxOs at script address
   - Rerun deployment if no UTxOs were created

3. **Partial Deployment**
   - Use blockchain explorer to verify created UTxOs
   - Contact support if NFTs were minted but UTxOs not created

## Post-Deployment Steps

1. **Record Important Information**
   - Save all transaction hashes
   - Document reference script UTxOs
   - Note oracle UTxO references

2. **Verify Oracle Settings**
   - Check fee configuration
   - Verify timing parameters
   - Confirm reward transport setup

3. **Backup Configuration**
   - Save deployment configuration
   - Document any custom parameters
   - Store reference addresses

## Support

If you encounter issues during deployment:

1. Check logs in `.logs/deployment.log`
2. Verify configuration against examples
3. Contact support with:
   - Configuration file (remove sensitive data)
   - Error messages and logs
   - Transaction hashes
   - Network information

## Security Considerations

1. **Key Management**
   - Secure storage of signing keys
   - Protection of mnemonics
   - Regular key rotation if needed

2. **Network Security**
   - Use secure connections to nodes
   - Protect API credentials
   - Monitor transaction activity

3. **Access Control**
   - Limit access to deployment tools
   - Secure configuration files
   - Audit deployment logs

## Additional Resources

1. **Documentation**
   - Configuration Guide
   - API Documentation
   - Contract Specifications

2. **Tools**
   - Cardano Explorer
   - Blockchain Tools
   - Monitoring Systems

3. **Support Channels**
   - Discord Community
   - GitHub Issues
   - Technical Support

Remember to keep your deployment documentation updated and maintain secure backups of all configuration and transaction information.
