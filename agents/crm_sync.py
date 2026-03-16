"""
CRM Sync Agent
Pushes prospect activity to HubSpot/Salesforce. Mock mode logs all operations.
"""
import json
import logging
from dataclasses import dataclass
from agents.base import BaseAgent
from config import settings

logger = logging.getLogger(__name__)


@dataclass
class SyncResult:
    crm: str
    action: str
    record_id: str
    success: bool
    mock: bool = False
    error: str = ""


class CRMSyncAgent(BaseAgent):
    """Syncs prospect data and activity to CRM systems."""

    async def run(self, action: str, payload: dict) -> SyncResult:
        if settings.hubspot_api_key:
            return await self._sync_hubspot(action, payload)
        return self._mock_sync(action, payload)

    # ── HubSpot ────────────────────────────────────────────────────────────

    async def _sync_hubspot(self, action: str, payload: dict) -> SyncResult:
        import httpx
        headers = {
            "Authorization": f"Bearer {settings.hubspot_api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(base_url="https://api.hubapi.com", timeout=10) as client:
                if action == "upsert_contact":
                    return await self._hs_upsert_contact(client, headers, payload)
                if action == "log_activity":
                    return await self._hs_log_activity(client, headers, payload)
                if action == "create_deal":
                    return await self._hs_create_deal(client, headers, payload)
        except Exception as exc:
            logger.error("HubSpot sync error: %s", exc)
            return SyncResult(crm="hubspot", action=action, record_id="", success=False, error=str(exc))
        return self._mock_sync(action, payload)

    async def _hs_upsert_contact(self, client, headers: dict, payload: dict) -> SyncResult:
        data = {
            "properties": {
                "email": payload.get("email", ""),
                "firstname": payload.get("first_name", ""),
                "lastname": payload.get("last_name", ""),
                "jobtitle": payload.get("title", ""),
                "company": payload.get("company", ""),
                "hs_lead_status": payload.get("status", "NEW"),
            }
        }
        resp = await client.post("/crm/v3/objects/contacts", json=data, headers=headers)
        resp.raise_for_status()
        record_id = resp.json().get("id", "")
        logger.info("HubSpot contact upserted: %s", record_id)
        return SyncResult(crm="hubspot", action="upsert_contact", record_id=record_id, success=True)

    async def _hs_log_activity(self, client, headers: dict, payload: dict) -> SyncResult:
        data = {
            "properties": {
                "hs_activity_type": payload.get("type", "EMAIL"),
                "hs_body_preview": payload.get("body", "")[:200],
                "hs_timestamp": payload.get("timestamp", ""),
            }
        }
        resp = await client.post("/crm/v3/objects/communications", json=data, headers=headers)
        resp.raise_for_status()
        record_id = resp.json().get("id", "")
        logger.info("HubSpot activity logged: %s", record_id)
        return SyncResult(crm="hubspot", action="log_activity", record_id=record_id, success=True)

    async def _hs_create_deal(self, client, headers: dict, payload: dict) -> SyncResult:
        data = {
            "properties": {
                "dealname": f"{payload.get('company', 'Unknown')} - Meeting Booked",
                "dealstage": "appointmentscheduled",
                "pipeline": "default",
            }
        }
        resp = await client.post("/crm/v3/objects/deals", json=data, headers=headers)
        resp.raise_for_status()
        record_id = resp.json().get("id", "")
        logger.info("HubSpot deal created: %s", record_id)
        return SyncResult(crm="hubspot", action="create_deal", record_id=record_id, success=True)

    # ── Mock mode ──────────────────────────────────────────────────────────

    def _mock_sync(self, action: str, payload: dict) -> SyncResult:
        logger.info("[MOCK CRM] %s — %s", action, json.dumps(payload, default=str)[:100])
        return SyncResult(
            crm="mock",
            action=action,
            record_id=f"mock-{action}-{id(payload)}",
            success=True,
            mock=True,
        )
