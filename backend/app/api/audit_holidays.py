"""Client holiday calendar for check A-13 (docs/PHASE8_API_CONTRACT.md, package B). Routes are added by package B."""

from fastapi import APIRouter

router = APIRouter(tags=["audit_holidays"])
