"""Corrections for RFC 4590 — see docs/corrections.md.

A stand-in typing RADIUS attributes for Diameter. RFC 4590 is a RADIUS
document: its section 3 assigns each attribute a RADIUS Type, which Diameter
takes as the AVP code, and a "Text" value, but no Diameter data type or flag
rule. RFC 4740 imports the nineteen Digest attributes (clause 9.5.6) and
SIP-AOR (clause 9.8) by name, and its tables 2 and 3, which type and flag
its new AVPs, list none of them. So these declarations give the table a Type
column and the four flag-rule columns, and every row a type and flag rules,
from outside the document: UTF8String for RFC 4590's "Text", as TS 29.229
types the four it re-uses and Wireshark's dictionary all twenty; and the flag
rules that dictionary states, no document stating any.
"""

from seanchai.dad import ast
from seanchai.dad.corrections import Correction, avp_table, flag_rules, table_row

# Each attribute with its RFC 4590 section 3 clause, and the TS 29.229 clause
# typing it where TS 29.229 re-uses it.
_ATTRIBUTES = {
    "Digest-Response": ("3.1", None),
    "Digest-Realm": ("3.2", "6.3.37"),
    "Digest-Nonce": ("3.3", None),
    "Digest-Response-Auth": ("3.4", None),
    "Digest-Nextnonce": ("3.5", None),
    "Digest-Method": ("3.6", None),
    "Digest-URI": ("3.7", None),
    "Digest-Qop": ("3.8", "6.3.40"),
    "Digest-Algorithm": ("3.9", "6.3.39"),
    "Digest-Entity-Body-Hash": ("3.10", None),
    "Digest-CNonce": ("3.11", None),
    "Digest-Nonce-Count": ("3.12", None),
    "Digest-Username": ("3.13", None),
    "Digest-Opaque": ("3.14", None),
    "Digest-Auth-Param": ("3.15", None),
    "Digest-AKA-Auts": ("3.16", None),
    "Digest-Domain": ("3.17", None),
    "Digest-Stale": ("3.18", None),
    "Digest-HA1": ("3.19", "6.3.41"),
    "SIP-AOR": ("3.20", None),
}

_WIRESHARK = "Wireshark's dictionary.xml (codes 103-122)"
_FLAGS_REASON = (
    "RFC 4740 imports the attribute without a flag rule (its table 3 lists"
    f" only the AVPs it defines) and RFC 4590 states none; {_WIRESHARK} gives"
    " mandatory='may' and, by its DTD's defaults, protected 'may' and"
    " vendor-bit 'mustnot'"
)

CORRECTIONS = [
    Correction(
        id="diameter-columns",
        target=avp_table(None),
        field="columns",
        expect=(ast.AvpColumn.NAME, ast.AvpColumn.CODE, ast.AvpColumn.SECTION),
        replace=(
            ast.AvpColumn.NAME,
            ast.AvpColumn.CODE,
            ast.AvpColumn.SECTION,
            ast.AvpColumn.TYPE,
            ast.AvpColumn.MUST,
            ast.AvpColumn.MAY,
            ast.AvpColumn.SHOULD_NOT,
            ast.AvpColumn.MUST_NOT,
        ),
        reason=(
            "a stand-in typing RADIUS attributes for Diameter: RFC 4590 section"
            " 3 gives each attribute a RADIUS Type, its AVP code, and no Diameter"
            " type or flag rule, and RFC 4740, which imports the attributes as"
            " AVPs (clauses 9.5.6, 9.8), types and flags none of them; the"
            " columns hold what the rows' corrections supply"
        ),
    ),
]
for _name, (_clause, _tgpp) in _ATTRIBUTES.items():
    _slug = _name.lower()
    CORRECTIONS += [
        Correction(
            id=f"{_slug}-type",
            target=table_row(_name),
            field="data_type",
            expect=None,
            replace=ast.DataType.UTF8_STRING,
            reason=(
                f"RFC 4590 clause {_clause} gives the attribute a 'Text' value,"
                " which RADIUS encodes as UTF-8 (RFC 2865 clause 5);"
                + (
                    f" TS 29.229 clause {_tgpp}, re-using it, types it UTF8String;"
                    if _tgpp is not None
                    else ""
                )
                + f" {_WIRESHARK} types it UTF8String"
            ),
        ),
        Correction(
            id=f"{_slug}-may",
            target=flag_rules(table_row(_name)),
            field="may",
            expect=frozenset(),
            replace=frozenset({ast.AvpFlag.MANDATORY, ast.AvpFlag.PROTECTED}),
            reason=_FLAGS_REASON,
        ),
        Correction(
            id=f"{_slug}-must-not",
            target=flag_rules(table_row(_name)),
            field="must_not",
            expect=frozenset(),
            replace=frozenset({ast.AvpFlag.VENDOR}),
            reason=_FLAGS_REASON
            + "; RFC 6733 clause 4.1.1 clears V for an AVP of no vendor,"
            " and RFC 4590's attributes are IETF space",
        ),
    ]
