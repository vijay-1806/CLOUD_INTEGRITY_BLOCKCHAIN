import os
import sys
import time
import threading
import json

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from bson.objectid import ObjectId
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from hash_and_submit import submit_new_entries, sha256_line, CONTRACT_ADDRESS_V2, ABI_V2_PATH, RPC_URL
from web3 import Web3
from models import Database

class MultiUserFileHandler(FileSystemEventHandler):
    def __init__(self, watcher, log_id, log_path, case_id):
        self.watcher = watcher
        self.log_id = str(log_id)
        self.log_path = log_path
        self.case_id = case_id
        
    def on_modified(self, event):
        if event.src_path == self.log_path:
            print(f"\n⚡ [AWS CloudTrail S3 Event] Ingestion trigger on S3 stream for Trail: {self.case_id} [Source: {self.log_path}]")
            threading.Thread(target=self.watcher.process_log, args=(self.log_id, self.log_path, self.case_id), daemon=True).start()

class MultiUserWatcher:
    def __init__(self):
        self.db = Database()
        self.observers = {} # Map of log_id -> Observer
        self._locks = {} # lock per log_id
        self._global_lock = threading.Lock()
        self._pending_updates = {} # track skipped runs
        
        self.w3 = Web3(Web3.HTTPProvider(RPC_URL))
        self.contract_v2 = None
        if self.w3.is_connected() and os.path.exists(ABI_V2_PATH):
            with open(ABI_V2_PATH) as f:
                self.contract_v2 = self.w3.eth.contract(address=CONTRACT_ADDRESS_V2, abi=json.load(f))

    def _get_lock(self, log_id):
        with self._global_lock:
            if log_id not in self._locks:
                self._locks[log_id] = threading.Lock()
            return self._locks[log_id]

    def process_log(self, log_id, log_path, case_id):
        lock = self._get_lock(log_id)
        
        with self._global_lock:
            if lock.locked():
                self._pending_updates[log_id] = True
                return
                
        lock.acquire()
        try:
            while True:
                with self._global_lock:
                    self._pending_updates[log_id] = False
                    
                # 1. Submit to blockchain using existing logic
                try:
                    submit_new_entries(log_path, case_id)
                except Exception as e:
                    print(f"⚠️ [AWS CloudTrail Error] Blockchain anchoring failed for stream {case_id}: {e}")
                    
                # Allow some time for transactions to confirm in the blockchain mempool
                time.sleep(2)
                    
                # 2. Re-verify the count and update DB
                if not self.contract_v2:
                    return
                    
                if os.path.exists(log_path):
                    with open(log_path, "r") as f:
                        file_lines = [line for line in f.readlines() if line.strip()]
                else:
                    file_lines = []
                    
                file_count = len(file_lines)
                
                # Wait until chain_count catches up to file_count (up to 30 seconds)
                chain_count = 0
                for _ in range(15):
                    try:
                        chain_count = self.contract_v2.functions.getEntryCount(case_id).call()
                        if chain_count >= file_count:
                            break
                    except Exception as e:
                        chain_count = 0
                    time.sleep(2)
                    
                log_doc = self.db.logs.find_one({"case_id": case_id})
                user_id = log_doc.get("user_id") if log_doc else None
                prev_tampered = set(log_doc.get("tampered_lines", [])) if log_doc else set()
                
                max_idx = max(file_count, chain_count)
                verified_count = 0
                current_tampered = []
                
                for i in range(max_idx):
                    has_file = i < file_count
                    has_chain = i < chain_count
                    if has_file and has_chain:
                        fhash = sha256_line(file_lines[i])
                        chash = self.contract_v2.functions.getEntryHash(case_id, i).call()
                        if chash:
                            if fhash == chash:
                                verified_count += 1
                            else:
                                current_tampered.append(i)
                                
                curr_t_set = set(current_tampered)
                new_tampers = curr_t_set - prev_tampered
                resolved_tampers = prev_tampered - curr_t_set
                
                for idx in new_tampers:
                    self.db.log_activity(user_id, "TAMPER_DETECTED", f"AWS CloudTrail Event Record #{idx+1} cryptographically altered / hash mismatch", case_id)
                    print(f"🚨 [AWS GuardDuty Alert] CLOUDTRAIL INTEGRITY COMPROMISED: Event Record #{idx+1} hash mismatch in Trail: {case_id}!")
                    
                for idx in resolved_tampers:
                    self.db.log_activity(user_id, "TAMPER_CORRECTED", f"AWS CloudTrail Event Record #{idx+1} cryptographically verified / restored", case_id)
                    print(f"✅ [AWS GuardDuty Auto-Heal] CLOUDTRAIL EVENT RESTORED: Event Record #{idx+1} verified in Trail: {case_id}")
                            
                # Update database
                self.db.update_log_stats(log_id, file_count, verified_count, current_tampered)
                print(f"📊 [AWS CloudWatch Metrics] Trail {case_id}: {verified_count}/{file_count} S3 CloudTrail events cryptographically verified on-chain")
                
                # Check if we need to loop again
                with self._global_lock:
                    if not self._pending_updates.get(log_id):
                        break
        except Exception as e:
            print(f"Error processing log {log_id}: {e}")
        finally:
            lock.release()

    def sync_active_logs(self):
        try:
            active_logs = self.db.get_active_logs()
            current_active = {str(log['_id']): log for log in active_logs}
            
            with self._global_lock:
                # Stop obsolete observers
                for log_id in list(self.observers.keys()):
                    if log_id not in current_active:
                        print(f"🛑 [AWS SQS Stream] Detaching listener from S3 stream ID: {log_id}")
                        self.observers[log_id].stop()
                        self.observers[log_id].join()
                        del self.observers[log_id]
                        
                # Start new observers
                for log_id, log_data in current_active.items():
                    if log_id not in self.observers:
                        log_path = log_data['log_path']
                        case_id = log_data['case_id']
                        
                        target_dir = os.path.dirname(log_path)
                        if os.path.exists(target_dir):
                            print(f"👀 [AWS Lambda Sync Active] Monitoring S3 Path Entry & CloudTrail Stream: {case_id} [Target: {log_path}]")
                            observer = Observer()
                            handler = MultiUserFileHandler(self, log_id, log_path, case_id)
                            observer.schedule(handler, path=target_dir, recursive=False)
                            observer.start()
                            self.observers[log_id] = observer
                            
                            # Do an initial process check
                            threading.Thread(target=self.process_log, args=(log_id, log_path, case_id), daemon=True).start()
                        else:
                            print(f"⚠️ [AWS S3 Mount Warning] S3 sync mount directory {target_dir} not found for stream {log_id}")
        except Exception as e:
            print(f"[AWS Sentinel Daemon Error] in sync_active_logs: {e}")

    def run(self):
        print("🚀 [AWS CloudTrail Sentinel] Starting Decentralized S3 & CloudTrail Ledger Sync Daemon...")
        while True:
            self.sync_active_logs()
            time.sleep(10)

if __name__ == '__main__':
    watcher = MultiUserWatcher()
    watcher.run()
