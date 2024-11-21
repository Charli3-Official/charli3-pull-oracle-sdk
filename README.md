# ODV Multisig Charli3 Offchain Core

Core off-chain infrastructure for Charli3's Oracle Data Verification (ODV) system with multisig capabilities. This package provides comprehensive tooling for oracle operations, contract interactions, and blockchain integration.

## 🌟 Features

- **Oracle Data Verification (ODV)**
  - Aggregation of oracle data
  - Multi-signature validation
  - Reward distribution management
  - Oracle node operations

- **Smart Contract Integration**
  - Aiken blueprint parsing and handling
  - Plutus script management
  - Transaction building and validation

- **Blockchain Operations**
  - Chain state queries through Blockfrost or Kupo/Ogmios
  - Transaction validation and monitoring
  - Reference script management

## 📦 Installation & Setup

1. Clone the repository:
```bash
git clone https://github.com/Charli3-Official/odv-multisig-charli3-offchain-core.git
cd odv-multisig-charli3-offchain-core
```

2. Install dependencies using Poetry:
```bash
poetry install
```

3. Set up pre-commit hooks (recommended for development):
```bash
poetry run pre-commit install
```

## 🚀 Quick Start

### Multisig Platform Auth NFT Mint

#### Configure multisig settings in yaml:
Reference: configuration file (e.g., `deploy-testnet.yaml`):
```yaml
multisig:
  # platform_addr: "addr_test1..."
  threshold: 2  # Required signatures
  parties:
    - "wallet1_public_key_hash"
    - "wallet2_public_key_hash"
```

#### Option 1. Single Signature Flow (threshold = 1)
```bash
# Complete flow in single command
# - Builds transaction
# - Signs with configured wallet
# - Submits to network immediately
# - Returns tx ID and policy ID
charli3 platform token mint --config deploy-testnet.yaml
```

#### Option 2.  Multi-Signature Flow (threshold > 1)
```bash
# 1. First Wallet: Build and optionally sign
# - Creates transaction
# - Prompts to sign with current wallet
# - Generates tx_platform_mint.json
charli3 platform token mint --config deploy-testnet-wallet-1.yaml

# 2. Second Wallet: Add signature
# - Validates key hasn't signed
# - Updates transaction file
# - Shows signature progress
charli3 platform token sign-tx --config deploy-testnet-wallet-2.yaml --tx-file tx_platform_mint.json

# 3. Submit when all signatures collected
# - Validates signature threshold
# - Submits to network
# - Returns tx ID and policy ID
charli3 platform token submit-tx --config deploy-testnet-wallet-2.yaml --tx-file tx_platform_mint.json
```


### Basic Oracle Deployment

1. Create a deployment configuration file (e.g., `deploy-testnet.yaml`):
```yaml
network:
  network: "testnet"
  blockfrost:
    project_id: "your-project-id"
  wallet:
    mnemonic: "your 24 word mnemonic"
    # OR use key files:
    # payment_skey_path: "path/to/payment.skey"
    # payment_vkey_path: "path/to/payment.vkey"
    # stake_vkey_path: "path/to/stake.vkey"

addresses:
  admin_address: "addr_test..."  # Address for reference scripts
  script_address: "addr_test..."     # Address for oracle UTxOs

tokens:
  platform_auth_policy: "hex_policy_id_for_platform_auth_nft"
  fee_token_policy: "hex_policy_id_for_fee_token"
  fee_token_name: "hex_asset_name_for_fee_token"

fees:
  node_fee: 1000000      # 1 ADA
  platform_fee: 500000   # 0.5 ADA

timing:
  closing_period: 3600000        # 1 hour in ms
  reward_dismissing_period: 7200000  # 2 hours in ms
  aggregation_liveness: 300000   # 5 minutes in ms
  time_uncertainty: 60000        # 1 minute in ms
  iqr_multiplier: 150           # 1.5x

transport_count: 4  # Number of reward transport UTxOs
blueprint_path: "artifacts/plutus.json"  # Path to Aiken blueprint
```

2. Deploy the oracle:
```bash
poetry run charli3 oracle deploy --config deploy-testnet.yaml
```

### Reference Scripts Management

Create reference scripts separately:
```bash
poetry run charli3 oracle create-reference-scripts \
    --config deploy-testnet.yaml \
    --manager \
    --nft
```

## 📖 Documentation

### Configuration Guide

The deployment configuration supports multiple options and backends:

1. **Network Configuration**
   - Support for Mainnet and Testnet
   - Choose between Blockfrost or Kupo/Ogmios backends
   - Wallet configuration through mnemonic or key files

2. **Address Configuration**
   - Reference address for storing reference scripts
   - Script address for oracle UTxOs

3. **Token Configuration**
   - Platform authorization NFT policy ID
   - Fee token specifications
   - Configurable token names for oracle NFTs

4. **Timing Parameters**
   - Closing period length
   - Reward dismissing period
   - Aggregation liveness period
   - Time uncertainty handling
   - IQR fence multiplier for outlier detection

For detailed configuration options, see [Configuration Guide](docs/configuration.md).

### Deployment Process

The oracle deployment process consists of several steps:

1. **Reference Script Creation**
   - Oracle manager script (reusable across deployments)
   - NFT minting policy script (unique per deployment)

2. **Oracle Start Transaction**
   - Mints oracle NFTs
   - Creates initial UTxOs with proper datums
   - Sets up reward transport system

3. **Post-Deployment Verification**
   - Confirms UTxO creation
   - Verifies NFT minting
   - Validates script parameters

For detailed deployment instructions, see [Deployment Guide](docs/deployment.md).

## 🔧 Development

### Project Structure

```
odv-multisig-charli3-offchain-core/
├── charli3_offchain_core/
│   ├── __init__.py
│   │
│   ├── api/                    # External API integrations
│   │   ├── __init__.py
│   │   ├── base.py            # Base API client
│   │   ├── kupo.py            # Kupo API integration
│   │   └── blockfrost.py      # Blockfrost API integration
│   │
│   ├── blockchain/            # Blockchain operations
│   │   ├── __init__.py
│   │   ├── chain_query.py     # Unified chain query interface
│   │   ├── transactions.py    # Transaction management
│   │   ├── network.py         # Network configuration & timing
│   │   └── exceptions.py      # Chain operation exceptions
│   │
│   ├── contracts/             # Contract interaction layer
│   │   ├── __init__.py
│   │   └── aiken_loader.py    # Aiken blueprint loader & handler
│   │
│   ├── models/                # Data models
│   │   ├── __init__.py
│   │   ├── oracle_datums.py   # Oracle datum types
│   │   └── oracle_redeemers.py # Oracle redeemer types
│   │
│   ├── oracle/                # Oracle operations
│   │   ├── __init__.py
│   │   ├── config.py          # Oracle configuration
│   │   │
│   │   └── deployment/        # Deployment operations
│   │       ├── __init__.py
│   │       ├── orchestrator.py # Deployment coordination
│   │       ├── oracle_start_builder.py  # Start transaction
│   │       ├── reference_script_builder.py  # Script creation
│   │       └── reference_script_finder.py   # Script lookup
│   │
│   └── cli/                   # Command line interface
│       ├── __init__.py
│       ├── base.py            # CLI utilities
│       ├── oracle.py          # Oracle commands
│       ├── contracts.py       # Contract commands
│       │
│       └── config/            # CLI configuration
│           ├── __init__.py
│           ├── deployment.py   # Deployment config
│           └── keys.py         # Key management
│
├── docs/                      # Documentation
│   ├── configuration.md       # Configuration guide
│   └── deployment.md          # Deployment guide
│
├── examples/                  # Example configurations
│   ├── mainnet.yaml          # Mainnet deployment config
│   └── testnet.yaml          # Testnet deployment config
│
├── .gitignore                # Git ignore rules
├── .pre-commit-config.yaml   # Pre-commit hooks
├── pyproject.toml            # Project configuration
├── poetry.lock               # Dependency lock file
└── README.md                 # Project readme
```

### Running Tests

```bash
poetry run pytest
```

### Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to your branch
5. Create a Pull Request
