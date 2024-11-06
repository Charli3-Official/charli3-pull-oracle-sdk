# Oracle Transaction CLI Configuration Examples

## 1. Transaction Configuration (tx-config.yaml)
```yaml
# Network Configuration
network:
  network: "TESTNET"  # TESTNET, MAINNET
  blockfrost:
    project_id: "testnetXYZ123"
  # Or use Ogmios/Kupo
  ogmios_kupo:
    ogmios_url: "ws://localhost:1337"
    kupo_url: "http://localhost:1442"

# Core oracle parameters
script_address: "addr_test1..."  # Oracle script address
policy_id: "1234..."            # Oracle NFT policy ID

# Wallet configuration with mnemonic
wallet:
  mnemonic: "word1 word2 word3 ... word24"  # 24-word mnemonic phrase
```

## 2. ODV Feed Data (feeds.json)
```json
{
  "node_feeds": {
    "1": {
      "feed_value": 1234567,
      "signature": "845d0f688b8c831c9c0b9439451bc1ca5eb4874906f8f8265ef2129e42cbf3c01e7750853e87f741675e8e0bab8b6ec1661121284abcdb22da10511a0614a508",
      "verification_key": "5820f2129e42cbf3c01e7750853e87f741675e8e0bab8b6ec1661121284abcdb22da"
    },
    "2": {
      "feed_value": 1234890,
      "signature": "84a7f78c0b9431bc1ca5eb48f8f8265ef2129e42cbf3c01e775085674167bab8b6ec1661121284abcdb22da10511a0614a5080f688b8c831c9c0b943945d0f68",
      "verification_key": "5820bab8b6ec1661121284abcdb22daf2129e42cbf3c01e7750853e87f741675e8e0"
    },
    "3": {
      "feed_value": 1234678,
      "signature": "845d0f688b8cf8f8265ef2129e42cbf3c01e775085831c9c0b9439451bc1ca5eb48749063e87f741675e8e0bab8b6ec1661121284abcdb22da10511a0614a508",
      "verification_key": "58201121284abcdb22daf2129e42cbf3c01e7750853e87f741675e8e0bab8b6ec166"
    }
  },
  "timestamp": 1699284000000,
  "feed_count": 3
}
```

## Available Commands

### ODV Commands
1. Submit ODV Transaction:
```bash
# Submit ODV with feed data
charli3 tx odv submit \
  --config tx-config.yaml \
  --feeds-file feeds.json \
  --wait
```

2. Check ODV Status:
```bash
# Check current ODV status
charli3 tx odv status \
  --config tx-config.yaml
```

### Reward Commands
1. Process Rewards:
```bash
# Process rewards with batch size
charli3 tx rewards process \
  --config tx-config.yaml \
  --batch-size 4 \
  --wait
```

2. Check Reward Status:
```bash
# Check overall reward status
charli3 tx rewards status \
  --config tx-config.yaml
```

3. Check Node Rewards:
```bash
# Check rewards for specific node
charli3 tx rewards check-node \
  --config tx-config.yaml \
  --node-id 1
```

## File Structure
```
project/
├── config/
│   └── tx-config.yaml
└── data/
    └── feeds.json
```

## Configuration Notes

### Transaction Configuration
1. Network Settings:
   - Choose between TESTNET and MAINNET
   - Configure either Blockfrost or Ogmios/Kupo backend
   - Blockfrost requires valid project ID
   - Ogmios/Kupo requires valid endpoint URLs

2. Oracle Parameters:
   - Script address must be a valid Cardano address
   - Policy ID must be in hex format (28 bytes)
   - All addresses should match the selected network

3. Wallet Configuration:
   - Mnemonic must be a valid 24-word seed phrase
   - Can use environment variable: `$WALLET_MNEMONIC`
   - Keep mnemonic secure and never commit to version control

### Feed Data Requirements
1. Node Feeds:
   - Each node must provide feed value, signature, and verification key
   - Feed values must be within valid protocol range
   - Node IDs must be unique positive integers

2. Signatures:
   - Must be valid Ed25519 signatures in hex format
   - Must be 128 characters long (64 bytes)
   - Must sign the corresponding feed value and timestamp

3. Verification Keys:
   - Must be valid Ed25519 public keys in hex format
   - Must be 64 characters long (32 bytes)
   - Must start with "5820" prefix

4. Timestamp:
   - Must be UTC milliseconds
   - Must be within protocol's valid time window
   - Must match the signed message timestamp

## Environment Variables
You can use environment variables in the configuration file:
```yaml
network:
  blockfrost:
    project_id: "$BLOCKFROST_PROJECT_ID"

wallet:
  mnemonic: "$WALLET_MNEMONIC"
```

## Security Considerations
1. Protect Sensitive Data:
   - Use environment variables for sensitive values
   - Never commit mnemonics or private keys
   - Keep Blockfrost project IDs private

2. Transaction Validation:
   - Verify feed data before submission
   - Check node signatures and verification keys
   - Ensure timestamp is within valid range
   - Validate feed values against protocol limits

3. Network Security:
   - Use secure connections for Blockfrost/Ogmios/Kupo
   - Validate SSL certificates when applicable
   - Keep backend endpoints secure and authenticated

## Common Issues
1. Transaction Failures:
   - Insufficient funds in wallet
   - Invalid feed signatures
   - Timestamp out of range
   - Network connectivity issues

2. Configuration Problems:
   - Mismatched network settings
   - Invalid addresses or policy IDs
   - Incorrect backend URLs
   - Malformed feed data

3. Operational Issues:
   - No available empty UTxO pairs
   - Pending transactions timeout
   - Backend service unavailability
