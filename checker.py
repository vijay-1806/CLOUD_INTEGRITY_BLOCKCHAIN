import os
import sys
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from web3 import Web3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
CONTRACT_ADDRESS = os.environ.get("CONTRACT_ADDRESS_V2", "0xC339e3B383333CAB68EbA145dEf8904864151c2E")
ABI_PATH = os.path.join(BASE_DIR, "LogIntegrityV2_abi.json")
CASE_ID  = "CASE-2024-0078"

def check_node():
    w3 = Web3(Web3.HTTPProvider(RPC_URL))
    if not w3.is_connected():
        print(f"❌ Could not connect to {RPC_URL}")
        return

    with open(ABI_PATH) as f:
        abi = json.load(f)
    
    contract = w3.eth.contract(address=CONTRACT_ADDRESS, abi=abi)
    
    print(f"\n--- NODE SYNC STATUS ---")
    print(f"Node URL:      {RPC_URL}")
    print(f"Block Number:  {w3.eth.block_number}")
    print(f"Peer Count:    {w3.net.peer_count}")
    
    # Query the blockchain for the total log entries for your case
    count = contract.functions.getEntryCount(CASE_ID).call()
    print(f"On-Chain Logs: {count} entries (Case: {CASE_ID})")
    
    if count > 0:
        print("✅ SUCCESS: Data is present on this node.")
    else:
        print("⚠️  WARNING: No logs found yet on this node.")
    print("------------------------\n")

if __name__ == "__main__":
    check_node()
