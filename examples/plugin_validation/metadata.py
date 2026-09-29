"""Minimal metadata provider example using normalized Plugin API DTOs."""
from dataclasses import dataclass

from src.plugin_api.coordinators import MetadataCandidate, MetadataProvider, MetadataProviderRequest


@dataclass
class ExampleMetadataPlugin(MetadataProvider):
    api_version: str = "v1"
    candidates: tuple[MetadataCandidate, ...] = ()

    async def search(self, request: MetadataProviderRequest) -> list[MetadataCandidate]:
        query = request.query.casefold()
        return [candidate for candidate in self.candidates if query in candidate.title.casefold()]
