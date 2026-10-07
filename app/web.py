"""Compatibility facade for existing `from app.web import app` users."""

from rapport_api import create_app


app = create_app()

__all__ = ["app", "create_app"]


if __name__ == "__main__":
    from rapport_api.cli import main

    main()
