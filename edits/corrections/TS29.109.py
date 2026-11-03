"""Corrections for 3GPP TS 29.109 — see docs/corrections.md."""

from seanchai.dad.corrections import Correction, definition, header

CORRECTIONS = [
    Correction(
        id="bases-cx",
        target=header(),
        field="bases",
        expect=("RFC6733",),
        replace=("RFC6733", "TS29.229"),
        reason="clause 6.3: 'The AVPs defined in 3GPP TS 29.229 [3] for 3GPP IMS Cx"
        " interface Multimedia-Auth-Request/Answer messages are used as they are',"
        " and table 6.1 lists none of them: clause 4.2's MAR and MAA use its"
        " Public-Identity and SIP-Auth-Data-Item",
        versions="18.1.0..19.0.0",
    ),
    Correction(
        id="bia-spelling",
        target=definition("Boostrapping-Info-Answer"),
        field="name",
        expect="Boostrapping-Info-Answer",
        replace="Bootstrapping-Info-Answer",
        reason="clause 5.2's rule drops the t; the sentence introducing it and the"
        " request's rule print Bootstrapping. TS 29.230 table 5.1/1 misspells both"
        " directions",
        versions="18.1.0..19.0.0",
    ),
]
