#!/usr/bin/env sh
set -euo pipefail

# Start Vault
exec vault server -config=/vault/config/vault.hcl
