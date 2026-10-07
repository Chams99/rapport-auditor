"""Compatibility package for the pre-monorepo Flask import path."""


def __getattr__(name: str):
    if name in {"app", "create_app"}:
        from .web import app, create_app

        return {"app": app, "create_app": create_app}[name]
    raise AttributeError(name)


__all__ = ["app", "create_app"]
