"""Generate and preserve the local secrets in .env. Never prints secret values.

One command (`./start`) runs this before the stack comes up: every value a
person would otherwise have to invent is created here on first run and kept
for later runs. Existing values are never overwritten.
"""
import base64
import os
import secrets
import string
import sys
from pathlib import Path

ENV = Path(".env")
GENERATED = {
    "ELEARNING_SITE_NAME": "elearning.localhost",
    "ELEARNING_DB_PASSWORD": lambda: "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(24)
    ),
    "ELEARNING_ADMIN_PASSWORD": lambda: "".join(
        secrets.choice(string.ascii_letters + string.digits) for _ in range(20)
    ),
    # A Fernet key, which is the format the framework validates.
    "ELEARNING_ENCRYPTION_KEY": lambda: base64.urlsafe_b64encode(
        os.urandom(32)
    ).decode(),
    "ELEARNING_COMPOSE_PROJECT": lambda: "elearning-"
    + secrets.token_hex(4).lower(),
}
DEFAULT_PORT = 18091
PORT_STEP = 1
PORT_ATTEMPTS = 50


def read_env():
    values = {}
    if ENV.exists():
        for line in ENV.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def write_env(values):
    lines = []
    for key, value in values.items():
        lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")
    os.chmod(ENV, 0o600)


def port_free(port):
    import socket

    with socket.socket() as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def main():
    values = read_env()
    changed = False
    for key, generate in GENERATED.items():
        if not values.get(key):
            values[key] = generate() if callable(generate) else generate
            changed = True
    if not values.get("ELEARNING_LOCAL_PORT"):
        port = int(os.environ.get("ELEARNING_PORT_START", DEFAULT_PORT))
        for _ in range(PORT_ATTEMPTS):
            if port_free(port):
                values["ELEARNING_LOCAL_PORT"] = str(port)
                changed = True
                break
            port += PORT_STEP
        else:
            sys.exit("No local port is available. Stop an unused service and run ./start again.")
    if changed or not ENV.exists():
        write_env(values)
    if "--print-port" in sys.argv:
        print(values["ELEARNING_LOCAL_PORT"])


if __name__ == "__main__":
    main()
