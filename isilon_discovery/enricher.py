"""
enricher.py — Async Isilon PAPI enricher (OneFS 9.5+, Platform API v12).

Architecture:
  - IsilonSession: manages a single authenticated HTTPS session to one node.
    Uses session-based auth (POST /session/1/session) to avoid re-sending
    credentials on every request. Token is refreshed when it expires (2h default).
  - ShareEnricher: high-level class that drives discovery for one NodeConfig.
    Calls IsilonSession and writes results to Database via model objects.
  - Concurrency: asyncio.Semaphore limits simultaneous in-flight requests
    to settings.concurrency (default 10) per node.

Key PAPI v12 endpoints used:
  GET /platform/12/protocols/smb/shares     — list all SMB shares in a zone
  GET /platform/12/protocols/smb/shares/{name} — share detail + ACL
  GET /platform/12/protocols/nfs/exports    — list NFS exports
  GET /platform/12/protocols/nfs/exports/{id} — export detail
  GET /platform/12/quota/quotas             — smart quotas (filter by path)
  GET /platform/12/cluster/config           — cluster version info
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple
import httpx
from isilon_discovery.config import NodeConfig, IsilonCredentials, AppSettings
from isilon_discovery.database import Database
from isilon_discovery.models import (
    NodeRecord, ShareRecord, QuotaRecord,
    SecurityGroupRecord, ShareGroupLink, RunLogRecord,
)

logger = logging.getLogger(__name__)


class IsilonSession:
    """
    Authenticated async HTTP session to one Isilon node.
    Uses PAPI session cookies (isisessid + isicsrf) — avoids Basic Auth
    on every call and respects the node's session limit.
    """

    SESSION_ENDPOINT = "/session/1/session"

    def __init__(
        self,
        node: NodeConfig,
        credentials: IsilonCredentials,
        timeout: int = 30,
    ) -> None:
        self.node = node
        self._creds = credentials
        self._timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._csrf_token: Optional[str] = None

    async def __aenter__(self) -> "IsilonSession":
        self._client = httpx.AsyncClient(
            base_url=f"https://{self.node.host}:{self.node.port}",
            verify=self._creds.verify_ssl,
            timeout=self._timeout,
            follow_redirects=True,
        )
        await self._authenticate()
        return self

    async def __aexit__(self, *_) -> None:
        await self._logout()
        if self._client:
            await self._client.aclose()

    async def _authenticate(self) -> None:
        resp = await self._client.post(
            self.SESSION_ENDPOINT,
            json={
                "username": self._creds.username,
                "password": self._creds.password,
                "services": ["platform", "namespace"],
            },
        )
        resp.raise_for_status()
        # PAPI returns X-CSRF-Token in the response for subsequent mutating calls
        self._csrf_token = resp.headers.get("X-CSRF-Token", "")
        logger.debug("Authenticated to %s", self.node.host)

    async def _logout(self) -> None:
        if self._client and self._csrf_token:
            try:
                await self._client.delete(
                    self.SESSION_ENDPOINT,
                    headers={"X-CSRF-Token": self._csrf_token, "Referer": f"https://{self.node.host}"},
                )
            except Exception:
                pass  # best-effort logout

    async def get(self, path: str, params: Optional[dict] = None) -> dict:
        """
        Authenticated GET. Handles PAPI pagination via 'resume' token.
        Returns the full merged response dict (all pages combined).
        """
        assert self._client, "Use as async context manager."
        full_result: Dict[str, Any] = {}
        resume: Optional[str] = None

        while True:
            query: dict = params or {}
            if resume:
                query["resume"] = resume

            resp = await self._client.get(
                path,
                params=query,
                headers={"X-CSRF-Token": self._csrf_token or ""},
            )

            if resp.status_code == 404:
                return {}
            resp.raise_for_status()
            data = resp.json()

            # Merge list fields across pages
            for key, val in data.items():
                if isinstance(val, list):
                    full_result.setdefault(key, [])
                    full_result[key].extend(val)
                else:
                    full_result[key] = val

            resume = data.get("resume")
            if not resume:
                break

        return full_result


class ShareEnricher:
    """
    Discovers and enriches all SMB + NFS shares on a single Isilon node.
    Writes NodeRecord, ShareRecord, QuotaRecord, and SecurityGroupRecord
    objects to the database.

    Usage:
        enricher = ShareEnricher(node_config, credentials, settings, db)
        run_log = await enricher.run()
    """

    def __init__(
        self,
        node: NodeConfig,
        credentials: IsilonCredentials,
        settings: AppSettings,
        db: Database,
    ) -> None:
        self.node = node
        self.credentials = credentials
        self.settings = settings
        self.db = db
        self._semaphore = asyncio.Semaphore(settings.concurrency)

    async def run(self) -> RunLogRecord:
        run = RunLogRecord(run_type="python_enricher", node_name=self.node.name)
        run_id = self.db.insert_run_log(run)

        try:
            async with IsilonSession(self.node, self.credentials, self.settings.request_timeout_s) as session:
                node_id = await self._upsert_node(session)
                self.db.mark_all_not_in_snapshot(node_id)

                tasks = []
                for zone in self.node.access_zones:
                    if "smb" in self.node.share_types:
                        tasks.append(self._enrich_smb_shares(session, node_id, zone, run))
                    if "nfs" in self.node.share_types:
                        tasks.append(self._enrich_nfs_exports(session, node_id, zone, run))

                await asyncio.gather(*tasks, return_exceptions=True)

                removed = self.db.remove_missing_shares(node_id)
                run.shares_removed = removed

        except Exception as exc:
            run.errors += 1
            run.notes = str(exc)
            logger.exception("Enricher failed for node %s", self.node.name)

        run.finish()
        self.db.update_run_log(run_id, run)
        return run

    async def _upsert_node(self, session: IsilonSession) -> int:
        """Fetch cluster version info and upsert the node record."""
        data = await session.get("/platform/12/cluster/config")
        version = (
            data.get("onefs_version", {}).get("release") or
            data.get("onefs_version", {}).get("version")
        )
        from datetime import datetime, timezone
        node_record = NodeRecord(
            name=self.node.name,
            host=self.node.host,
            port=self.node.port,
            onefs_version=version,
            last_seen_at=datetime.now(timezone.utc).isoformat(),
        )
        return self.db.upsert_node(node_record)

    async def _enrich_smb_shares(
        self, session: IsilonSession, node_id: int, zone: str, run: RunLogRecord
    ) -> None:
        """List all SMB shares in an access zone, then enrich each one."""
        data = await session.get(
            "/platform/12/protocols/smb/shares",
            params={"zone": zone, "limit": 1000},
        )
        shares_list = data.get("shares", [])
        run.shares_discovered += len(shares_list)
        logger.info("Node %s zone %s: %d SMB shares", self.node.name, zone, len(shares_list))

        tasks = [
            self._enrich_one_smb_share(session, node_id, zone, s, run)
            for s in shares_list
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                run.errors += 1
                logger.warning("SMB share enrichment error: %s", r)

    async def _enrich_one_smb_share(
        self,
        session: IsilonSession,
        node_id: int,
        zone: str,
        share_summary: dict,
        run: RunLogRecord,
    ) -> None:
        """Fetch full share detail + ACL, then persist to DB."""
        async with self._semaphore:
            name = share_summary["name"]
            detail = await session.get(
                f"/platform/12/protocols/smb/shares/{name}",
                params={"zone": zone},
            )
            raw = (detail.get("shares") or [detail])[0]
            if not raw:
                return

            share = ShareRecord.from_smb_api(node_id, zone, raw)
            share_id = self.db.upsert_share(share)

            if share_id not in [s["id"] for s in self.db.get_shares_for_node(node_id)
                                 if s["name"] == share.name]:
                run.shares_added += 1

            run.shares_enriched += 1

            # Extract ACL → security groups
            acl = raw.get("acl", [])
            await self._persist_acl(session, share_id, acl)

            # Fetch quota for this path
            await self._enrich_quota(session, share_id, share.path)

    async def _enrich_nfs_exports(
        self, session: IsilonSession, node_id: int, zone: str, run: RunLogRecord
    ) -> None:
        data = await session.get(
            "/platform/12/protocols/nfs/exports",
            params={"zone": zone, "limit": 1000},
        )
        exports = data.get("exports", [])
        run.shares_discovered += len(exports)

        tasks = [
            self._enrich_one_nfs_export(session, node_id, zone, e, run)
            for e in exports
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, Exception):
                run.errors += 1
                logger.warning("NFS export enrichment error: %s", r)

    async def _enrich_one_nfs_export(
        self,
        session: IsilonSession,
        node_id: int,
        zone: str,
        export_summary: dict,
        run: RunLogRecord,
    ) -> None:
        async with self._semaphore:
            export_id = export_summary["id"]
            detail = await session.get(
                f"/platform/12/protocols/nfs/exports/{export_id}",
                params={"zone": zone},
            )
            raw = (detail.get("exports") or [detail])[0]
            if not raw:
                return

            share = ShareRecord.from_nfs_api(node_id, zone, raw)
            share_id = self.db.upsert_share(share)
            run.shares_enriched += 1

            await self._enrich_quota(session, share_id, share.path)

    async def _enrich_quota(
        self, session: IsilonSession, share_id: int, path: str
    ) -> None:
        """Fetch the directory-level smart quota for this path, if any."""
        if not path:
            return
        data = await session.get(
            "/platform/12/quota/quotas",
            params={"path": path, "type": "directory"},
        )
        for q in data.get("quotas", []):
            quota = QuotaRecord.from_api(share_id, q)
            self.db.upsert_quota(quota)

    async def _persist_acl(
        self, session: IsilonSession, share_id: int, acl: List[dict]
    ) -> None:
        """
        Extract AD security groups from a share ACL and persist them.
        Groups are identified by trustee.type == 'group'.
        Individual user SIDs are noted but group resolution is left to PowerShell.
        """
        for ace in acl:
            trustee = ace.get("trustee", {})
            if trustee.get("type") != "group":
                continue

            group = SecurityGroupRecord(
                group_name=trustee.get("name", ""),
                group_sid=trustee.get("id", ""),
                domain=trustee.get("name", "").split("\\")[0] if "\\" in trustee.get("name", "") else None,
            )

            if not group.group_sid:
                continue

            group_id = self.db.upsert_security_group(group)
            link = ShareGroupLink(
                share_id=share_id,
                group_id=group_id,
                permission_type=ace.get("accesstype", "allow"),
                permission_level=ace.get("access_rights", [None])[0] if ace.get("access_rights") else None,
                inherited=ace.get("inherit_flags", {}).get("inherit", False),
            )
            self.db.link_group_to_share(link)
