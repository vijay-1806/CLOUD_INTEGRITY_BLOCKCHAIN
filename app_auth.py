import os
import sys
import json
import hashlib
import threading
import time
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, abort
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from web3 import Web3
from models import Database
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-secret-key')

# ── Database & Login ──────────────────────────────────────────────
db = Database()
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_data):
        self.id = str(user_data['_id'])
        self.username = user_data['username']
        self.role = user_data.get('role', 'user')
        self._is_active = user_data.get('is_active', True)

    @property
    def is_active(self):
        return self._is_active

@login_manager.user_loader
def load_user(user_id):
    user_data = db.get_user_by_id(user_id)
    if not user_data or not user_data.get('is_active', True):
        return None
    return User(user_data)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            abort(403)
        return f(*args, **kwargs)
    return decorated_function

# ── Blockchain Setup ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RPC_URL = os.environ.get("RPC_URL", "http://127.0.0.1:8545")
NODE2_RPC_URL = os.environ.get("NODE2_RPC_URL", "")
CONTRACT_ADDRESS_V2 = os.environ.get("CONTRACT_ADDRESS_V2", "0xC339e3B383333CAB68EbA145dEf8904864151c2E")
ABI_V2_PATH = os.path.join(BASE_DIR, "LogIntegrityV2_abi.json")

w3 = Web3(Web3.HTTPProvider(RPC_URL))
w3_node2 = Web3(Web3.HTTPProvider(NODE2_RPC_URL)) if NODE2_RPC_URL else None
contract_v2 = None
if w3.is_connected() and os.path.exists(ABI_V2_PATH):
    with open(ABI_V2_PATH) as f:
        contract_v2 = w3.eth.contract(address=CONTRACT_ADDRESS_V2, abi=json.load(f))

def sha256_line(line_str):
    return hashlib.sha256(line_str.strip().encode("utf-8")).hexdigest()

# ── Auth Routes ───────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = db.get_user_by_username(username)
        if user_data and db.verify_password(user_data['password'], password):
            if not user_data.get('is_active', True):
                flash('Account is disabled. Please contact admin.', 'danger')
                return redirect(url_for('login'))
                
            user = User(user_data)
            login_user(user)
            db.update_login_time(user.id)
            db.log_activity(user.id, "LOGIN", f"IAM Auditor authenticated: {user.username}")
            return redirect(url_for('dashboard'))
            
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        email = request.form.get('email', '')
        
        user_id, error = db.create_user(username, password, email)
        if error:
            flash(error, 'danger')
        else:
            db.log_activity(user_id, "REGISTER", f"New IAM Auditor registered: {username}")
            flash('Registration successful! Please login.', 'success')
            return redirect(url_for('login'))
            
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    db.log_activity(current_user.id, "LOGOUT", "User logged out")
    logout_user()
    return redirect(url_for('login'))

# ── User Routes ───────────────────────────────────────────────────

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    logs = db.get_logs_for_user(current_user.id)
    return render_template('dashboard.html', logs=logs)

@app.route('/add_log', methods=['GET', 'POST'])
@login_required
def add_log():
    if request.method == 'POST':
        case_id = request.form.get('case_id')
        log_path = request.form.get('log_path')
        description = request.form.get('description', '')
        
        # Verify local sync path if not purely virtual S3 URI
        if not log_path.startswith("s3://") and not os.path.exists(log_path):
            flash('Notice: S3 CloudTrail stream sync cache path not currently found on local node mount', 'warning')
            
        log_id, _ = db.add_log_source(current_user.id, log_path, case_id, description)
        db.log_activity(current_user.id, "PROVISION_STREAM", f"[AWS S3 Ingestion] Attached CloudTrail Stream: {case_id} ({log_path})")
        flash('AWS CloudTrail Stream provisioned and connected to Ledger!', 'success')
        return redirect(url_for('dashboard'))
        
    return render_template('add_log.html')

@app.route('/toggle_log/<log_id>')
@login_required
def toggle_log(log_id):
    new_status = db.toggle_log_status(log_id, current_user.id)
    if new_status is not None:
        status_label = "ACTIVE" if new_status else "SUSPENDED"
        db.log_activity(current_user.id, "TOGGLE_STREAM", f"[AWS S3 Ingestion] CloudTrail Stream {log_id} ingestion state changed to {status_label}")
    return redirect(url_for('dashboard'))

@app.route('/delete_log/<log_id>')
@login_required
def delete_log(log_id):
    if db.delete_log(log_id, current_user.id):
        db.log_activity(current_user.id, "DEPROVISION_STREAM", f"[AWS S3 Ingestion] Deprovisioned CloudTrail stream {log_id}")
    return redirect(url_for('dashboard'))

# ── Admin Routes ──────────────────────────────────────────────────

@app.route('/admin')
@admin_required
def admin():
    users = db.get_all_users()
    all_logs = db.get_all_logs()
    recent_activities = db.get_recent_activities(100)
    return render_template('admin.html', users=users, logs=all_logs, activities=recent_activities)

@app.route('/admin/toggle_user/<user_id>')
@admin_required
def toggle_user(user_id):
    if user_id != current_user.id:  # Prevent locking oneself out
        new_status = db.toggle_user_status(user_id)
        db.log_activity(current_user.id, "ADMIN_TOGGLE_USER", f"User {user_id} active status: {new_status}")
    return redirect(url_for('admin'))

@app.route('/admin/delete_user/<user_id>')
@admin_required
def delete_user(user_id):
    if user_id != current_user.id:
        db.delete_user(user_id)
        db.log_activity(current_user.id, "ADMIN_DELETE_USER", f"Deleted user {user_id}")
    return redirect(url_for('admin'))

@app.route('/admin/create_user', methods=['POST'])
@admin_required
def create_user():
    username = request.form.get('username')
    password = request.form.get('password')
    role = request.form.get('role', 'user')
    email = request.form.get('email', '')
    
    user_id, error = db.create_user(username, password, email, role=role)
    if error:
        flash(f'Error creating user: {error}', 'danger')
    else:
        db.log_activity(current_user.id, "ADMIN_CREATE_USER", f"Created {role} user: {username}")
        flash(f'User {username} created successfully', 'success')
    return redirect(url_for('admin'))

# ── AJAX API Routes ──────────────────────────────────────────────

@app.route('/api/blockchain_status')
@admin_required
def api_blockchain_status():
    try:
        node1_connected = w3.is_connected()
        node1_block = w3.eth.block_number if node1_connected else 0
        node1_peers = w3.net.peer_count if node1_connected else 0
        node1_mining = getattr(w3.eth, 'mining', False) if node1_connected else False
    except Exception:
        node1_connected, node1_block, node1_peers, node1_mining = False, 0, 0, False

    try:
        node2_connected = w3_node2.is_connected() if w3_node2 else False
        node2_block = w3_node2.eth.block_number if node2_connected else 0
    except Exception:
        node2_connected, node2_block = False, 0

    return jsonify({
        "node1": {
            "connected": node1_connected,
            "block": node1_block,
            "peers": node1_peers,
            "mining": node1_mining,
            "ip": RPC_URL
        },
        "node2": {
            "connected": node2_connected,
            "block": node2_block,
            "ip": NODE2_RPC_URL or "Single-Node Mode (PC1)"
        },
        "active": node1_connected and (node2_connected if NODE2_RPC_URL else True)
    })

@app.route('/api/stats')
@login_required
def api_stats():
    logs = db.get_logs_for_user(current_user.id)
    total_logs = len(logs)
    active_logs = sum(1 for log in logs if log.get('is_active'))
    total_entries = sum(log.get('total_entries', 0) for log in logs)
    verified_entries = sum(log.get('verified_entries', 0) for log in logs)
    
    return jsonify({
        "total_logs": total_logs,
        "active_logs": active_logs,
        "total_entries": total_entries,
        "verified_entries": verified_entries,
        "log_sources": [{"id": str(log['_id']), "verified": log.get('verified_entries', 0), "total": log.get('total_entries', 0)} for log in logs]
    })

@app.route('/api/admin/user_cases/<user_id>')
@login_required
@admin_required
def api_admin_user_cases(user_id):
    logs = db.get_logs_for_user(user_id)
    return jsonify([{"case_id": log.get("case_id"), "log_path": log.get("log_path"), 
                     "verified_entries": log.get("verified_entries", 0), 
                     "total_entries": log.get("total_entries", 0)} for log in logs])

@app.route('/api/admin/tamper_logs/<case_id>')
@login_required
@admin_required
def api_admin_tamper_logs(case_id):
    activities = db.activities.find({
        "case_id": case_id, 
        "action": {"$in": ["TAMPER_DETECTED", "TAMPER_CORRECTED"]}
    }).sort("timestamp", -1)
    
    rows = []
    for act in activities:
        rows.append({
            "timestamp": act.get("timestamp").strftime('%Y-%m-%d %H:%M:%S'),
            "action": act.get("action"),
            "details": act.get("details")
        })
    return jsonify({"rows": rows})

@app.route('/api/entries/<case_id>')
@login_required
def api_entries(case_id):
    # Verify the current user owns a log with this case_id (or is admin)
    user_logs = db.get_logs_for_user(current_user.id)
    log_doc = next((l for l in user_logs if l.get('case_id') == case_id), None)
    
    if not log_doc and current_user.role != 'admin':
        return jsonify({"error": "Unauthorized"}), 403
        
    log_path = log_doc['log_path'] if log_doc else None
    
    results = {
        "status": "Scanning",
        "all_ok": True,
        "file_count": 0,
        "chain_count": 0,
        "rows": []
    }
    
    if not contract_v2:
        results["status"] = "V2 Contract Offline"
        results["all_ok"] = False
        return jsonify(results)
        
    try:
        if log_path and os.path.exists(log_path):
            with open(log_path, "r") as f:
                file_lines = [line for line in f.readlines() if line.strip()]
        else:
            file_lines = []
            
        file_count = len(file_lines)
        try:
            chain_count = contract_v2.functions.getEntryCount(case_id).call()
        except:
            chain_count = 0
            
        results["file_count"] = file_count
        results["chain_count"] = chain_count
        max_idx = max(file_count, chain_count)
        
        all_ok = True
        rows = []
        
        for i in range(max_idx):
            has_file = i < file_count
            has_chain = i < chain_count
            
            if has_file and has_chain:
                fhash = sha256_line(file_lines[i])
                chash = contract_v2.functions.getEntryHash(case_id, i).call()
                if fhash == chash:
                    rows.append({
                        "index": i + 1, "status": "✅ VERIFIED",
                        "content": file_lines[i].strip()[:55],
                        "file_hash": fhash[:20] + "...",
                        "chain_hash": chash[:20] + "...",
                        "row_class": "", "tag_class": "tag-ok"
                    })
                elif not chash:
                    all_ok = False
                    rows.append({
                        "index": i + 1, "status": "⚠️ S3 SYNC LAG",
                        "content": file_lines[i].strip()[:55],
                        "file_hash": fhash[:20] + "...",
                        "chain_hash": "...",
                        "row_class": "row-warning", "tag_class": "tag-warning"
                    })
                else:
                    all_ok = False
                    rows.append({
                        "index": i + 1, "status": "🚨 TAMPER DETECTED",
                        "content": file_lines[i].strip()[:55],
                        "file_hash": fhash[:20] + "...",
                        "chain_hash": chash[:20] + "...",
                        "row_class": "row-tampered", "tag_class": "tag-tampered"
                    })
            elif has_file and not has_chain:
                all_ok = False
                fhash = sha256_line(file_lines[i])
                rows.append({
                    "index": i + 1, "status": "⏳ PENDING ON-CHAIN NOTARIZATION",
                    "content": file_lines[i].strip()[:55],
                    "file_hash": fhash[:20] + "...", "chain_hash": "...",
                    "row_class": "row-pending", "tag_class": "tag-pending"
                })
            elif has_chain and not has_file:
                all_ok = False
                chash = contract_v2.functions.getEntryHash(case_id, i).call()
                rows.append({
                    "index": i + 1, "status": "❌ S3 OBJECT DELETED",
                    "content": "(missing from S3 stream)",
                    "file_hash": "(none)",
                    "chain_hash": chash[:20] + "...",
                    "row_class": "row-deleted", "tag_class": "tag-deleted"
                })
                
        results["all_ok"] = all_ok
        results["rows"] = rows
        results["status"] = "All CloudTrail Events Verified" if all_ok else "Integrity Issues Detected"
        
    except Exception as e:
        results["status"] = f"Error: {str(e)}"
        results["all_ok"] = False
        

# ── Interactive Action & Tamper Testbed Routes ─────────────────────

DEMO_CASE_ID = "AUDIT_LIVE_LOG"
AUDIT_LOG_PATH = os.path.join(BASE_DIR, "audit_live.log")
AUDIT_BACKUP_PATH = os.path.join(BASE_DIR, "audit_live.backup.log")

# Auto-Anchor Daemon Thread
def auto_anchor_worker():
    """Background worker that continuously anchors new log lines to Ethereum LogIntegrityV2."""
    from hash_and_submit import send_tx, ACCOUNT
    while True:
        try:
            if contract_v2 and w3.is_connected() and os.path.exists(AUDIT_LOG_PATH):
                with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
                    lines = [line.rstrip('\r\n') for line in f.readlines() if line.strip()]

                try:
                    chain_count = contract_v2.functions.getEntryCount(DEMO_CASE_ID).call()
                except Exception:
                    chain_count = 0

                if len(lines) > chain_count:
                    new_lines = lines[chain_count:]
                    nonce = w3.eth.get_transaction_count(ACCOUNT)
                    last_tx = None
                    for i, line in enumerate(new_lines):
                        line_idx = chain_count + i
                        line_hash = sha256_line(line)
                        last_tx = send_tx(
                            contract_v2.functions.appendEntryHash(DEMO_CASE_ID, line_idx, line_hash),
                            nonce,
                            label=f"auto[{line_idx}]"
                        )
                        nonce += 1
                        print(f" [AUTO-ANCHOR] Submitted line #{line_idx + 1} hash={line_hash[:16]}... tx={last_tx.hex()[:18]}...")
                    if last_tx:
                        receipt = w3.eth.wait_for_transaction_receipt(last_tx, timeout=12)
                        print(f" [AUTO-ANCHOR] Sealed block #{receipt.blockNumber} for {len(new_lines)} lines")
        except Exception as e:
            # print error only if not network wait
            pass
        time.sleep(1.5)

threading.Thread(target=auto_anchor_worker, daemon=True).start()

@app.route('/demo')
def demo_page():
    return render_template('demo.html', log_file_name="audit_live.log")

@app.route('/api/demo/state')
def api_demo_state():
    logs = []
    lines = []
    if os.path.exists(AUDIT_LOG_PATH):
        with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
            lines = [line.rstrip('\r\n') for line in f.readlines() if line.strip()]

    chain_count = 0
    if contract_v2:
        try:
            chain_count = contract_v2.functions.getEntryCount(DEMO_CASE_ID).call()
        except:
            chain_count = 0

    block_num = 0
    node1_peers = 0
    if w3.is_connected():
        try:
            block_num = w3.eth.block_number
            node1_peers = int(w3.net.peer_count)
        except:
            pass

    node2_connected = False
    node2_peers = 0
    if NODE2_RPC_URL:
        try:
            w2 = Web3(Web3.HTTPProvider(NODE2_RPC_URL))
            if w2.is_connected():
                node2_connected = True
                node2_peers = int(w2.net.peer_count)
        except:
            pass

    for i, line in enumerate(lines):
        local_hash = sha256_line(line)
        is_anchored = (i < chain_count)
        chain_hash = ""
        is_tampered = False

        if is_anchored and contract_v2:
            try:
                chain_hash = contract_v2.functions.getEntryHash(DEMO_CASE_ID, i).call()
                is_tampered = (local_hash != chain_hash)
            except:
                pass

        logs.append({
            "index": i,
            "content": line,
            "local_hash": local_hash,
            "chain_hash": chain_hash,
            "is_anchored": is_anchored,
            "is_tampered": is_tampered
        })

    return jsonify({
        "case_id": DEMO_CASE_ID,
        "logs": logs,
        "block_number": block_num,
        "contract_address": CONTRACT_ADDRESS_V2,
        "chain_count": chain_count,
        "file_name": "audit_live.log",
        "file_path": AUDIT_LOG_PATH,
        "node1_peers": node1_peers,
        "node2_connected": node2_connected,
        "node2_peers": node2_peers
    })

# ── AWS CloudWatch Log Receiver Endpoint ───────────────────────────
@app.route('/logs', methods=['GET', 'POST'])
def aws_cloudwatch_receiver():
    """
    Receives forwarded logs from AWS Exporter Lambda via ngrok or direct HTTP.
    Extracts events, appends them to audit_live.log, where auto_anchor_worker
    immediately notarizes their SHA-256 hashes to the Ethereum blockchain.
    """
    if request.method == 'GET':
        return jsonify({
            "status": "online",
            "service": "AWS CloudWatch Blockchain Integrity Gateway",
            "endpoint": "/logs",
            "method": "POST",
            "message": "Send JSON logs via POST from your Exporter Lambda to anchor them into the blockchain.",
            "monitored_file": "audit_live.log",
            "dashboard_url": "/demo"
        }), 200

    payload = request.get_json(silent=True) or {}
    raw_text = request.get_data(as_text=True)

    extracted_messages = []

    # Format 1: Decoded CloudWatch subscription filter payload
    if isinstance(payload, dict):
        log_group = payload.get('logGroup', 'AWS_CLOUDWATCH')
        if 'logEvents' in payload and isinstance(payload['logEvents'], list):
            for event in payload['logEvents']:
                msg = event.get('message', '').strip() if isinstance(event, dict) else str(event).strip()
                if msg:
                    extracted_messages.append(f"[{log_group}] {msg}")
        elif 'message' in payload:
            extracted_messages.append(f"[{log_group}] {str(payload['message']).strip()}")
        elif 'log' in payload:
            extracted_messages.append(f"[{log_group}] {str(payload['log']).strip()}")
        elif 'event' in payload:
            extracted_messages.append(f"[{log_group}] {str(payload['event']).strip()}")

    # Format 2: JSON array of events
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                msg = item.get('message') or item.get('log') or json.dumps(item)
                extracted_messages.append(f"[AWS_EVENT] {msg.strip()}")
            else:
                extracted_messages.append(f"[AWS_EVENT] {str(item).strip()}")

    # Format 3: Raw text fallback
    if not extracted_messages and raw_text.strip():
        for line in raw_text.splitlines():
            line_str = line.strip()
            if line_str:
                extracted_messages.append(f"[AWS_RAW] {line_str}")

    if not extracted_messages:
        return jsonify({"status": "error", "message": "No log events found in payload"}), 400

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    written_lines = []

    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f_log, \
         open(AUDIT_BACKUP_PATH, "a", encoding="utf-8") as f_bak:
        for msg in extracted_messages:
            formatted_line = f"[{timestamp}] {msg}"
            f_log.write(formatted_line + "\n")
            f_bak.write(formatted_line + "\n")
            written_lines.append(formatted_line)
            print(f" [AWS-INGEST] Appended from CloudWatch: {formatted_line[:75]}...")

    return jsonify({
        "status": "success",
        "events_received": len(written_lines),
        "target_file": "audit_live.log",
        "blockchain_auto_anchoring": "ACTIVE",
        "sample_event": written_lines[0] if written_lines else None
    }), 200

@app.route('/api/demo/action', methods=['POST'])
def api_demo_action():
    data = request.get_json() or {}
    action_text = data.get('action', '').strip()
    if not action_text:
        return jsonify({"success": False, "error": "Empty action"}), 400

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_line = f"[{timestamp}] {action_text}"

    with open(AUDIT_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(formatted_line + "\n")

    with open(AUDIT_BACKUP_PATH, "a", encoding="utf-8") as f:
        f.write(formatted_line + "\n")

    return jsonify({
        "success": True,
        "line": formatted_line,
        "hash": sha256_line(formatted_line)
    })

@app.route('/api/demo/anchor', methods=['POST'])
def api_demo_anchor():
    if not contract_v2 or not w3.is_connected():
        return jsonify({"success": False, "error": "Blockchain or Contract V2 offline"}), 500

    if not os.path.exists(AUDIT_LOG_PATH):
        return jsonify({"success": False, "error": "No demo logs recorded yet"}), 400

    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        lines = [line.rstrip('\r\n') for line in f.readlines() if line.strip()]

    try:
        current_chain_count = contract_v2.functions.getEntryCount(DEMO_CASE_ID).call()
    except:
        current_chain_count = 0

    new_lines = lines[current_chain_count:]
    if not new_lines:
        return jsonify({
            "success": True,
            "submitted_count": 0,
            "message": "All current entries are already anchored on-chain."
        })

    from hash_and_submit import send_tx, ACCOUNT
    nonce = w3.eth.get_transaction_count(ACCOUNT)
    last_tx_hash = None

    for i, line in enumerate(new_lines):
        line_idx = current_chain_count + i
        line_hash = sha256_line(line)
        tx_hash = send_tx(
            contract_v2.functions.appendEntryHash(DEMO_CASE_ID, line_idx, line_hash),
            nonce,
            label=f"demo[{line_idx}]"
        )
        nonce += 1
        last_tx_hash = tx_hash

    receipt = w3.eth.wait_for_transaction_receipt(last_tx_hash, timeout=15)
    return jsonify({
        "success": True,
        "submitted_count": len(new_lines),
        "block_number": receipt.blockNumber,
        "tx_hash": last_tx_hash.hex()
    })

@app.route('/api/demo/tamper', methods=['POST'])
def api_demo_tamper():
    data = request.get_json() or {}
    idx = data.get('index')
    new_content = data.get('content')

    if idx is None or not new_content or not os.path.exists(AUDIT_LOG_PATH):
        return jsonify({"success": False, "error": "Invalid request"}), 400

    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        lines = [line.rstrip('\r\n') for line in f.readlines() if line.strip()]

    if idx < 0 or idx >= len(lines):
        return jsonify({"success": False, "error": "Index out of range"}), 400

    lines[idx] = new_content
    with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    return jsonify({"success": True, "tampered_index": idx})

@app.route('/api/demo/delete', methods=['POST'])
def api_demo_delete():
    data = request.get_json() or {}
    idx = data.get('index')

    if idx is None or not os.path.exists(AUDIT_LOG_PATH):
        return jsonify({"success": False, "error": "Invalid request"}), 400

    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        lines = [line.rstrip('\r\n') for line in f.readlines() if line.strip()]

    if idx < 0 or idx >= len(lines):
        return jsonify({"success": False, "error": "Index out of range"}), 400

    del lines[idx]
    with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")

    return jsonify({"success": True, "deleted_index": idx})

@app.route('/api/demo/restore', methods=['POST'])
def api_demo_restore():
    if os.path.exists(AUDIT_BACKUP_PATH):
        with open(AUDIT_BACKUP_PATH, "r", encoding="utf-8") as src:
            content = src.read()
        with open(AUDIT_LOG_PATH, "w", encoding="utf-8") as dst:
            dst.write(content)
        return jsonify({"success": True, "message": "Restored from backup"})
    return jsonify({"success": False, "error": "Backup file not found"}), 404

@app.route('/api/demo/verify')
def api_demo_verify():
    if not os.path.exists(AUDIT_LOG_PATH):
        return jsonify({"all_ok": True, "rows": []})

    with open(AUDIT_LOG_PATH, "r", encoding="utf-8") as f:
        lines = [line.rstrip('\r\n') for line in f.readlines() if line.strip()]

    chain_count = 0
    if contract_v2:
        try:
            chain_count = contract_v2.functions.getEntryCount(DEMO_CASE_ID).call()
        except:
            chain_count = 0

    all_ok = True
    rows = []
    for i, line in enumerate(lines):
        local_hash = sha256_line(line)
        chain_hash = ""
        status = "PENDING_NOTARIZATION"
        if i < chain_count and contract_v2:
            try:
                chain_hash = contract_v2.functions.getEntryHash(DEMO_CASE_ID, i).call()
                if local_hash == chain_hash:
                    status = "VERIFIED"
                else:
                    status = "TAMPERED"
                    all_ok = False
            except:
                pass
        rows.append({
            "index": i + 1,
            "status": status,
            "local_hash": local_hash,
            "chain_hash": chain_hash
        })

    return jsonify({"all_ok": all_ok, "rows": rows})

if __name__ == '__main__':
    print("\n" + "="*70)
    print(" ☁️  AWS CLOUDTRAIL / S3 BLOCKCHAIN INTEGRITY GATEWAY")
    print(" [AWS Lambda Sync Active] API Service listening on http://0.0.0.0:5000")
    print("="*70 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=True)
