#!/bin/sh
set -eu

CERT_DAYS="${CERT_DAYS:-365}"
ROOT_DAYS="${ROOT_DAYS:-3650}"
INTERMEDIATE_DAYS="${INTERMEDIATE_DAYS:-1825}"
RENEW_BEFORE_DAYS="${RENEW_BEFORE_DAYS:-30}"
MLDSA_RESET_PKI="${MLDSA_RESET_PKI:-0}"
PRIVATE_DIR="${PRIVATE_DIR:-/private}"
BROKER_DIR="${BROKER_DIR:-/broker}"
CLIENT_DIR="${CLIENT_DIR:-/client}"

if ! openssl list -public-key-algorithms 2>/dev/null | grep -Eqi 'ML-DSA-65|MLDSA65'; then
    echo "OpenSSL runtime does not provide ML-DSA-65" >&2
    openssl version >&2 || true
    exit 20
fi

umask 077
mkdir -p "$PRIVATE_DIR" "$BROKER_DIR" "$CLIENT_DIR"

ROOT_KEY="$PRIVATE_DIR/root.key"
ROOT_CERT="$PRIVATE_DIR/root-ca.crt"
INTERMEDIATE_KEY="$PRIVATE_DIR/intermediate.key"
INTERMEDIATE_CERT="$PRIVATE_DIR/intermediate-ca.crt"

if [ "$MLDSA_RESET_PKI" = "1" ]; then
    echo "[mldsa65] Explicit reset requested; removing only the ML-DSA-65 signing tuple and leaves."
    rm -f "$ROOT_KEY" "$ROOT_CERT" "$INTERMEDIATE_KEY" "$INTERMEDIATE_CERT" \
        "$PRIVATE_DIR/root-ca.srl" "$PRIVATE_DIR/intermediate-ca.srl"
    rm -f "$BROKER_DIR/tls.crt" "$BROKER_DIR/tls.key" "$BROKER_DIR/tls-chain.crt"
    rm -f "$CLIENT_DIR/client.crt" "$CLIENT_DIR/client.key" "$CLIENT_DIR/client-chain.crt"
fi

present=0
for member in "$ROOT_KEY" "$ROOT_CERT" "$INTERMEDIATE_KEY" "$INTERMEDIATE_CERT"; do
    if [ -s "$member" ]; then
        present=$((present + 1))
    fi
done

if [ "$present" -ne 0 ] && [ "$present" -ne 4 ]; then
    echo "ML-DSA-65 signing tuple is partial; refusing silent reconstruction" >&2
    exit 21
fi

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

key_matches_cert() {
    key="$1"
    cert="$2"
    openssl pkey -in "$key" -pubout -out "$WORK/key-public.pem" >/dev/null 2>&1 || return 1
    openssl x509 -in "$cert" -pubkey -noout >"$WORK/cert-public.pem" 2>/dev/null || return 1
    cmp -s "$WORK/key-public.pem" "$WORK/cert-public.pem"
}

if [ "$present" -eq 0 ]; then
    echo "[mldsa65] Creating persistent ML-DSA-65 root and intermediate signing tuple."
    openssl genpkey -algorithm ML-DSA-65 -out "$ROOT_KEY"
    openssl req -new -x509 \
        -key "$ROOT_KEY" \
        -subj '/CN=PQC Framework ML-DSA-65 Root CA/O=PQC Framework' \
        -days "$ROOT_DAYS" \
        -addext 'basicConstraints=critical,CA:TRUE,pathlen:1' \
        -addext 'keyUsage=critical,keyCertSign,cRLSign' \
        -out "$ROOT_CERT"

    openssl genpkey -algorithm ML-DSA-65 -out "$INTERMEDIATE_KEY"
    openssl req -new \
        -key "$INTERMEDIATE_KEY" \
        -subj '/CN=PQC Framework ML-DSA-65 Intermediate CA/O=PQC Framework' \
        -out "$WORK/intermediate.csr"
    cat >"$WORK/intermediate.ext" <<'EOC'
basicConstraints=critical,CA:TRUE,pathlen:0
keyUsage=critical,keyCertSign,cRLSign
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOC
    openssl x509 -req \
        -in "$WORK/intermediate.csr" \
        -CA "$ROOT_CERT" \
        -CAkey "$ROOT_KEY" \
        -CAcreateserial \
        -days "$INTERMEDIATE_DAYS" \
        -extfile "$WORK/intermediate.ext" \
        -out "$INTERMEDIATE_CERT"
else
    echo "[mldsa65] Reusing persistent ML-DSA-65 root and intermediate signing tuple."
fi

if ! key_matches_cert "$ROOT_KEY" "$ROOT_CERT" || ! key_matches_cert "$INTERMEDIATE_KEY" "$INTERMEDIATE_CERT"; then
    echo "ML-DSA-65 signing tuple contains a key/certificate mismatch; refusing replacement" >&2
    exit 22
fi
openssl verify -CAfile "$ROOT_CERT" "$ROOT_CERT" >/dev/null
openssl verify -CAfile "$ROOT_CERT" "$INTERMEDIATE_CERT" >/dev/null
chmod 0600 "$ROOT_KEY" "$INTERMEDIATE_KEY"
chmod 0644 "$ROOT_CERT" "$INTERMEDIATE_CERT"
cat "$INTERMEDIATE_CERT" "$ROOT_CERT" >"$PRIVATE_DIR/ca-chain.crt"
cp -f "$ROOT_CERT" "$PRIVATE_DIR/ca.crt"
chmod 0644 "$PRIVATE_DIR/ca.crt" "$PRIVATE_DIR/ca-chain.crt"

certificate_fresh() {
    cert="$1"
    [ -s "$cert" ] && openssl x509 -checkend "$((RENEW_BEFORE_DAYS * 86400))" -noout -in "$cert" >/dev/null 2>&1
}

issue_leaf() {
    mode="$1"
    cn="$2"
    sans="$3"
    out_dir="$4"
    crt="$5"
    key="$6"

    if certificate_fresh "$out_dir/$crt" && [ -s "$out_dir/$key" ]; then
        if openssl verify -CAfile "$ROOT_CERT" -untrusted "$INTERMEDIATE_CERT" "$out_dir/$crt" >/dev/null 2>&1 \
            && key_matches_cert "$out_dir/$key" "$out_dir/$crt"; then
            echo "[mldsa65] Existing $mode certificate remains outside the renewal window."
            return
        fi
    fi

    openssl genpkey -algorithm ML-DSA-65 -out "$WORK/$key"
    openssl req -new -key "$WORK/$key" -subj "/CN=$cn/O=PQC Framework" -out "$WORK/$mode.csr"

    if [ "$mode" = "server" ]; then
        eku='serverAuth'
    else
        eku='clientAuth'
    fi
    cat >"$WORK/$mode.ext" <<EOC
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature
extendedKeyUsage=$eku
subjectAltName=$sans
subjectKeyIdentifier=hash
authorityKeyIdentifier=keyid,issuer
EOC

    openssl x509 -req \
        -in "$WORK/$mode.csr" \
        -CA "$INTERMEDIATE_CERT" \
        -CAkey "$INTERMEDIATE_KEY" \
        -CAcreateserial \
        -days "$CERT_DAYS" \
        -extfile "$WORK/$mode.ext" \
        -out "$WORK/$crt"
    openssl verify -CAfile "$ROOT_CERT" -untrusted "$INTERMEDIATE_CERT" "$WORK/$crt" >/dev/null
    cp -f "$WORK/$crt" "$out_dir/$crt"
    cp -f "$WORK/$key" "$out_dir/$key"
    chmod 0644 "$out_dir/$crt"
    chmod 0600 "$out_dir/$key"
}

issue_leaf server mqtt-broker 'DNS:mqtt-broker,DNS:localhost,DNS:pqc-gateway1.pqcnet' "$BROKER_DIR" tls.crt tls.key
issue_leaf client stm32-mqtt-client 'DNS:stm32-mqtt-client' "$CLIENT_DIR" client.crt client.key

cat "$BROKER_DIR/tls.crt" "$INTERMEDIATE_CERT" >"$BROKER_DIR/tls-chain.crt"
cat "$CLIENT_DIR/client.crt" "$INTERMEDIATE_CERT" >"$CLIENT_DIR/client-chain.crt"
chmod 0644 "$BROKER_DIR/tls-chain.crt" "$CLIENT_DIR/client-chain.crt"

echo "[mldsa65] ML-DSA-65 certificate material ready."
