# pylint: disable=missing-module-docstring,missing-function-docstring,too-few-public-methods
from __future__ import annotations

import re
from typing import Any

_GUID_PATTERN = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class XboxError(RuntimeError):
    """Raised when the stored Xbox/Azure AD credentials look invalid."""


class XboxClient:
    """Xbox Live's real API needs a full Azure AD OAuth consent flow
    (a redirect back from Microsoft), which a Settings-page form can't host
    yet. This client only confirms the app credentials are shaped like a
    real Azure AD app registration — it does NOT verify them against
    Microsoft, and does NOT pull any game/achievement data. See the
    Settings plan's "Xbox gets no real validation this pass" decision."""

    def __init__(self, client_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    def validate(self) -> dict[str, Any]:
        if not self.client_id or not self.client_secret:
            raise XboxError("Both a client ID and client secret are required.")
        if not _GUID_PATTERN.match(self.client_id.strip()):
            raise XboxError(
                "That doesn't look like an Azure AD application (client) ID: expected a GUID."
            )
        # Cannot verify the secret without a full OAuth consent redirect —
        # accepted as "saved", not "connected". See module docstring.
        return {"validated": False, "saved": True}
