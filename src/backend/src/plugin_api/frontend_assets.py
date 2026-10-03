"""Package-only inline assets for cookie-isolated sandbox frontends."""

from __future__ import annotations

import html
import posixpath
import re
from collections.abc import Awaitable, Callable
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit


class _Assets(HTMLParser):
    def __init__(self, entry: str, nonce: str):
        super().__init__(convert_charrefs=False)
        self.entry = entry
        self.nonce = html.escape(nonce, quote=True)
        self.fragments: list[str] = []
        self.assets: list[tuple[int, str, str]] = []
        self.skip_script = False

    def asset(self, source: str, kind: str) -> None:
        url = urlsplit(source)
        decoded = unquote(url.path)
        if (
            url.scheme
            or url.netloc
            or url.query
            or url.fragment
            or decoded.startswith("/")
            or "\\" in decoded
            or ".." in decoded.split("/")
        ):
            raise ValueError("inline assets must be relative package paths")
        path = posixpath.normpath(posixpath.join(posixpath.dirname(self.entry), decoded))
        if not path.startswith("frontend/"):
            raise ValueError("inline asset escaped frontend root")
        self.assets.append((len(self.fragments), path, kind))
        self.fragments.append("")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and values.get("src"):
            if values.get("type", "text/javascript") not in {
                "text/javascript",
                "application/javascript",
            }:
                raise ValueError("inline assets require classic scripts")
            self.asset(str(values["src"]), "script")
            self.skip_script = True
        elif tag == "link" and values.get("rel") == "stylesheet" and values.get("href"):
            self.asset(str(values["href"]), "style")
        else:
            self.fragments.append(self.get_starttag_text() or "")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.skip_script:
            self.skip_script = False
        else:
            self.fragments.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.skip_script:
            self.fragments.append(data)

    def handle_entityref(self, name: str) -> None:
        self.fragments.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.fragments.append(f"&#{name};")

    def handle_decl(self, decl: str) -> None:
        self.fragments.append(f"<!{decl}>")

    def handle_comment(self, data: str) -> None:
        self.fragments.append(f"<!--{data}-->")


async def inline_frontend_assets(
    content: bytes, entry: str, nonce: str, loader: Callable[[str], Awaitable[bytes]]
) -> bytes:
    """Inline verified package CSS/JS without exposing assets or granting origin access."""
    parser = _Assets(entry, nonce)
    parser.feed(content.decode("utf-8"))
    if len(parser.assets) > 32:
        raise ValueError("too many inline assets")
    total = len(content)
    if total > 8 * 1024 * 1024:
        raise ValueError("inline frontend exceeds 8 MiB")
    for index, path, kind in parser.assets:
        data = await loader(path)
        total += len(data)
        if total > 8 * 1024 * 1024:
            raise ValueError("inline frontend exceeds 8 MiB")
        source = data.decode("utf-8")
        # Prevent embedded closing tags from terminating a raw-text element.
        source = re.sub(
            rf"</{kind}", lambda match: match[0].replace("/", "\\/"), source, flags=re.IGNORECASE
        )
        parser.fragments[index] = f'<{kind} nonce="{parser.nonce}">{source}</{kind}>'
    return "".join(parser.fragments).encode("utf-8")
