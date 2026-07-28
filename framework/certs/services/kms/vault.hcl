ui = true

storage "file" {
  path = "/vault/data"
}

seal "awskms" {
  region     = "us-east-1"
  kms_key_id = "alias/vault-unlock-key-alias"
  endpoint   = "http://localstack:4566"
}

# Configure the listener
listener "tcp" {
  address = "[::]:8200"
  # Disable TLS for simple local development
  tls_disable = "true"
}

api_addr     = "http://vault:8200"
cluster_addr = "http://vault:8201"
