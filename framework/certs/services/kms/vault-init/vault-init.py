import os, sys, time, json, base64
import requests

VAULT_ADDR   = os.environ.get("VAULT_ADDR", "http://vault:8200").rstrip("/")
STATE_DIR    = os.environ.get("STATE_DIR", "/state")
INIT_JSON_F  = os.path.join(STATE_DIR, "init.json")
ROOT_TOKEN_F = os.path.join(STATE_DIR, "root.token")
ROLE_ID_F    = os.path.join(STATE_DIR, "cert-materializer.role_id")
SECRET_ID_F  = os.path.join(STATE_DIR, "cert-materializer.secret_id")
VAULT_AUDIT_FILE = os.getenv("VAULT_AUDIT_FILE", "/vault/logs/audit.ndjson")

S = requests.Session()
S.headers.update({"Content-Type": "application/json"})

def log(msg): print(f"[vault-init] {msg}", flush=True)

def ok_codes(*codes): return set(codes or (200,204,400,409))

def req(method, path, token=None, body=None, ok=ok_codes()):
    url = f"{VAULT_ADDR}{path}"
    headers = {}
    if token:
        headers["X-Vault-Token"] = token
    r = S.request(method, url, headers=headers, json=body, timeout=10)
    if r.status_code not in ok:
        raise RuntimeError(f"{method} {path} -> {r.status_code} {r.text}")
    return r

def wait_http():
    log(f"VAULT_ADDR={VAULT_ADDR}")
    for _ in range(120):
        try:
            r = S.get(f"{VAULT_ADDR}/v1/sys/health", timeout=3)
            if r.status_code in (200, 429, 473, 501, 503):
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("Vault HTTP not reachable on /v1/sys/health")

def health_code():
    try:
        return S.get(f"{VAULT_ADDR}/v1/sys/health", timeout=5).status_code
    except Exception:
        return 0

def ensure_initialized():
    os.makedirs(STATE_DIR, exist_ok=True)
    code = health_code()
    log(f"Initial health: {code}")
    if code == 501:  # Not initialized
        log("Initializing Vault (awskms -> recovery shares)...")
        r = req("PUT", "/v1/sys/init", body={
            "recovery_shares": 1,
            "recovery_threshold": 1
        }, ok=ok_codes(200))
        open(INIT_JSON_F, "w", encoding="utf-8").write(r.text)
        # extract root_token (no jq)
        try:
            tok = r.json().get("root_token")
            if tok:
                open(ROOT_TOKEN_F, "w", encoding="utf-8").write(tok)
                log(f"Saved root token to {ROOT_TOKEN_F}")
            else:
                log("WARNING: init returned no root_token (check logs).")
        except Exception as e:
            log(f"WARNING: failed to parse init response: {e}")
    else:
        log("Vault already initialized.")

def wait_active():
    log("Waiting for Vault to become active (200)...")
    for _ in range(120):
        code = health_code()
        if code == 200:
            log("Vault is active (200).")
            return
        time.sleep(1)
    raise RuntimeError(f"Timed out waiting for active (last={code})")

def read_root_token():
    if os.path.isfile(ROOT_TOKEN_F) and os.path.getsize(ROOT_TOKEN_F) > 0:
        return open(ROOT_TOKEN_F,"r",encoding="utf-8").read().strip()
    if os.path.isfile(INIT_JSON_F):
        try:
            tok = json.load(open(INIT_JSON_F,"r",encoding="utf-8")).get("root_token")
            if tok:
                open(ROOT_TOKEN_F,"w",encoding="utf-8").write(tok)
                return tok
        except Exception as e:
            log(f"WARNING: parse {INIT_JSON_F} failed: {e}")
    raise RuntimeError(f"No root token found in {STATE_DIR}")

def ensure_kv_mount(token):
    mounts = req("GET", "/v1/sys/mounts", token).json()
    if "pqc-secrets/" in mounts:
        log("pqc-secrets KV v2 already enabled")
    else:
        log("enabling pqc-secrets KV v2...")
        req("POST", "/v1/sys/mounts/pqc-secrets", token, {
            "type": "kv",
            "options": {"version": "2"}
        })

def ensure_policy_and_approle(token):
    policy_hcl = (
        'path "pqc-secrets/data/ca/*" { capabilities = ["read"] }\n'
        'path "pqc-secrets/data/mqtt/*" { capabilities = ["read"] }\n'
        'path "pqc-secrets/data/wolfboot/*" { capabilities = ["read"] }\n'
        'path "pqc-secrets/metadata/ca/*" { capabilities = ["read", "list"] }\n'
        'path "pqc-secrets/metadata/mqtt/*" { capabilities = ["read", "list"] }\n'
        'path "pqc-secrets/metadata/wolfboot/*" { capabilities = ["read", "list"] }\n'
    )
    log("writing cert-materializer policy...")
    req("PUT", "/v1/sys/policies/acl/cert-materializer", token, {"policy": policy_hcl})

    auths = req("GET", "/v1/sys/auth", token).json()
    if "approle/" not in auths:
        log("enabling approle auth...")
        req("POST", "/v1/sys/auth/approle", token, {"type":"approle"})

    log("creating AppRole cert-materializer...")
    req("POST", "/v1/auth/approle/role/cert-materializer", token, {
        "policies": "cert-materializer",
        "token_ttl": "15m",
        "token_max_ttl": "1h",
        "secret_id_ttl": "24h",
        "secret_id_num_uses": 0
    })

    role_id = req("GET", "/v1/auth/approle/role/cert-materializer/role-id", token).json()["data"]["role_id"]
    secret_id = req("POST", "/v1/auth/approle/role/cert-materializer/secret-id", token).json()["data"]["secret_id"]

    with open(ROLE_ID_F, "w", encoding="utf-8") as stream:
        stream.write(role_id)
    with open(SECRET_ID_F, "w", encoding="utf-8") as stream:
        stream.write(secret_id)
    os.chmod(ROLE_ID_F, 0o600)
    os.chmod(SECRET_ID_F, 0o600)
    log(f"Wrote {ROLE_ID_F} and {SECRET_ID_F}")

def ensure_audit_file(token: str):
    url = f"{VAULT_ADDR}/v1/sys/audit/file"
    headers = {"X-Vault-Token": token}
    body = {
        "type": "file",
        "description": "primary audit device",
        "options": {
            "file_path": VAULT_AUDIT_FILE,
            "log_raw": "true",
        },
    }
    r = requests.put(url, headers=headers, json=body, timeout=5)
    # 204 created/enabled, 400/409 means it's already there (ok to ignore)
    print(f"Ensure Audit File Status Code {r}")
    if r.status_code not in (200, 204, 400, 409):
        raise RuntimeError(f"enable audit failed: {r.status_code} {r.text}")
    
    # Configure which client request headers Vault will record and HMAC
    headers = {"X-Vault-Token": token}
    cfg = {
        "x-request-id": False,           # plaintext
        "x-purpose": False,              # plaintext
        "x-original-client-ip": False,   # plaintext
    }

    # Apply idempotently (POST overwrites the setting if it already exists)
    for h, hmac_flag in cfg.items():
        pr = requests.post(
            f"{VAULT_ADDR}/v1/sys/config/auditing/request-headers/{h}",
            headers=headers,
            json={"hmac": bool(hmac_flag)},
            timeout=5,
        )
        # 204 No Content on success
        if pr.status_code not in (204, 200):
            raise RuntimeError(f"configure audit header {h} failed: {pr.status_code} {pr.text}")

def main():
    try:
        wait_http()
        ensure_initialized()
        wait_active()
        token = read_root_token()
        log("Using root token from state")
        ensure_audit_file(token)
        ensure_kv_mount(token)
        ensure_policy_and_approle(token)
        
        log("All done.")
    except Exception as e:
        log(f"ERROR: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
