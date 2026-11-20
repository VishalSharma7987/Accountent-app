"""Sampling helpers (random / systematic / value) with recorded seeds (docs/PHASE8_API_CONTRACT.md, package E). Routes are added by package E."""

from fastapi import APIRouter

router = APIRouter(tags=["audit_sampling"])
