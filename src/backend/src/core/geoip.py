"""Optional local GeoIP lookup support for session metadata."""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from pathlib import Path

from src.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GeoLocation:
    """Approximate location returned by the configured GeoIP database."""

    country: str | None = None
    region: str | None = None
    city: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    network_type: str | None = None
    network_label: str | None = None
    network_number: int | None = None
    network_organization: str | None = None

    @property
    def label(self) -> str | None:
        """Return a human-readable approximate location."""
        return ", ".join(part for part in (self.city, self.region, self.country) if part) or None


class GeoIpProvider:
    """Read a local MaxMind-compatible database without network access."""

    def __init__(
        self, path: str | None = None, country_path: str | None = None, asn_path: str | None = None
    ) -> None:
        self.path = Path(path or settings.GEOIP_DATABASE_PATH)
        self.country_path = Path(country_path or settings.GEOIP_COUNTRY_DATABASE_PATH)
        self.asn_path = Path(asn_path or settings.GEOIP_ASN_DATABASE_PATH)
        self._reader = None
        self._loaded_path: Path | None = None
        self._country_reader = None
        self._loaded_country_path: Path | None = None
        self._asn_reader = None
        self._loaded_asn_path: Path | None = None

    def availability(self) -> dict[str, bool]:
        """Report usable database kinds without exposing filesystem paths or readers."""
        return {
            "city": self._get_reader() is not None,
            "country": self._get_country_reader() is not None,
            "network": self._get_asn_reader() is not None,
        }

    @staticmethod
    def _open(path: Path):
        if not path.is_file():
            return None
        try:
            import maxminddb

            return maxminddb.open_database(str(path))
        except Exception:
            logger.warning("GeoIP database is unavailable or invalid: %s", path, exc_info=True)
            return None

    def _get_reader(self):
        if self._reader is not None and self._loaded_path == self.path:
            return self._reader
        self._reader = self._open(self.path)
        self._loaded_path = self.path if self._reader is not None else None
        return self._reader

    def _get_country_reader(self):
        if self._country_reader is not None and self._loaded_country_path == self.country_path:
            return self._country_reader
        self._country_reader = self._open(self.country_path)
        self._loaded_country_path = self.country_path if self._country_reader is not None else None
        return self._country_reader

    def _get_asn_reader(self):
        if self._asn_reader is not None and self._loaded_asn_path == self.asn_path:
            return self._asn_reader
        self._asn_reader = self._open(self.asn_path)
        self._loaded_asn_path = self.asn_path if self._asn_reader is not None else None
        return self._asn_reader

    def reset(self) -> None:
        self._reader = None
        self._loaded_path = None
        self._country_reader = None
        self._loaded_country_path = None
        self._asn_reader = None
        self._loaded_asn_path = None

    @staticmethod
    def _name(record, key: str) -> str | None:
        value = record.get(key) if isinstance(record, dict) else None
        names = value.get("names") if isinstance(value, dict) else None
        return names.get("en") if isinstance(names, dict) else None

    @staticmethod
    def _classify_special_network(
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
    ) -> tuple[str, str] | None:
        if address.is_loopback:
            return ("loopback", "Loopback address")
        if address.version == 4:
            if address in ipaddress.ip_network("100.64.0.0/10"):
                return ("cgnat", "CGNAT / RFC 6598 shared address")
            if address in ipaddress.ip_network("10.0.0.0/8"):
                return ("rfc1918", "RFC 1918 private address (10.0.0.0/8)")
            if address in ipaddress.ip_network("172.16.0.0/12"):
                return ("rfc1918", "RFC 1918 private address (172.16.0.0/12)")
            if address in ipaddress.ip_network("192.168.0.0/16"):
                return ("rfc1918", "RFC 1918 private address (192.168.0.0/16)")
        else:
            if address in ipaddress.ip_network("fc00::/7"):
                return ("ula", "IPv6 unique-local address (RFC 4193)")
            if address in ipaddress.ip_network("fe80::/10"):
                return ("link_local", "IPv6 link-local address")
        if address.is_link_local:
            return ("link_local", "Link-local address")
        if address.is_private:
            return ("private", "Private/local address")
        return None

    def lookup(self, ip: str | None) -> GeoLocation:
        """Return approximate location, or an empty value on any lookup failure."""
        if not ip:
            return GeoLocation()
        try:
            address = ipaddress.ip_address(ip.strip())
            network = self._classify_special_network(address)
            if network is not None:
                return GeoLocation(network_type=network[0], network_label=network[1])
            data = {}
            reader = self._get_reader()
            if reader is not None:
                value = reader.get(str(address))
                if isinstance(value, dict):
                    data = value
            if not data:
                reader = self._get_country_reader()
                if reader is not None:
                    value = reader.get(str(address))
                    if isinstance(value, dict):
                        data = value
            country = self._name(data, "country")
            subdivisions = data.get("subdivisions") or []
            region = self._name(subdivisions[0], "region") if subdivisions else None
            city = self._name(data, "city")
            location = data.get("location") or {}
            latitude, longitude = location.get("latitude"), location.get("longitude")
            if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
                latitude = longitude = None
            network_number = None
            network_organization = None
            reader = self._get_asn_reader()
            if reader is not None:
                value = reader.get(str(address))
                if isinstance(value, dict):
                    raw_number = value.get("autonomous_system_number")
                    network_number = raw_number if isinstance(raw_number, int) else None
                    raw_org = value.get("autonomous_system_organization")
                    network_organization = raw_org if isinstance(raw_org, str) else None
            return GeoLocation(
                country,
                region,
                city,
                latitude,
                longitude,
                network_number=network_number,
                network_organization=network_organization,
            )
        except Exception:
            logger.warning("GeoIP lookup failed", exc_info=True)
            return GeoLocation()


geoip = GeoIpProvider()
