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
  - Chain state queries
  - Transaction validation
  - Integration with Kupo and Blockfrost

- **Administration Tools**
  - Oracle settings management
  - Node authorization
  - Administrative operations

## 📦 Installation

For development:
```bash
git clone https://github.com/Charli3-Official/odv-multisig-charli3-offchain-core.git
cd odv-multisig-charli3-offchain-core
```

## 🏗️ Project Structure

```
odv-multisig-charli3-offchain-core/
├── .github/
│   └── workflows/
│       ├── test.yml
│       ├── lint.yml
│       ├── publish.yml
│       └── docs.yml
│
├── src/
│   └── charli3-offchain-core/
│       ├── __init__.py
│       │
│       ├── api/             # External API integrations
│       │   ├── __init__.py
│       │   ├── base.py      # Base API client
│       │   ├── kupo.py      # Kupo API integration
│       │   └── blockfrost.py # Blockfrost API integration
│       │
│       ├── blockchain/      # Blockchain operations
│       │   ├── __init__.py
│       │   ├── chain_query.py  # Chain state queries
│       │   └── tx_validation.py # Transaction validation
│       │
│       ├── contracts/       # Contract interaction layer
│       │   ├── __init__.py
│       │   ├── aiken.py     # Aiken blueprint handling
│       │   └── plutus.py    # Plutus script utilities
│       │
│       ├── oracle/          # Oracle operations & transactions
│       │   ├── __init__.py
│       │   ├── transactions.py # Oracle-specific transactions
│       │   ├── aggregate.py    # ODV aggregation & scaling
│       │   ├── settings.py     # Oracle settings management
│       │   ├── rewards.py      # Reward management
│       │   ├── node.py         # Oracle node operations
│       │   ├── admin.py        # Oracle admin operations
│       │   └── checks.py       # Oracle validation checks
│       │
│       ├── cli/             # Command line interface
│       │   ├── __init__.py
│       │   ├── commands/
│       │   │   ├── __init__.py
│       │   │   ├── oracle.py
│       │   │   └── contracts.py
│       │   └── simulator.py
│       │
│       └── utils/            # Shared utilities
│           ├── __init__.py
│           ├── cardano.py    # Cardano network utilities
|           ├── consensus.py  # Consensus mechanisms
│           ├── nft.py        # Platform NFT authorization
│           ├── exceptions.py # Custom exceptions
│           ├── logging.py    # Logging configuration
│           └── config.py     # Configuration management
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── api/
│   ├── blockchain/
│   ├── contracts/
│   ├── oracle/
│   ├── cli/
│   └── utils/
│
├── examples/
│   ├── oracle_operations.py
│   ├── contract_interaction.py
│
├── docs/
│   ├── guides/
│   │   ├── getting_started.md
│   │   ├── oracle_management.md
│   │   └── contract_interaction.md
│
├── .gitignore
├── .pre-commit-config.yaml
├── pyproject.toml
└── README.md
```
