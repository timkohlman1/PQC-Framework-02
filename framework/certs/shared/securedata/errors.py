class SecureDataError(RuntimeError):
    """Base exception for the certificate storage client."""


class VaultRequestError(SecureDataError):
    """A Vault HTTP request failed."""


class SecretFormatError(SecureDataError):
    """Stored certificate or key material has an invalid shape."""
