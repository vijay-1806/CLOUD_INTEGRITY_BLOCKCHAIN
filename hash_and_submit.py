"""
hash_and_submit.py  —  FAST BATCH submission
All new lines submitted in ONE transaction instead of one per line.
"""
import hashlib
import json
import os
import sys
import time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from web3 import Web3
from merkle import build_merkle_tree

# ── Config ────────────────────────────────────────────────────────
BASE_DIR             = os.path.dirname(os.path.abspath(__file__))
RPC_URL              = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
CONTRACT_ADDRESS_V1  = os.environ.get("CONTRACT_ADDRESS_V1", "0xE89d89d78b1a2BBA11Cb36C0750c28cBbd118862")
CONTRACT_ADDRESS_V2  = os.environ.get("CONTRACT_ADDRESS_V2", "0xC339e3B383333CAB68EbA145dEf8904864151c2E")
PRIVATE_KEY          = os.environ.get("PRIVATE_KEY", "0x9c7bf0754e9b13d38d2b71a69da799f76545991b97918ae1e000f400437d51b2")
ACCOUNT              = os.environ.get("ACCOUNT", "0x8b629ce3BB085B061D95C7f0d14d2BF63ECbA758")
INVESTIGATOR_ID      = "INV-007"
CHAIN_ID             = int(os.environ.get("CHAIN_ID", 12345))
ABI_V1_PATH          = os.path.join(BASE_DIR, "LogIntegrity_abi.json")
ABI_V2_PATH          = os.path.join(BASE_DIR, "LogIntegrityV2_abi.json")
LEAVES_FILE          = os.path.join(BASE_DIR, "original_leaves.json")
OFFSET_FILE          = os.path.join(BASE_DIR, "offset_tracker.json")

# ── Connect ───────────────────────────────────────────────────────
w3 = Web3(Web3.HTTPProvider(RPC_URL))
contract_v1, contract_v2 = None, None
if w3.is_connected():
    if os.path.exists(ABI_V1_PATH):
        with open(ABI_V1_PATH) as f:
            contract_v1 = w3.eth.contract(address=CONTRACT_ADDRESS_V1, abi=json.load(f))
    if os.path.exists(ABI_V2_PATH):
        with open(ABI_V2_PATH) as f:
            contract_v2 = w3.eth.contract(address=CONTRACT_ADDRESS_V2, abi=json.load(f))

def sha256_line(line: str) -> str:
    return hashlib.sha256(line.strip().encode()).hexdigest()

def load_offset() -> dict:
    if os.path.exists(OFFSET_FILE):
        with open(OFFSET_FILE) as f:
            return json.load(f)
    return {}

def save_offset(state: dict):
    with open(OFFSET_FILE, "w") as f:
        json.dump(state, f, indent=2)

def send_tx(fn_call, nonce, label="tx"):
    """Send a single transaction with given nonce."""
    tx = fn_call.build_transaction({
        "chainId": CHAIN_ID,
        "gas": 500000,
        "gasPrice": w3.to_wei("2", "gwei"),
        "nonce": nonce,
    })
    signed  = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"  [{label}] sent: {tx_hash.hex()[:20]}...")
    return tx_hash

def submit_new_entries(log_file: str, case_id: str):
    """
    FAST: Sends ALL new lines in rapid fire (no waiting between txs).
    Only waits for the LAST transaction to confirm.
    """
    if not w3.is_connected():
        print("❌ Web3 not connected.")
        return False

    if not os.path.exists(log_file):
        print(f"⚠️ Log file not found: {log_file}")
        return False

    try:
        with open(log_file, "r") as f:
            all_lines = [line for line in f.readlines() if line.strip()]
    except Exception as e:
        print(f"⚠️ Could not read {log_file}: {e}")
        return False

    current_count = len(all_lines)
    current_size  = os.path.getsize(log_file)

    state     = load_offset()
    key       = f"{case_id}::{log_file}"
    case_state = state.get(key, {"last_line_count": 0, "last_file_size": 0})
    last_count = case_state["last_line_count"]
    last_size  = case_state["last_file_size"]

    # Detect truncation
    if current_size < last_size and current_count < last_count:
        print(f"🚨 TRUNCATION DETECTED. Resetting offset.")
        last_count, last_size = 0, 0

    new_lines = all_lines[last_count:]
    if not new_lines:
        print("✅ No new lines to submit.")
        return True

    print(f"\n📤 Batch submitting {len(new_lines)} new line(s) for {case_id}...")

    # Get starting nonce
    nonce = w3.eth.get_transaction_count(ACCOUNT)
    last_tx_hash = None

    # FAST: Fire all transactions without waiting
    for i, line in enumerate(new_lines):
        global_index = last_count + i
        entry_hash   = sha256_line(line)
        try:
            last_tx_hash = send_tx(
                contract_v2.functions.appendEntryHash(case_id, global_index, entry_hash),
                nonce,
                label=f"line[{global_index}]"
            )
            nonce += 1  # increment nonce manually — no waiting!
        except Exception as e:
            print(f"  ⚠️ Failed line {global_index}: {e}")

    # Wait only for the LAST transaction
    if last_tx_hash:
        print(f"⏳ Waiting for last tx to confirm...")
        receipt = w3.eth.wait_for_transaction_receipt(last_tx_hash, timeout=60)
        print(f"✅ All lines confirmed at block {receipt.blockNumber}")

    # Submit Merkle root
    root, leaves, _ = build_merkle_tree(all_lines)
    nonce = w3.eth.get_transaction_count(ACCOUNT)

    try:
        if not contract_v1.functions.entryExists(case_id).call():
            tx = send_tx(
                contract_v1.functions.addLog(case_id, root, INVESTIGATOR_ID, len(all_lines)),
                nonce, label="V1/addLog"
            )
            nonce += 1
            w3.eth.wait_for_transaction_receipt(tx, timeout=60)
    except Exception as e:
        print(f"  V1 addLog: {e}")

    try:
        if not contract_v2.functions.entryExists(case_id).call():
            tx = send_tx(
                contract_v2.functions.addLog(case_id, root, INVESTIGATOR_ID, len(all_lines)),
                nonce, label="V2/addLog"
            )
            w3.eth.wait_for_transaction_receipt(tx, timeout=60)
    except Exception as e:
        print(f"  V2 addLog: {e}")

    # Save leaves
    with open(LEAVES_FILE, "w") as f:
        json.dump({
            "leaves": leaves,
            "entries": [e.strip() for e in all_lines],
            "root": root,
            "case_id": case_id
        }, f, indent=2)

    # Save offset
    state[key] = {
        "last_line_count": current_count,
        "last_file_size":  current_size,
        "last_run":        time.strftime("%Y-%m-%dT%H:%M:%S")
    }
    save_offset(state)
    print(f"✅ Batch complete! {len(new_lines)} lines submitted.")
    return True

if __name__ == "__main__":
    sample_file = os.path.join(BASE_DIR, "sample log", "sam3.log")
    submit_new_entries(sample_file, "CASE-2024-0078")
