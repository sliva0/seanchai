"""What a codec needs beside the corpus's statements: each data type's basic
format and the names of the vendor ids the corpus uses."""

from __future__ import annotations

from dataclasses import dataclass

from ..dad import ast

# RFC 6733 section 4.3.1 derives these from a section 4.2 basic format;
# QoSFilterRule is RFC 3588 section 4.3's, dropped by RFC 6733 and still used
# by RFC 4005's AVPs. Every other type is basic.
_DERIVED = {
    ast.DataType.ADDRESS: ast.DataType.OCTET_STRING,
    ast.DataType.TIME: ast.DataType.OCTET_STRING,
    ast.DataType.UTF8_STRING: ast.DataType.OCTET_STRING,
    ast.DataType.DIAMETER_IDENTITY: ast.DataType.OCTET_STRING,
    ast.DataType.DIAMETER_URI: ast.DataType.OCTET_STRING,
    ast.DataType.ENUMERATED: ast.DataType.INTEGER32,
    ast.DataType.IP_FILTER_RULE: ast.DataType.OCTET_STRING,
    ast.DataType.QOS_FILTER_RULE: ast.DataType.OCTET_STRING,
}


def basic_type(data_type: ast.DataType) -> ast.DataType:
    """The RFC 6733 section 4.2 basic format `data_type` is carried in:
    itself for a basic one (`Unsigned32`, `Grouped`), else the format section
    4.3.1 derives it from (`OctetString` for `DiameterIdentity`, `Integer32`
    for `Enumerated`)."""
    return _DERIVED.get(data_type, data_type)


@dataclass(frozen=True)
class Vendor:
    """A vendor id the corpus places AVPs under, with the organisation it
    names and where that is stated."""

    vendor_id: int
    name: str
    source: str

    def to_dict(self) -> dict[str, int | str]:
        """The three fields, for `json.dumps`."""
        return {"vendor_id": self.vendor_id, "name": self.name, "source": self.source}


_PEN = "IANA Private Enterprise Numbers, https://www.iana.org/assignments/enterprise-numbers"

# Every vendor id a corpus file's `; Vendor-ID:` or an AVP header states. A
# non-zero Vendor-Id is an IANA Private Enterprise Number (RFC 6733 section
# 4.1); the documents state their own as well.
VENDORS: dict[int, Vendor] = {
    vendor.vendor_id: vendor
    for vendor in (
        Vendor(
            ast.IETF_VENDOR,
            "IETF",
            "RFC 6733 section 4.1: a Vendor-Id of 0 is an IETF-adopted AVP's",
        ),
        Vendor(5535, "3GPP2", f"{_PEN}; 3GPP2 X.S0057-0 clause 5.6.2.1.1"),
        Vendor(10415, "3GPP", f"{_PEN}; 3GPP TS 29.230 clause 6.1"),
        Vendor(13019, "ETSI", f"{_PEN}; ETSI ES 283 034 clause 6.6"),
        Vendor(45687, "oneM2M", f"{_PEN}; oneM2M TS-0004 clause A.4"),
    )
}
