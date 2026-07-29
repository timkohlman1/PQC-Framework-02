# OQS hybrid mutual TLS broker profile

This profile uses the same classical Step CA hierarchy and the same
`SecP256r1MLKEM768` TLS 1.3 hybrid key-exchange capability as the `oqs`
server-authentication profile. It additionally requires and validates a
classical client certificate. No ML-DSA TLS signatures are used.
