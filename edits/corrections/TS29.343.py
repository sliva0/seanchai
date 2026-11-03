"""Corrections for 3GPP TS 29.343 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, avp_rule, definition, reused_row

# The three grouped-AVP clauses print `<AVP header:nnn>` with no vendor-id
# while table 6.4.1-1 marks the V flag mandatory for each, the TS 29.214 case.
_VENDORLESS = [
    ("Monitor-Target", "6.4.9"),
    ("ProSe-Code-Suffix-Mask", "6.4.10"),
    ("Banned-User-Target", "6.4.17"),
]

CORRECTIONS = [
    Correction(
        id=f"vendor-id-{name.lower()}",
        target=definition(name, section=section),
        field="vendor_id",
        expect=None,
        replace=10415,
        reason=f"clause {section}'s AVP header omits the vendor-id; table"
        " 6.4.1-1 marks the V flag mandatory for it, as for every other AVP"
        " the specification defines",
        versions="18.0.0..19.0.0",
    )
    for name, section in _VENDORLESS
] + [
    Correction(
        id="pxr-allowed-suffixes-number-spelling",
        target=avp_rule("PX-Request", "Allowed-Suffix-Number"),
        field="name",
        expect="Allowed-Suffix-Number",
        replace="Allowed-Suffixes-Number",
        reason="the PXR ABNF (clause 6.6.2) drops the plural; clause 6.4.8 and"
        " table 6.4.1-1 define Allowed-Suffixes-Number (code 3606)",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="prose-app-code-suffix-range-row-name",
        target=reused_row("ProSe-Application-Code-Suffix-Range"),
        field="name",
        expect="ProSe-Application-Code-Suffix-Range",
        replace="ProSe-App-Code-Suffix-Range",
        reason="table 6.5.1-1 cites TS 29.345 for the AVP, which defines it as"
        " ProSe-App-Code-Suffix-Range (clause 6.3.82, code 3867)",
        versions="18.0.0..19.0.0",
    ),
    Correction(
        id="pxa-prose-app-code-suffix-range-name",
        target=avp_rule("PX-Answer", "ProSe-Application-Code-Suffix-Range"),
        field="name",
        expect="ProSe-Application-Code-Suffix-Range",
        replace="ProSe-App-Code-Suffix-Range",
        reason="the PXA ABNF (clause 6.6.3) uses table 6.5.1-1's spelling;"
        " TS 29.345 clause 6.3.82 defines the AVP as ProSe-App-Code-Suffix-Range",
        versions="18.0.0..19.0.0",
    ),
]
