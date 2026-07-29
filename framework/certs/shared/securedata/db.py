import os
from urllib.parse import quote_plus

def build_sqlalchemy_url_from_env(
    user_var="DB_APP_USER", host_var="DB_HOST", port_var="DB_PORT", db_var="DB_NAME"
) -> str:
    user = os.getenv(user_var, "app_runtime")
    host = os.getenv(host_var, "db.a3team")
    port = os.getenv(port_var, "5432")
    db   = os.getenv(db_var, "appdb")

    sslmode     = os.getenv("PGSSLMODE", "verify-full")
    sslrootcert = os.getenv("PGSSLROOTCERT", "/certs/ca.crt")
    sslcert     = os.getenv("PGSSLCERT", "/certs/client.crt")
    sslkey      = os.getenv("PGSSLKEY", "/certs/client.key")

    q = quote_plus
    query = (
        f"sslmode={q(sslmode)}&sslrootcert={q(sslrootcert)}"
        f"&sslcert={q(sslcert)}&sslkey={q(sslkey)}"
    )
    return f"postgresql+psycopg://{user}@{host}:{port}/{db}?{query}"
