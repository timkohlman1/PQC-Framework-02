# Experimental OQS Mosquitto profile

The `mqtt-oqs` Compose profile uses `openquantumsafe/mosquitto:latest` as an experimental post-quantum TLS broker image.

This profile is intended for protocol evaluation only. It is not a production TLS configuration and does not share the classical Mosquitto configuration files in this repository. Confirm negotiated algorithms from explicit broker/client logs before recording benchmark or security claims.

Default environment values are declared in `experiment/mqtt-broker/env.example` and may be overridden in a local `.env` file on the target host. Do not commit real `.env` files.
