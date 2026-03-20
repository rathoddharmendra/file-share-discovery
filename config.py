"""
config.py — loads inventory.yaml (non-secret) + .env (secrets, outside project).

.env resolution priority:
  1. ISILON_ENV_FILE env var (user sets in shell / task scheduler)
  2. ~/.isilon_discovery.env  (default convention)
  3. .env in CWD             (dev fallback only)
"""
from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
import yaml
from dotenv import load_dotenv


def _resolve_env_file() -> Path:
    explicit = os.environ.get("ISILON_ENV_FILE")
    if explicit:
        p = Path(explicit)
        if p.exists():
            return p
        raise FileNotFoundError(f"ISILON_ENV_FILE='{explicit}' not found.")
    default = Path.home() / ".isilon_discovery.env"
    if default.exists():
        return default
    fallback = Path(".env")
    if fallback.exists():
        return fallback
    raise FileNotFoundError(
        "No .env file found. Create ~/.isilon_discovery.env "
        "or set ISILON_ENV_FILE."
    )


def load_secrets() -> None:
    """Load .env into os.environ. Call once at process startup."""
    load_dotenv(dotenv_path=_resolve_env_file(), override=False)


@dataclass
class NodeConfig:
    name: str
    host: str
    port: int = 8080
    access_zones: List[str] = field(default_factory=lambda: ["System"])
    share_types: List[str] = field(default_factory=lambda: ["smb", "nfs"])
    enabled: bool = True

    @property
    def base_url(self) -> str:
        # OneFS 9.5 PAPI version 12
        return f"https://{self.host}:{self.port}/platform/12"


@dataclass
class AppSettings:
    db_path: str = "./shares.db"
    snapshot_dir: str = "./snapshots"
    concurrency: int = 10
    request_timeout_s: int = 30


@dataclass
class IsilonCredentials:
    username: str
    password: str
    verify_ssl: bool = False

    @classmethod
    def from_env(cls) -> "IsilonCredentials":
        u = os.environ.get("ISILON_USERNAME")
        p = os.environ.get("ISILON_PASSWORD")
        if not u or not p:
            raise EnvironmentError(
                "ISILON_USERNAME and ISILON_PASSWORD must be set in your .env file."
            )
        return cls(
            username=u,
            password=p,
            verify_ssl=os.environ.get("ISILON_VERIFY_SSL", "false").lower() == "true",
        )


@dataclass
class GraphCredentials:
    tenant_id: str
    client_id: str
    client_secret: str

    @classmethod
    def from_env(cls) -> Optional["GraphCredentials"]:
        t = os.environ.get("GRAPH_TENANT_ID")
        c = os.environ.get("GRAPH_CLIENT_ID")
        s = os.environ.get("GRAPH_CLIENT_SECRET")
        return cls(tenant_id=t, client_id=c, client_secret=s) if (t and c and s) else None


@dataclass
class Config:
    nodes: List[NodeConfig]
    settings: AppSettings
    credentials: IsilonCredentials
    graph_credentials: Optional[GraphCredentials] = None

    @classmethod
    def load(cls, inventory_path: str = "inventory.yaml") -> "Config":
        raw = _load_yaml(inventory_path)
        return cls(
            nodes=[NodeConfig(**n) for n in raw.get("nodes", [])],
            settings=AppSettings(**raw.get("settings", {})),
            credentials=IsilonCredentials.from_env(),
            graph_credentials=GraphCredentials.from_env(),
        )

    @property
    def active_nodes(self) -> List[NodeConfig]:
        return [n for n in self.nodes if n.enabled]


def _load_yaml(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"inventory.yaml not found at '{path}'.")
    with p.open() as fh:
        return yaml.safe_load(fh) or {}
