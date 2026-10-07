"""Packaged templates and static assets for the Rapport Auditor web UI."""

from pathlib import Path


WEB_PACKAGE_DIR = Path(__file__).resolve().parent

__all__ = ["WEB_PACKAGE_DIR"]
