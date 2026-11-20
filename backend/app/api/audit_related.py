"""Related-party flags for check A-18 (docs/PHASE8_API_CONTRACT.md, package D). Routes are added by package D."""

from fastapi import APIRouter

router = APIRouter(tags=["audit_related"])
