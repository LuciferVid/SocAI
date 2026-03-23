"""
IP Reputation API routes.
Lookup and manual tag override.
"""

import logging
from fastapi import APIRouter, HTTPException

from app.models.schemas import IPReputationOut, IPTagUpdate
from app.services.ip_reputation import get_reputation, override_tag

logger = logging.getLogger("soc.api.reputation")
router = APIRouter()


@router.get("/{ip}", response_model=IPReputationOut)
async def lookup_ip(ip: str):
    """Get reputation data for a specific IP."""
    record = await get_reputation(ip)
    if not record:
        raise HTTPException(status_code=404, detail="IP not found in reputation database")
    return record


@router.patch("/{ip}/tag")
async def update_ip_tag(ip: str, body: IPTagUpdate):
    """Manually override an IP's reputation tag."""
    success = await override_tag(ip, body.tag)
    if not success:
        raise HTTPException(status_code=404, detail="IP not found")
    return {"status": "updated", "ip": ip, "tag": body.tag}
