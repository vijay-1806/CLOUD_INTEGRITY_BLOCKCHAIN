"""
deploy_v2.py  —  Deploy LogIntegrityV2 using web3.py + compiled Hardhat artifact
Run: python deploy_v2.py
"""
import json
import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from web3 import Web3

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
RPC_URL     = "http://127.0.0.1:8545"
PRIVATE_KEY = "0x9c7bf0754e9b13d38d2b71a69da799f76545991b97918ae1e000f400437d51b2"
ACCOUNT     = "0x8b629ce3BB085B061D95C7f0d14d2BF63ECbA758"
CHAIN_ID    = 12345

ARTIFACT    = os.path.join(BASE_DIR, "artifacts", "contracts", "LogIntegrityV2.sol", "LogIntegrityV2.json")
ABI_OUT     = os.path.join(BASE_DIR, "LogIntegrityV2_abi.json")

w3 = Web3(Web3.HTTPProvider(RPC_URL))
if not w3.is_connected():
    print("❌ Cannot connect to", RPC_URL); sys.exit(1)
print("✅ Connected, block:", w3.eth.block_number)

with open(ARTIFACT) as f:
    artifact = json.load(f)

abi      = artifact["abi"]
bytecode = artifact["bytecode"]

Contract = w3.eth.contract(abi=abi, bytecode=bytecode)

nonce = w3.eth.get_transaction_count(ACCOUNT)
tx = Contract.constructor().build_transaction({
    "chainId":  CHAIN_ID,
    "gas":      3000000,
    "gasPrice": w3.to_wei("1", "gwei"),
    "nonce":    nonce,
})

signed  = w3.eth.account.sign_transaction(tx, PRIVATE_KEY)
tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
print("Tx sent:", tx_hash.hex(), "— waiting for receipt…")

receipt = w3.eth.wait_for_transaction_receipt(tx_hash)
addr    = receipt["contractAddress"]
print(f"\n✅ LogIntegrityV2 deployed at: {addr}")
print(f"   Block: {receipt.blockNumber}  Gas used: {receipt.gasUsed}")

# Save ABI
with open(ABI_OUT, "w") as f:
    json.dump(abi, f, indent=2)
print(f"   ABI  → {ABI_OUT}")

print(f"""
📋 Update CONTRACT_ADDRESS_V2 in these files:
   hash_and_submit.py  → CONTRACT_ADDRESS_V2 = "{addr}"
   watcher.py          → CONTRACT_ADDRESS_V2 = "{addr}"
   app.py              → CONTRACT_ADDRESS_V2 = "{addr}"
""")
