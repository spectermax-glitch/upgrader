"""QAdmin (god.specter.co) client.

Deploy-secret auth. QAdmin is the system of record for the asset
hierarchy, so everything topology-shaped is read from here.

Two surfaces, both taking the same deploy secret:

  /openapi/*  the documented REST facade -- preferred
  /trpc/*     the internal router the facade sits on, for the handful of
              fields the facade doesn't publish (the mothernode EIC is one)
""" 
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "https://god.specter.co"
SECRET_PATH = Path.home() / "secrets" / "qadmin"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "spctrl"

# /deployments is ~160KB and takes under a second, but a lookup shouldn't pay
# for it every time -- the hierarchy changes on install/swap timescales.
DEPLOYMENTS_TTL = 900

# The mothernode roster changes on the same timescales as the hierarchy.
MOTHERNODES_TTL = 900


class QAdminError(RuntimeError):
    pass


def read_secret() -> str:
    """Deploy secret from the environment, else ~/secrets/qadmin."""
    for var in ("SPCTRL_QADMIN_SECRET", "QADMIN_DEPLOY_SECRET"):
        val = os.environ.get(var)
        if val:
            return val.strip()
    try:
        return SECRET_PATH.read_text().strip()
    except OSError as exc:
        raise QAdminError(
            f"no QAdmin deploy secret: set SPCTRL_QADMIN_SECRET or write {SECRET_PATH} ({exc})"
        ) from exc


class QAdmin:
    def __init__(self, secret: str | None = None, base_url: str = BASE_URL):
        self.base = base_url.rstrip("/")
        self._http = requests.Session()
        self._http.headers["deploy-secret"] = secret or read_secret()

    def get(self, path: str) -> Any:
        return self._get(f"{self.base}/openapi/{path.lstrip('/')}")

    def trpc(self, procedure: str) -> Any:
        """Call an input-less tRPC query and unwrap its envelope.

        Responses come back as `{result: {data: ...}}`, with the payload
        under a further `json` key when the router has a superjson
        transformer configured. Both shapes are handled since that's a server
        setting this client shouldn't care about.
        """
        body = self._get(f"{self.base}/trpc/{procedure.lstrip('/')}")
        try:
            data = body["result"]["data"]
        except (KeyError, TypeError) as exc:
            raise QAdminError(f"unexpected tRPC envelope from {procedure}: {body!r:.200}") from exc
        if isinstance(data, dict) and "json" in data:
            return data["json"]
        return data

    def _get(self, url: str) -> Any:
        resp = self._http.get(url, timeout=30)
        if resp.status_code == 401:
            raise QAdminError(f"401 unauthorized -- deploy secret rejected ({url})")
        if resp.status_code == 404:
            raise QAdminError(f"404 not found: {url}")
        resp.raise_for_status()
        return resp.json() if resp.text else None

    # -- cache ------------------------------------------------------------
    def _cached(self, name: str, ttl: float, max_age: float, fetch) -> Any:
        """Disk-cached fetch. A cache that can't be read or written never
        fails the call it was meant to speed up."""
        cache = CACHE_DIR / f"{name}.json"
        if max_age > 0:
            try:
                if time.time() - cache.stat().st_mtime < max_age:
                    return json.loads(cache.read_text())
            except (OSError, ValueError):
                pass  # cold, stale beyond repair, or truncated -- refetch

        data = fetch()
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = cache.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data))
            tmp.replace(cache)
        except OSError:
            pass
        return data

    # -- topology ---------------------------------------------------------
    def deployments(self, max_age: float = DEPLOYMENTS_TTL) -> dict[str, Any]:
        """Full customer -> site -> mothernode -> sensor hierarchy, cached."""
        return self._cached("deployments", DEPLOYMENTS_TTL, max_age,
                            lambda: self.get("deployments"))

    def mothernodes(self, max_age: float = MOTHERNODES_TTL) -> list[dict[str, Any]]:
        """Every mothernode record, including inventory and decommissioned.

        Carries the fields `/deployments` leaves out -- `eic`, `notes`, the
        Starlink columns -- and is only available over tRPC.
        """
        rows = self._cached("mothernodes", MOTHERNODES_TTL, max_age,
                            lambda: self.trpc("mothernodes.list"))
        return rows if isinstance(rows, list) else []

    def mothernode_records(self, max_age: float = MOTHERNODES_TTL) -> dict[int, dict[str, Any]]:
        """`mothernodes()` keyed by asset ID."""
        return {r["asset_id"]: r for r in self.mothernodes(max_age) if r.get("asset_id")}

    # -- direct lookups ---------------------------------------------------
    def mothernode_ip(self, asset_id: int) -> str | None:
        """Mothernode Tailscale IP for a sensor, straight from QAdmin.

        Authoritative but context-free; the hierarchy is what carries the
        mothernode's own asset ID and site. Used to cross-check the cache.
        """
        try:
            return (self.get(f"sensors/{asset_id}/mothernode-hostname") or {}).get("hostname")
        except QAdminError:
            return None

    def asset_mapping(self, asset_id: int) -> dict[str, Any] | None:
        """Subdomain and site for any asset id."""
        try:
            return self.get(f"v2/asset-mappings/{asset_id}")
        except QAdminError:
            return None

    def tailscale_ip(self, asset_id: int) -> str | None:
        try:
            return (self.get(f"v2/assets/{asset_id}/tailscale-ip") or {}).get("ip")
        except QAdminError:
            return None
