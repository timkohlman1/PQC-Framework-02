#!/bin/bash

set -e # Exit immediately if a command exits with a non-zero status.

# The awslocal command is a wrapper around the AWS CLI that points to LocalStack (localhost:4566).
# Since LocalStack is running inside the container, awslocal is available in its environment.

echo "--- LocalStack Initialization Script Start ---"

ALIAS_NAME="alias/vault-unlock-key-alias"
REGION="us-east-1"
OUT_DIR="/out"
mkdir -p "$OUT_DIR"

# Does the alias already exist?
EXISTING_KEY_ID=$(awslocal kms list-aliases \
  --query "Aliases[?AliasName=='${ALIAS_NAME}'].TargetKeyId | [0]" \
  --output text 2>/dev/null || true)

if [ -z "$EXISTING_KEY_ID" ] || [ "$EXISTING_KEY_ID" = "None" ]; then
  echo "Creating new KMS key + alias ${ALIAS_NAME}..."
  NEW_KEY_ID=$(awslocal kms create-key \
    --description "Vault auto-unseal key (LocalStack)" \
    --query 'KeyMetadata.KeyId' \
    --output text)
  awslocal kms create-alias --alias-name "${ALIAS_NAME}" --target-key-id "${NEW_KEY_ID}"
  echo "Created KMS key ${NEW_KEY_ID} and alias ${ALIAS_NAME}."
  KEY_ID="${NEW_KEY_ID}"
else
  echo "Reusing existing KMS key for ${ALIAS_NAME}: ${EXISTING_KEY_ID}"
  KEY_ID="${EXISTING_KEY_ID}"
fi

# Resolve full ARN for the alias
KEY_ARN=$(awslocal kms describe-key \
  --key-id "${ALIAS_NAME}" \
  --query 'KeyMetadata.Arn' \
  --output text)

echo "Resolved KMS ARN: ${KEY_ARN}"

# Publish for other containers
echo -n "${KEY_ARN}"   > "${OUT_DIR}/kms_key_arn"
echo -n "${REGION}"    > "${OUT_DIR}/aws_region"
echo -n "http://localstack:4566" > "${OUT_DIR}/aws_endpoint"

echo "--- LocalStack Initialization Script Complete ---"
