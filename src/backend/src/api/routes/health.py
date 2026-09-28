from fastapi import APIRouter, HTTPException
from src.core.diagnostics import collect_diagnostics, diagnostics_enabled
router = APIRouter(tags=["health"])
@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
@router.get("/health/diagnostics")
async def health_diagnostics() -> dict:
    if not diagnostics_enabled():
        raise HTTPException(status_code=404, detail="Diagnostics are disabled.")
    return await collect_diagnostics()
