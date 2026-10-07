from __future__ import annotations

import argparse
import ipaddress
import logging

from waitress import serve

from . import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the local Rapport Auditor web app.")
    parser.add_argument("--host", help="bind address (non-loopback requires server profile)")
    parser.add_argument("--port", type=int)
    parser.add_argument("--threads", type=int)
    args = parser.parse_args()
    app = create_app()
    host = args.host or app.config["HOST"]
    port = args.port if args.port is not None else app.config["PORT"]
    threads = args.threads if args.threads is not None else app.config["THREADS"]
    if not 1 <= port <= 65535 or not 1 <= threads <= 32:
        parser.error("port must be 1–65535 and threads must be 1–32")
    if app.config["APP_MODE"] == "local":
        try:
            if not ipaddress.ip_address(host).is_loopback:
                parser.error("non-loopback binding requires RAPPORT_AUDITOR_MODE=server")
        except ValueError:
            if host != "localhost":
                parser.error("local mode may bind only to localhost or a loopback IP")
    body_limit = int(app.config["MAX_CONTENT_LENGTH"])
    options = {
        "host": host,
        "port": port,
        "threads": threads,
        "channel_timeout": 30,
        "connection_limit": min(16, max(8, threads * 2)),
        "max_request_body_size": body_limit,
        "inbuf_overflow": body_limit + 100_000,
        "outbuf_overflow": int(app.config["WAITRESS_OUTBUF_OVERFLOW"]),
        "log_socket_errors": False,
    }
    if app.config["APP_MODE"] == "server":
        options.update(
            trusted_proxy=app.config["TRUSTED_PROXY"],
            trusted_proxy_count=1,
            trusted_proxy_headers={"x-forwarded-for", "x-forwarded-proto"},
            clear_untrusted_proxy_headers=True,
            log_untrusted_proxy_headers=False,
        )
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Waitress's diagnostics can include request paths or socket details. The
    # app emits correlation-only structured request events instead.
    logging.getLogger("waitress").setLevel(logging.CRITICAL)
    logging.getLogger("waitress.queue").setLevel(logging.CRITICAL)
    logging.getLogger("rapport_api").info(
        '{"event":"server_starting","profile":"%s","bind_host":"%s","port":%d}',
        app.config["APP_MODE"],
        host,
        port,
    )
    serve(
        app,
        **options,
    )


if __name__ == "__main__":
    main()
