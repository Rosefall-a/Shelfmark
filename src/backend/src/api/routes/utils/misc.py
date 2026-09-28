# pylint: disable=missing-module-docstring
from fastapi import APIRouter, Depends

from src.core.auth import get_current_user
from src.helpers.currency_codes import CURRENCY_CODES

router = APIRouter(prefix="/api", tags=["misc"], dependencies=[Depends(get_current_user)])


@router.get("/currency-codes")
def get_allowed_currency_codes() -> dict[str, list[str]]:
    """Return the ISO 4217 currency codes accepted by the API."""
    return {"codes": CURRENCY_CODES}
