# Request 10 final cleanup

This package contains the final canonical-config cleanup replacements. After extracting it at the repository root, remove the retired paths listed in `REQUEST10_DELETE_PATHS.txt`.

Then remove stale generated state (`.pqc-generated-state`) and `.last_successful_build.json`, regenerate campaigns from `configs/campaigns`, and run the unit verification commands supplied with the delivery message.

The cleanup keeps `configs/{targets,gateways,instruments/energy,services/mqtt_broker,workloads,tls_kex,tls_auth,secure_boot,network_conditions,campaigns}` as the canonical configuration hierarchy.
