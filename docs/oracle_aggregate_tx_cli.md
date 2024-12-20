# Oracle Aggregate Transaction CLI Documentation

## Command Structure

```bash
charli3
├── aggregate_tx              # Oracle Aggregate transaction commands
│   ├── odv_aggregate        # ODV-aggregate commands
│   │   ├── submit          # Submit ODV transaction
│   │   └── status          # Check ODV status
│   └── rewards             # Reward-calculate commands
│       └── process         # Process pending rewards
├── simulator               # Simulation commands
│   └── run                # Run oracle odv aggregate simulation
└── generate-node-keys      # Generate node keys
```

## Configuration Files

### 1. Transaction Configuration (tx_config.yml)
```yaml
network:
  network: "TESTNET"  # TESTNET, MAINNET
  blockfrost:
    project_id: "testnetXYZ123"
  # Or use Ogmios/Kupo
  ogmios_kupo:
    ogmios_url: "ws://localhost:1337"
    kupo_url: "http://localhost:1442"

# Core oracle parameters
oracle_address: "addr_test1..."  # Oracle script address
policy_id: "1234..."            # Oracle NFT policy ID

# Fee token configuration
fee_token:
  fee_token_policy: "hex_policy_id_here"
  fee_token_name: "hex_token_name_here"

# Wallet configuration
wallet:
  mnemonic: "word1 word2 word3 ... word24"  # 24-word mnemonic phrase
```

### 2. Feed Data Format (feeds.json)
```json
{
  "node_feeds_sorted_by_feed": {
    "007df380aef26e44739db3f4fe67d8137446e630dab3df16d9fbddc5": 1000,
    "018ab1dd5f33ca2e0ae6ccb694ea379d841bf5f4d2d5756452a2117d": 1001,
    "e47c436dbd0d1f7642ce2f4a8e36c4facae2b8d9d4c3267380cb1f5f": 1001
  },
  "node_feeds_count": 3,
  "timestamp": 1734363765000
}
```

## Available Commands

### 1. ODV Transaction Commands

#### Submit ODV Transaction
```bash
charli3 aggregate-tx odv-aggregate submit \
  --config tx_config.yml \
  --feeds-file feeds.json \
  --node-keys-dir node_keys
```

Options:
- `--config`: Path to transaction configuration YAML
- `--feeds-file`: Path to JSON file containing node feeds
- `--node-keys-dir`: Directory containing node signing keys
- `--wait/--no-wait`: Wait for transaction confirmation (default: true)

#### Check ODV Status
```bash
charli3 aggregate-tx odv-aggregate status \
  --config tx_config.yml
```

This command shows:
- Empty Transport UTxOs count
- Pending Transport UTxOs count
- AggState UTxOs details
- Available ODV pairs
- Pending transactions details
- Expired AggState information

### 2. Reward Commands

#### Process Rewards
```bash
charli3 aggregate-tx rewards process \
  --config tx_config.yml \
  --batch-size 4
```

Options:
- `--batch-size`: Maximum number of transports to process (default: 8)
- `--wait/--no-wait`: Wait for transaction confirmation (default: true)

The command provides:
- Preview of rewards to be processed
- Transaction details after submission
- Distribution summary
- Platform fee calculations

### 3. Node Key Generation

```bash
charli3 generate-node-keys \
  --mnemonic "word1 word2 ... word24" \
  --count 4 \
  --start-index 0 \
  --required-sigs 3 \
  --output-dir node_keys
```

Options:
- `--mnemonic`: 24-word mnemonic phrase
- `--count`: Number of nodes to generate (default: 4)
- `--start-index`: Starting derivation index (default: 0)
- `--required-sigs`: Required signature count
- `--output-dir`: Output directory for key files (default: "node_keys")
- `--print-yaml/--no-print-yaml`: Print configuration in YAML format (default: true)

### 4. Simulation Commands

```bash
charli3 simulator run \
  --config sim_config.yml \
  --output results.json
```

Additional simulation configuration in config file:
```yaml
simulation:
  node_keys_dir: "node_keys"
  base_feed: 100
  variance: 0.02
  wait_time: 60
```


## Important Notes

### Security Considerations
1. Key Management:
   - Store node keys securely
   - Use environment variables for sensitive data
   - Never commit private keys or mnemonics

2. Transaction Security:
   - Verify node signatures before submission
   - Validate feed data format and values
   - Check timestamp validity
   - Ensure proper fee token configuration

### Common Issues and Solutions

1. Transaction Failures
   - Check node key permissions
   - Verify fee token balance
   - Ensure correct network configuration
   - Validate UTxO availability

2. Configuration Issues
   - Verify network settings match
   - Check policy IDs and token names
   - Validate node key directory structure
   - Ensure proper feed data format

3. Operational Tips
   - Monitor UTxO availability
   - Track reward distribution
   - Check node signature requirements
   - Maintain proper key backups
