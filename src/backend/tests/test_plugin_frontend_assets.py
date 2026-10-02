"""Package assets remain authenticated while opaque sandbox subresources need no cookie."""

from unittest.mock import AsyncMock

import pytest

from src.api.routes.plugins import _filter_ui_document
from src.plugin_api.contracts import PluginUiDocument
from src.plugin_api.frontend_assets import inline_frontend_assets


@pytest.mark.asyncio
async def test_inline_assets_use_only_package_css_and_nonce_scripts():
    loader = AsyncMock(
        side_effect=[b"body { color: red; }", b'window.text="</script><script>evil()</script>";']
    )
    output = await inline_frontend_assets(
        b'<link rel="stylesheet" href="./style.css"><script src="./app.js"></script><p>Hi &amp; bye</p>',
        "frontend/index.html",
        "nonce",
        loader,
    )
    assert b'<style nonce="nonce">body { color: red; }</style>' in output
    assert b'<script nonce="nonce">' in output
    assert (
        b"<script>evil()" in output
    )  # Closing tag is escaped; it remains script source, not markup.
    assert b"<\\/script>" in output
    assert b" src=" not in output and b" href=" not in output
    assert b"Hi &amp; bye" in output
    assert [call.args[0] for call in loader.await_args_list] == [
        "frontend/style.css",
        "frontend/app.js",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source",
    ["../private.py", "..%2fprivate.py", "/api/auth", "https://evil.test/x.js", "a.js?token=x"],
)
async def test_inline_assets_reject_escape_and_network_sources(source):
    loader = AsyncMock()
    with pytest.raises(ValueError):
        await inline_frontend_assets(
            f'<script src="{source}"></script>'.encode(), "frontend/index.html", "nonce", loader
        )
    loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_inline_assets_enforce_count_and_combined_size_limits():
    loader = AsyncMock(return_value=b"x" * (8 * 1024 * 1024))
    with pytest.raises(ValueError, match="8 MiB"):
        await inline_frontend_assets(
            b'<script src="app.js"></script>', "frontend/index.html", "nonce", loader
        )
    loader.reset_mock()
    with pytest.raises(ValueError, match="too many"):
        await inline_frontend_assets(
            b'<script src="app.js"></script>' * 33, "frontend/index.html", "nonce", loader
        )
    loader.assert_not_awaited()


def test_reader_registration_requires_both_live_capabilities_and_a_real_page():
    data = {
        "plugin_id": "example.reader",
        "title": "Reader",
        "pages": [{"id": "reader", "title": "Reader"}],
        "document_readers": [{"id": "reader", "page_id": "reader", "label": "Read"}],
    }
    document = PluginUiDocument.model_validate(data)
    for grants in (
        frozenset(),
        frozenset({"documents.read"}),
        frozenset({"frontend.context.documents"}),
    ):
        assert not _filter_ui_document(document, grants).document_readers
    assert _filter_ui_document(
        document, frozenset({"documents.read", "frontend.context.documents"})
    ).document_readers
    data["document_readers"][0]["page_id"] = "missing"
    with pytest.raises(ValueError):
        PluginUiDocument.model_validate(data)
