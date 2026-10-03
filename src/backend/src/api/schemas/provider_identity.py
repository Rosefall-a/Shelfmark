"""Bounded provider namespaces shared by native and plugin import payloads."""

from typing import Annotated

from pydantic import BeforeValidator, Field

ProviderIDs = Annotated[
    dict[
        Annotated[str, Field(pattern=r"^[a-z0-9._-]{1,50}$")],
        Annotated[str, Field(max_length=256)],
    ],
    Field(max_length=32),
    BeforeValidator(lambda value: {} if value is None else value),
]
