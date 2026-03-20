"""
Compatibility wrapper for `config.py` at the repository root.

The project originally lived at the repo root; this wrapper keeps the code
working while exposing a clean package layout as `isilon_discovery.*`.
"""

from config import (  # type: ignore
    load_secrets,
    Config,
    NodeConfig,
    AppSettings,
    IsilonCredentials,
    GraphCredentials,
)

__all__ = [
    "load_secrets",
    "Config",
    "NodeConfig",
    "AppSettings",
    "IsilonCredentials",
    "GraphCredentials",
]

