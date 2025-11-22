#!/usr/bin/env bash

set -e  # Exit on any command failure
set -x  # Print each command before executing it

# Initialize test result to 0
test_result=0

# Function to kill processes
kill_processes() {
  # Capture the exit status of the script (or the command that triggered the trap)
  local saved_exit_status=$?
  
  echo "Shutting down the cluster..."
  ./bin/devkit.sh stop

  # Determine the final exit code
  # If test_result is non-zero, use it (test failure).
  # Otherwise, use saved_exit_status (script crash or success).
  if [ $test_result -ne 0 ]; then
    exit $test_result
  else
    exit $saved_exit_status
  fi
}

# Function to generate test node keys if they don't exist
ensure_node_keys() {
  # Check if node_keys directory exists and has content
  if [ ! -d "node_keys" ] || [ -z "$(ls -A node_keys 2>/dev/null)" ]; then
    echo "Generating test node keys..."

    # Test mnemonic (DO NOT USE IN PRODUCTION)
    TEST_MNEMONIC="test test test test test test test test test test test test test test test test test test test test test test test sauce"

    # Create output directory
    NODE_KEYS_DIR="./node_keys"
    mkdir -p "$NODE_KEYS_DIR"

    # Generate node keys using the CLI
    poetry run charli3 generate-node-keys \
      --mnemonic "$TEST_MNEMONIC" \
      --count 9 \
      --start-index 0 \
      --output-dir "$NODE_KEYS_DIR"

    echo "Node keys generated successfully at $NODE_KEYS_DIR"
  else
    echo "Using existing node keys from node_keys directory"
  fi
}

# Trap the SIGINT, SIGTERM, and EXIT signals and call the function to kill processes
trap 'kill_processes' SIGINT SIGTERM EXIT

# Ensure test node keys are available
ensure_node_keys

# Start the node in the background
./bin/devkit.sh stop && ./bin/devkit.sh start create-node -o --start -e 1000 --era conway >/dev/null 2>&1 &
# Wait for the node to start
echo "Waiting for the node to start..."
sleep 70

# Tests
run_test() {
  local test_pattern="$1"
  poetry run pytest tests -v -k "$test_pattern"

  # Capture the exit code of the test
  test_result=$?

  # Exit if the test fails
  if [ $test_result -ne 0 ]; then
    echo "Test pattern $test_pattern failed."
    exit $test_result
  fi
}

run_test_multiple_times() {
  local test_pattern="$1"
  local count="$2"
  local delay="$3"

  for i in $(seq 1 "$count"); do
    echo "Running test iteration $i for pattern: $test_pattern"
    run_test "$test_pattern"
    sleep "$delay"
  done
}

# Execute tests in order

# 1. Initial Setup & Core Components
# 1.1. Create Platform Auth NFT
run_test "TestPlatformAuth"

# 1.2. Create TestC3 Reward Tokens
run_test "TestRewardToken"

# 1.3. Deploy oracle
run_test "TestDeployment"

# 1.4. Create reference script
run_test "TestCreateReferenceScript"

# 2. Oracle Functionality
# 2.1. Run aggregate tests
run_test "TestAggregate"

# 2.2. Test node reward collection
run_test "TestNodeCollect"

# 2.3. Test platform reward collection
run_test "TestPlatformCollect"

# 2.4. Oracle Pause and Resume
run_test "TestOraclePauseResume"

# 2.5. Oracle Remove
run_test "TestOracleRemove"

# 2.6. Additional Aggregate Tests (Planned)
# run_test_multiple_times "TestAggregate" 1 10

# 3. Governance Functions
# 3.1. Test removing nodes
run_test "TestRemoveNodes"

# 3.2. Test adding nodes
run_test "TestAddNodes"

# 3.3. Test editing settings
run_test "TestEditSettings"

# 3.4. Test scaling up
run_test "TestScaleUp"

# 3.5. Test scaling down
run_test "TestScaleDown"

# 4. Multisig Functionality
# 4.1. Test multisig platform auth
run_test "TestMultisigPlatformAuth"

# 4.2. Test multisig deployment
run_test "TestMultisigDeployment"

# 4.3. Test multisig reference script
run_test "TestMultisigReferenceScript"

# 4.4. Test multisig governance
run_test "TestMultisigGovernance"

# Exit with the result of the last test
exit $test_result
