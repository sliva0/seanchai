"""Classifying the document's clauses in one pass (`_collect`), then the
cross-section work (`_resolve`): pairing each AVP table with its re-used
table and giving enumerated AVPs their codes; and the order of the blocks
in the file (`_assemble`)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ...dad import ast
from .. import sources
from ..errors import ExtractionError
from ._avp_tables import (
    _extract_avp_table,
    _extract_reused_table,
    _extract_vendor_table,
    _referred_type_sentences,
    _vendor_id_sentence,
)
from ._base import (
    TGPP_VENDOR,
    _avp_title,
    _Collected,
    _CollectedAvpTable,
    _ReusedTable,
    _Section,
)
from ._commands import (
    _COMMAND_TITLE_RE,
    _MESSAGE_TITLE_RE,
    _answer_messages,
    _extract_category_message,
    _extract_messages,
    _extract_table_message,
    _message_caption,
    _sibling_applications,
    _stated_applications,
    _table_message_row,
)
from ._enums import _ENUM_VALUE_RE, _extract_enumerated
from ._origins import _prose_avp_origins, _references
from ._registries import _REGISTRY_KINDS, _extract_registry
from ._rules import (
    _AVP_HEADER_RE,
    _DIAMETER_HEADER_RE,
    _extract_grouped,
    _find_rule_header,
)
from ._tables import _NAME_LABELS


@dataclass
class _Resolved:
    """Definitions after cross-section resolution: every enumerated AVP has a
    code and a vendor-id, and external AVPs have been dropped."""

    messages: list[ast.Message]
    # Document order, one entry per definition set: the AVP table and the
    # re-used block accompanying it (synthesised, with the AVP table's own
    # label and section, when the document prints no re-used table).
    pairs: list[tuple[ast.AvpTable, _ReusedTable]]
    definitions: list[ast.GroupedAvp | ast.EnumeratedAvp]
    independent_reused: list[_ReusedTable] = field(default_factory=list)
    # A block per clause whose prose states origins, and per AVP table whose
    # notes derive rows beside a printed re-used table: no printed table holds
    # them.
    derived_reused: list[_ReusedTable] = field(default_factory=list)
    applications: list[ast.ApplicationScope] = field(default_factory=list)
    registries: list[ast.Registry] = field(default_factory=list)


def _collect(
    sections: list[_Section],
    warnings: list[str],
    own_reference: str,
    quirks: sources.Quirks,
    publisher_vendor: int = TGPP_VENDOR,
) -> _Collected:
    """Walk the document once, classifying sections. Source-shaped work only:
    nothing here needs to know about another section."""
    collected = _Collected(own_reference=own_reference, vendor=publisher_vendor)
    references = (
        _references(sections)
        if quirks.enabled("refer-type-cells")
        or quirks.enabled("vendor-avp-tables")
        or quirks.enabled("registry-tables")
        or quirks.enabled("origins-by-reference")
        else {}
    )
    for section in sections:
        collected.answers.extend(_answer_messages(section, quirks, warnings))
        if quirks.enabled("prose-application-ids"):
            collected.applications.extend(_stated_applications(section, quirks))
        if title := _COMMAND_TITLE_RE.match(section.title):
            collected.messages.extend(
                _extract_messages(section, title, warnings, quirks, collected.commented)
            )
            continue
        if (
            quirks.enabled("message-headings")
            and (title := _MESSAGE_TITLE_RE.match(section.title))
            and any(
                "Diameter Header" in line.text and "::" in line.text
                for line in section.lines
            )
        ):
            # Only the clauses printing a rule: 6.4.6-6.4.13 point at RFC 6733.
            collected.messages.extend(
                _extract_messages(
                    section,
                    title,
                    warnings,
                    quirks,
                    collected.commented,
                    message_heading=True,
                )
            )
            continue
        if quirks.enabled("message-tables") and (
            title := _MESSAGE_TITLE_RE.match(section.title)
        ):
            printed = [
                (table, start)
                for table in section.tables
                if (start := _table_message_row(table)) is not None
            ]
            for table, start in printed:
                collected.messages.append(
                    _extract_table_message(
                        section,
                        table,
                        start,
                        title,
                        warnings,
                        quirks,
                        collected.commented,
                    )
                )
            if printed:
                continue
            # Named by a caption and no row prints its header: read, or failed
            # on, never passed over. 6.4.6-6.4.13 point at RFC 6733, and print
            # no such caption.
            if caption := _message_caption(section, title):
                table = next(
                    (
                        table
                        for table in section.tables
                        if table.rows[0].cells == ["AVP", "Category", "Description"]
                    ),
                    None,
                )
                if table is None:
                    raise ExtractionError(
                        f"{section.number}: {caption[0]!r} over no table a"
                        " `message-tables` reading knows"
                    )
                collected.messages.append(
                    _extract_category_message(
                        section,
                        table,
                        caption,
                        title,
                        quirks,
                        collected.commented,
                        f"{collected.own_reference}.toml",
                    )
                )
                continue
        if quirks.enabled("procedure-commands") and any(
            _DIAMETER_HEADER_RE.match(line.text) for line in section.lines
        ):
            collected.messages.extend(
                _extract_messages(
                    section,
                    None,
                    warnings,
                    quirks,
                    collected.commented,
                    reprints=collected.reprints,
                    glosses=collected.glosses,
                )
            )
            continue
        for table in section.tables:
            header = table.rows[0].cells
            if quirks.enabled("registry-tables") and header[0] in _REGISTRY_KINDS:
                collected.registries.append(
                    _extract_registry(
                        table, section.number, warnings, quirks, references
                    )
                )
                continue
            # Substring, not membership: 29.214 titles the column group
            # "AVP Flag rules (Note 1)".
            if any("AVP Flag rules" in cell for cell in header):
                # TS 29.330 table 6.3.1-1 is a template with no definitions.
                # Recognise only the full header followed entirely by blank cells.
                labels = next(
                    (
                        i
                        for i, row in enumerate(table.rows)
                        if row.cells[0] in _NAME_LABELS
                    ),
                    None,
                )
                if labels is not None and all(
                    not any(row.cells) for row in table.rows[labels + 1 :]
                ):
                    warnings.append(
                        f"{section.number}: AVP table {table.caption}"
                        " contains no definitions"
                    )
                    continue
                wildcards: list[tuple[int, str]] = []
                avp_table, note_reused = _extract_avp_table(
                    table,
                    section.number,
                    warnings,
                    quirks,
                    references,
                    own_reference,
                    wildcards,
                )
                if quirks.enabled("referred-type-sentences"):
                    avp_table = _referred_type_sentences(
                        avp_table, note_reused, sections, warnings, quirks
                    )
                if quirks.enabled("vendor-id-sentence"):
                    avp_table = _vendor_id_sentence(avp_table, section, quirks)
                if wildcards:
                    collected.table_notes.append((avp_table, wildcards))
                collected.avp_tables.append(
                    _CollectedAvpTable(
                        table=avp_table,
                        section=section.number,
                        note_reused=note_reused,
                    )
                )
            elif (
                header[0] == "AVP Name"
                and "Reference" in header
                and quirks.enabled("vendor-avp-tables")
            ):
                vendor = _extract_vendor_table(
                    table, section.number, warnings, quirks, references
                )
                if vendor.rows:
                    collected.vendor_reused.append(vendor)
            elif "Attribute Name" in header and "Reference" in header:
                # Keyed on Reference rather than on M-bit: TS 29.128, 29.173
                # and 29.336 print a re-used table with no M-bit column at all.
                if table.caption is None:
                    raise ExtractionError("re-used AVPs table without a caption")
                reused_rows, reused_columns = _extract_reused_table(
                    table, warnings, own_reference, quirks, references
                )
                collected.reused_tables.append(
                    _ReusedTable(
                        rows=reused_rows,
                        columns=reused_columns,
                        label=table.caption,
                        section=section.number,
                    )
                )
        if title := _avp_title(section.title, quirks):
            found = _find_rule_header(section, _AVP_HEADER_RE, quirks)
            if found is not None:
                header, body_start = found
                rule_name = header["name"]
                if " " in rule_name:
                    # Spaces-for-hyphens rule names (29.272 §7.3.196
                    # "Monitoring Event Report") are input-patched.
                    raise ExtractionError(
                        f"{section.number}: rule name {rule_name!r} contains spaces"
                    )
                if rule_name != title["name"]:
                    warnings.append(
                        f"{section.number}: heading name"
                        f" {title['name']!r} != rule name {rule_name!r},"
                        " using the rule name"
                    )
                collected.grouped.append(
                    _extract_grouped(
                        section,
                        header,
                        body_start,
                        rule_name,
                        quirks,
                        warnings,
                        collected.commented,
                    )
                )
            elif section.paragraphs and "type Enumerated" in section.paragraphs[0].text:
                collected.pending_enums.append((section, title["name"]))
    if quirks.enabled("prose-avp-origins"):
        _prose_avp_origins(collected, sections, quirks)
    collected.applications = _sibling_applications(collected.applications)
    return collected


def _resolve(
    collected: _Collected,
    quirks: sources.Quirks | None = None,
    warnings: list[str] | None = None,
) -> _Resolved:
    """Cross-section work: pair each AVP table with its re-used table, then
    turn pending enumerated sections into definitions using codes from the
    AVP tables."""
    quirks = quirks if quirks is not None else sources.Quirks([], None)
    warnings = warnings if warnings is not None else []
    if (
        collected.registries
        and not collected.avp_tables
        and not collected.messages
        and not collected.grouped
    ):
        # A registry allocates and defines nothing (TS 29.230): its tables
        # are the whole file.
        return _Resolved(
            messages=[], pairs=[], definitions=[], registries=collected.registries
        )
    if not collected.avp_tables:
        if (
            quirks.enabled("message-only")
            and collected.messages
            and not collected.grouped
            and all(
                name
                in {row.name for table in collected.reused_tables for row in table.rows}
                and not any(
                    _ENUM_VALUE_RE.fullmatch(p.text) for p in section.paragraphs
                )
                for section, name in collected.pending_enums
            )
        ):
            quirks.fire("message-only")
            return _Resolved(
                messages=collected.messages,
                pairs=[],
                definitions=[],
                independent_reused=[
                    *collected.reused_tables,
                    *collected.vendor_reused,
                ],
                applications=collected.applications,
            )
        raise ExtractionError("no AVP table found")
    # A document with several definition sets (29.336's S6m/S6n and S6t,
    # 29.338's S6c and S6d) prints one AVP table and one re-used table per
    # set, in the same document order — that adjacency is the only thing that
    # says which re-used block belongs to which set, so unequal counts leave
    # no defensible pairing and are rejected rather than guessed at. A single
    # AVP table without a re-used table stays legitimate: the re-used block is
    # synthesised for its NOTE-derived rows. So do several AVP tables with
    # no printed re-used table at all (TS 32.299's 7.1.0.1 and 7.2.0.1):
    # each synthesises its own, and there is nothing to mis-pair.
    independent = quirks.enabled("independent-avp-tables")
    if independent:
        quirks.fire("independent-avp-tables")
    if not independent and (
        len(collected.reused_tables) > len(collected.avp_tables)
        or (
            len(collected.avp_tables) > 1
            and collected.reused_tables
            and len(collected.reused_tables) != len(collected.avp_tables)
        )
    ):
        avp_sections = ", ".join(entry.section for entry in collected.avp_tables)
        reused_labels = ", ".join(str(table.label) for table in collected.reused_tables)
        raise ExtractionError(
            f"{len(collected.avp_tables)} AVP tables (sections {avp_sections}) with"
            f" {len(collected.reused_tables)} re-used tables"
            f" ({reused_labels or 'none'}): cannot pair them"
        )

    pairs = []
    derived = list(collected.prose_reused)
    for index, entry in enumerate(collected.avp_tables):
        # `AvpTable.table` is optional only for label-less RFC tables; this
        # extractor rejects a docx AVP table without a caption before here.
        assert entry.table.table is not None
        # The rows the AVP table's own notes and cells derive come from it, so
        # that is honestly where their block was found.
        noted = _ReusedTable(
            rows=entry.note_reused,
            columns=ast.REUSED_COLUMNS,
            label=entry.table.table,
            section=entry.section,
        )
        if not independent and index < len(collected.reused_tables):
            # A printed table holds its own rows only: TS 29.329's table 6.3/2
            # prints External-Identifier, and its AVP table's NOTE the four
            # RFC AVPs beside it.
            pairs.append((entry.table, collected.reused_tables[index]))
            if noted.rows:
                derived.append(noted)
        else:
            pairs.append((entry.table, noted))

    codes: dict[str, int | None] = {}
    for entry in collected.avp_tables:
        for row in entry.table.rows:
            if row.name in codes and codes[row.name] != row.code:
                raise ExtractionError(
                    f"AVP table code conflict for {row.name!r}:"
                    f" {codes[row.name]} vs {row.code}"
                )
            codes[row.name] = row.code
    # An enumerated section whose values live in another spec has nothing to
    # emit: DRMP says "is of type Enumerated" and then prints no values,
    # because RFC 7944 defines them. Skipping it drops no information.
    #
    # Note the deliberate asymmetry with grouped AVPs. TS 29.272 §7.3.40
    # re-prints TS 29.212's Allocation-Retention-Priority in full while listing
    # it as re-used, and nine of its clauses do this. Those definitions are
    # kept: the document printed a body, so the file records it. That an AVP is
    # both defined locally and listed as re-used is a real inconsistency in the
    # source, and reporting it is the linter's job — resolving it by deleting
    # what the specification says is not this layer's call to make.
    #
    # A row citing this document itself is no "elsewhere": TS 29.212's Gxx,
    # S9, Sd and St re-used tables (clauses 5a.4.0, 5b.4.0, 5c.4.1, E.6.4.1)
    # list Gx's AVPs as re-used from TS 29.212, and 29.061's SGmb table (20.5)
    # cites 29.061, while the clauses defining them are in the same document.
    reused_rows = [row for _, reused in pairs for row in reused.rows]
    reused_rows += [row for reused in derived for row in reused.rows]
    if independent:
        reused_rows += [row for table in collected.reused_tables for row in table.rows]
    reused_rows += [row for table in collected.vendor_reused for row in table.rows]
    external = {
        row.name for row in reused_rows if row.origin != collected.own_reference
    }
    local_enums = [
        (section, name)
        for section, name in collected.pending_enums
        if name not in external
    ]
    vendor_id = (
        _enum_vendor_id(collected.grouped, collected.vendor) if local_enums else None
    )
    # A table printing each row's vendor states the enumerated AVP's too,
    # 0 being the IETF space a definition spells as no vendor (oneM2M
    # TS-0004's Accounting-Record-Type, table A.4-1).
    row_vendors = {
        row.name: row.vendor_id
        for entry in collected.avp_tables
        for row in entry.table.rows
        if row.vendor_id is not None
    }

    enumerated = []
    for section, name in local_enums:
        code = codes.get(name)
        if code is None:
            raise ExtractionError(
                f"{section.number}: enumerated AVP {name!r}"
                " has no code in the AVP table"
            )
        vendor = row_vendors.get(name, vendor_id)
        enumerated.append(
            _extract_enumerated(section, name, code, vendor or None, quirks, warnings)
        )

    return _Resolved(
        messages=collected.messages,
        pairs=pairs,
        definitions=[*collected.grouped, *enumerated],
        independent_reused=[
            # A printed re-used table with no rows is no block, as when paired.
            *(table for table in collected.reused_tables if independent and table.rows),
            *collected.vendor_reused,
        ],
        applications=collected.applications,
        derived_reused=derived,
    )


def _enum_vendor_id(grouped: list[ast.GroupedAvp], publisher: int) -> int:
    """The vendor id shared by this spec's locally defined AVPs.

    Read off the grouped-AVP headers (3GPP: 10415), since enumerated-AVP
    sections never print it. With no grouped AVP (TS 29.109), it is the
    publisher's vendor space. Several distinct header values are an error.
    """
    vendors = sorted({avp.vendor_id for avp in grouped if avp.vendor_id is not None})
    if not vendors:
        return publisher
    if len(vendors) != 1:
        found = ", ".join(str(vendor) for vendor in vendors)
        raise ExtractionError(
            "cannot resolve the vendor id of this spec's enumerated AVPs:"
            f" its grouped-AVP headers give {found}"
        )
    return vendors[0]


def _assemble(
    resolved: _Resolved,
    reprints: Sequence[ast.ReprintedAvp] = (),
    value_tables: Sequence[ast.ValueTable] = (),
    answers: Sequence[ast.AnswerMessage] = (),
) -> tuple[ast.Section, ...]:
    """File order: applications, messages and answer messages in document
    order, what the document re-prints and registries, then each definition
    set's AVP table followed by its re-used table, then every definition, value
    table and block of derived re-used rows in document order, each of these
    after the definitions of its clause."""
    sections: list[ast.Section] = [
        *resolved.applications,
        *ast.in_document_order(resolved.messages, answers),
        *reprints,
        *resolved.registries,
    ]
    for avp_table, reused in resolved.pairs:
        sections.append(avp_table)
        if reused.rows:
            sections.append(
                ast.ReusedAvps(
                    table=reused.label,
                    source=ast.SourceRef(section=reused.section),
                    columns=reused.columns,
                    rows=tuple(reused.rows),
                )
            )
    for reused in resolved.independent_reused:
        sections.append(
            ast.ReusedAvps(
                table=reused.label,
                source=ast.SourceRef(section=reused.section),
                columns=reused.columns,
                rows=tuple(reused.rows),
            )
        )
    derived = [
        ast.ReusedAvps(
            table=reused.label,
            source=ast.SourceRef(section=reused.section),
            columns=reused.columns,
            rows=tuple(reused.rows),
        )
        for reused in resolved.derived_reused
    ]
    sections.extend(
        sorted(
            (*resolved.definitions, *value_tables, *derived),
            key=lambda definition: ast.section_sort_key(definition.source.section),
        )
    )
    return tuple(sections)
