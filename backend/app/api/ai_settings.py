"""Per-client AI switch, model-call log and narration suggestions (docs/PHASE7_API_CONTRACT.md, packages C and F). Routes are added by C and F."""

from fastapi import APIRouter

router = APIRouter(tags=["ai"])
