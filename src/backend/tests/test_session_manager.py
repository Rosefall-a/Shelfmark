from src.core.geoip import GeoIpProvider, GeoLocation
from src.core.session_manager import create_session, session_state
from src.api.routes.session_manager import view
from src.database.models.auth import UserSession


def test_session_state_distinguishes_active_expired_and_revoked() -> None:
    active = UserSession(expires_at=200, revoked_at=None, last_seen_at=100)
    expired = UserSession(expires_at=100, revoked_at=None, last_seen_at=50)
    revoked = UserSession(expires_at=200, revoked_at=150, last_seen_at=100)
    assert session_state(active, 150) == "active"
    assert session_state(expired, 150) == "expired"
    assert session_state(revoked, 150) == "revoked"


def test_geoip_missing_database_is_unavailable(tmp_path) -> None:
    provider = GeoIpProvider(str(tmp_path / "missing.mmdb"))
    assert provider.lookup("8.8.8.8") == GeoLocation()


def test_geoip_private_addresses_are_classified(tmp_path) -> None:
    provider = GeoIpProvider(str(tmp_path / "missing.mmdb"))
    assert (
        provider.lookup("192.168.1.20").network_label == "RFC 1918 private address (192.168.0.0/16)"
    )
    assert provider.lookup("100.64.1.20").network_label == "CGNAT / RFC 6598 shared address"
    assert provider.lookup("127.0.0.1").network_label == "Loopback address"
    assert provider.lookup("::1").network_label == "Loopback address"
    assert provider.lookup("fc00::1").network_label == "IPv6 unique-local address (RFC 4193)"


def test_geoip_malformed_database_fails_closed(tmp_path) -> None:
    path = tmp_path / "bad.mmdb"
    path.write_bytes(b"not-a-maxmind-database")
    provider = GeoIpProvider(str(path))
    assert provider.lookup("8.8.8.8") == GeoLocation()


def test_session_view_never_contains_raw_or_hashed_token() -> None:
    row = UserSession(expires_at=200, revoked_at=None, last_seen_at=100, token_hash="secret-hash")
    payload = view(row)
    assert "token" not in payload
    assert "token_hash" not in payload


def test_geoip_available_database_supports_ipv4_and_ipv6(tmp_path) -> None:
    path = tmp_path / "geo.mmdb"
    path.write_bytes(b"placeholder")
    provider = GeoIpProvider(str(path))

    class Reader:
        def get(self, address: str) -> dict:
            return {
                "country": {"names": {"en": "Australia"}},
                "subdivisions": [{"names": {"en": "Western Australia"}}],
                "city": {"names": {"en": "Perth"}},
                "location": {"latitude": -31.95, "longitude": 115.86},
            }

    provider._reader = Reader()
    provider._loaded_path = path
    assert provider.lookup("8.8.8.8").country == "Australia"
    assert provider.lookup("2001:4860:4860::8888").city == "Perth"


def test_geoip_country_and_network_databases_can_be_used_together(tmp_path) -> None:
    city = tmp_path / "city.mmdb"
    country = tmp_path / "country.mmdb"
    network = tmp_path / "network.mmdb"
    for path in (city, country, network):
        path.write_bytes(b"placeholder")
    provider = GeoIpProvider(str(city), str(country), str(network))

    class Reader:
        def __init__(self, value: dict) -> None:
            self.value = value

        def get(self, address: str) -> dict:
            return self.value

    provider._reader = Reader({})
    provider._loaded_path = city
    provider._country_reader = Reader({"country": {"names": {"en": "Australia"}}})
    provider._loaded_country_path = country
    provider._asn_reader = Reader(
        {"autonomous_system_number": 13335, "autonomous_system_organization": "Cloudflare"}
    )
    provider._loaded_asn_path = network

    location = provider.lookup("8.8.8.8")
    assert location.country == "Australia"
    assert location.network_number == 13335
    assert location.network_organization == "Cloudflare"


def test_geoip_reader_failure_returns_unavailable(tmp_path) -> None:
    path = tmp_path / "geo.mmdb"
    path.write_bytes(b"placeholder")
    provider = GeoIpProvider(str(path))

    class Reader:
        def get(self, address: str) -> dict:
            raise RuntimeError("provider failure")

    provider._reader = Reader()
    provider._loaded_path = path
    assert provider.lookup("8.8.8.8") == GeoLocation()


def test_create_session_persists_network_metadata(monkeypatch) -> None:
    from uuid import uuid4

    from starlette.requests import Request

    class FakeDb:
        def __init__(self) -> None:
            self.session = None

        async def scalar(self, _statement):
            return None

        def add(self, session) -> None:
            self.session = session

        async def flush(self) -> None:
            return None

    user = type("UserStub", (), {"id": uuid4()})()
    request = Request(
        {
            "type": "http",
            "headers": [
                (b"x-real-ip", b"8.8.8.8"),
                (b"user-agent", b"test-agent"),
            ],
            "client": ("127.0.0.1", 1234),
        }
    )
    monkeypatch.setattr(
        "src.core.session_manager.geoip.lookup",
        lambda _ip: GeoLocation(
            country="Australia",
            network_number=13335,
            network_organization="Cloudflare",
        ),
    )
    db = FakeDb()

    import asyncio

    asyncio.run(create_session(db, user, request))
    assert db.session is not None
    assert db.session.geo_network_number == 13335
    assert db.session.geo_network_organization == "Cloudflare"
