#!/usr/bin/env bash

set -e  # Exit on any command failure
set -x  # Print each command before executing it

# Function to kill processes
kill_processes() {
  echo "Shutting down the cluster..."
  ./bin/devkit.sh stop

  # Preserve the exit code from tests
  exit $test_result
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
#0. Create Platform Auth NFT
run_test "TestPlatformAuth"

# 0.5. Create TestC3 Reward Tokens
run_test "TestRewardToken"

# 1. Deploy oracle
run_test "TestDeployment"

# 2. Create reference script
run_test "TestCreateReferenceScript"

# 3. Run aggregate tests multiple times
run_test "TestAggregate"

# 4. Test reward collection
run_test "TestNodeCollect"
run_test "TestPlatformCollect"

# # 5. Test reward collection
run_test "TestNodeCollect or TestPlatformCollect"

# 5. Test governance functions
# 5.1
run_test "TestRemoveNodes"
# 5.2
run_test "TestAddNodes"
# 5.3
run_test "TestEditSettings"
# 5.4
run_test "TestScaleUp"
# 5.5
run_test "TestScaleDown"

# 6. Oracle Pause and Resume
run_test "TestOraclePauseResume"

# 7. Dismiss Rewards
run_test "TestDismissRewards"

# 8. Run aggregate tests again to verify it still works after changes
# run_test_multiple_times "TestAggregate" 1 10

# 9. Oracle Remove
run_test "TestOracleRemove"

# 10. Test multisig functionality
run_test "TestMultisigPlatformAuth"
run_test "TestMultisigDeployment"
run_test "TestMultisigReferenceScript"
run_test "TestMultisigGovernance"

# Stop the cluster (this will also be handled by kill_processes on EXIT)
./bin/devkit.sh stop

# Exit with the result of the last test
exit $test_result
