"""Commands: the messages a command clause's rules define, under a
command heading, a message heading, a procedure step or none (the RFC
commands); a command printed as a table; RFC 6733's `<answer-message>`;
a rule re-printed from an RFC; and the application ids a clause's prose
states, scoped to their interface clauses."""

from __future__ import annotations

import re

from ...dad import abnf, ast, formatter
from .. import sources
from ..errors import ExtractionError
from ._base import _Commented, _Glosses, _Line, _Section, _Table
from ._rules import (
    _AVP_HEADER_RE,
    _DIAMETER_HEADER_RE,
    _abnf_body,
    _rule_text,
)

# TS 29.343 clauses 6.6.2-6.6.5 lower-case the keyword
# ("ProXimity-Action-Request (PXR) command"). TS 29.336 clauses 8.2.3 and 8.2.7
# and TS 29.128 clause 6.2.3 space the name's words ("NIDD Information Request
# (NIR) Command") over a rule hyphenating them; the rule's name wins, as it does
# over any heading.
_COMMAND_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z-]+(?: [A-Za-z-]+)*) \((?P<abbr>[A-Z]{2,5})\) [Cc]ommand$"
)
# TS 32.299 clauses 6.2.2-6.4.13: "Accounting-Request message",
# "Accounting-Answer (ACA) message"; oneM2M TS-0004 clauses A.2.1-A.2.2,
# "Accounting Request Command", once a patch joins the words; TS 32.299
# V11.20.0 capitalizes "Accounting-Request Message". Read behind
# `message-headings`.
_MESSAGE_TITLE_RE = re.compile(
    r"^(?P<name>[A-Za-z-]+)(?: \((?P<abbr>[A-Z]{2,5})\))? (?:[Mm]essage|Command)$"
)


_COMMAND_INTRO_RE = re.compile(
    r"^The (?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) command,"
)
# Behind `message-tables`: the caption naming the command a table prints, TS
# 32.299 V11.20.0 "Table 6.4.5: Re-Auth-Answer (RAA) Message Contents for Online
# Charging", and the table's header row, as the rule's right side prints it.
_MESSAGE_CAPTION_RE = re.compile(
    r"\b(?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) Message Contents\b"
)
_MESSAGE_ROW_RE = re.compile(r"^<\s*Diameter Header:\s*(?P<items>[0-9A-Z, ]+?)\s*>$")
# Behind `reprinted-avps`, the sentence saying a rule copies another document's:
# TS 29.109 clause 4.2, "The content of mandatory Vendor-Specific-Application-ID
# according IETF RFC 6733 [33] is:".
_REPRINT_INTRO_RE = re.compile(
    r"^The content of (?:mandatory )?[A-Za-z-]+ according IETF RFC ?(?P<rfc>\d+)"
    r" \[\d+\] is:$"
)
# Behind `procedure-commands`, a procedure step naming the command printed under
# it: TS 29.109 clause 4.2, "... in the format of Multimedia-Auth-Request (MAR)
# message.", and clause 5.2, "The NAF shall send a Bootstrapping-Info-Request
# message (BIR) to the BSF."
_STEP_INTRO_RES = (
    re.compile(r"(?P<name>[A-Za-z-]+) \((?P<abbr>[A-Z]{2,5})\) message\b"),
    re.compile(r"(?P<name>[A-Za-z-]+) message \((?P<abbr>[A-Z]{2,5})\)"),
)


# Behind `rfc-command-rules`, the RFCs' names of the commands a procedure clause
# prints by rule alone, keyed by command code and whether the R bit is set: RFC
# 6733 section 3.1 (Re-Auth, Accounting, Abort-Session, Session-Termination),
# RFC 7155 section 3 (AA) and RFC 4072 section 3 (Diameter-EAP). TS 29.234
# V11.2.0 clause 4.4.2.2 prints "ABNF for the ASR and ASA commands are as
# follows:" over `<ASR> ::=`, and 4.4.2.1 `<Diameter-EAP-Request> ::=` under
# "DER and DEA Commands".
_RFC_COMMANDS = {
    (258, True): ("Re-Auth-Request", "RAR"),
    (258, False): ("Re-Auth-Answer", "RAA"),
    (265, True): ("AA-Request", "AAR"),
    (265, False): ("AA-Answer", "AAA"),
    (268, True): ("Diameter-EAP-Request", "DER"),
    (268, False): ("Diameter-EAP-Answer", "DEA"),
    (271, True): ("Accounting-Request", "ACR"),
    (271, False): ("Accounting-Answer", "ACA"),
    (274, True): ("Abort-Session-Request", "ASR"),
    (274, False): ("Abort-Session-Answer", "ASA"),
    (275, True): ("Session-Termination-Request", "STR"),
    (275, False): ("Session-Termination-Answer", "STA"),
}


def _rfc_command(
    section: _Section, header: re.Match, quirks: sources.Quirks
) -> re.Match | None:
    """What an intro would say of a rule no intro names, read as a title.
    None without the quirk, and an error for a code no RFC here defines or a
    rule abbreviating the command otherwise."""
    if not quirks.enabled("rfc-command-rules"):
        return None
    try:
        code, flags, _ = abnf.diameter_header(header["items"])
    except abnf.AbnfError as error:
        raise ExtractionError(f"{section.number}: {error}") from None
    known = _RFC_COMMANDS.get((code, ast.CommandFlag.REQUEST in flags))
    rule = header["name"].replace(" ", "")
    if known is None or (rule.isupper() and rule != known[1]):
        raise ExtractionError(
            f"{section.number}: rule {rule!r} over command {code} is none of"
            " the RFC commands `rfc-command-rules` reads"
        )
    quirks.fire("rfc-command-rules")
    return _COMMAND_INTRO_RE.match(f"The {known[0]} ({known[1]}) command,")


def _procedure_intro(text: str) -> re.Match | None:
    """The command a procedure clause's line introduces, if it does."""
    if match := _COMMAND_INTRO_RE.match(text):
        return match
    return next(filter(None, (rule.search(text) for rule in _STEP_INTRO_RES)), None)


def _answer_messages(
    section: _Section, quirks: sources.Quirks, warnings: list[str]
) -> list[ast.AnswerMessage]:
    """RFC 6733 section 7.2's `<answer-message>`, the format an answer with the
    E bit set takes, as a document prints its own: TS 29.229 clause 7.3.1, "based
    on the RFC 3588, clause 7.2", for the Cx and Dx commands. Its heading names
    no command, so its rule line is what anchors it, and a line naming
    `<answer-message>` in any other shape fails rather than drop the block."""
    found = []
    lines = section.lines
    for index, line in enumerate(lines):
        if "answer-message" not in line.text or "::" not in line.text:
            continue
        if abnf.ANSWER_MESSAGE_RE.match(line.text) is None:
            raise ExtractionError(
                f"{section.number}: malformed answer-message rule {line.text!r}"
            )
        avps, _, struck = _abnf_body(
            lines, index + 1, "answer-message", section.number, quirks, warnings
        )
        if struck:
            raise ExtractionError(
                f"{section.number}: answer-message body comments out members,"
                " which no reading here keeps"
            )
        found.append(
            ast.AnswerMessage(source=ast.SourceRef(section=section.number), avps=avps)
        )
    return found


def _extract_messages(
    section: _Section,
    title: re.Match | None,
    warnings: list[str],
    quirks: sources.Quirks,
    commented: _Commented,
    message_heading: bool = False,
    reprints: list[ast.ReprintedAvp] | None = None,
    glosses: _Glosses | None = None,
) -> list[ast.Message]:
    """A command section usually holds one ABNF, but can hold several — the
    same command under different application ids (TS 29.272 defines IDR/DSR/RSR
    once for S6a and once for S7a in one section).

    With `message_heading`, `title` is a "Name message" heading whose rule
    is spelled with the abbreviation (`<ACR> ::=`, TS 32.299 clauses
    6.2.2-6.4.5): the long name comes from the heading, as the RFC extractor
    takes it for RFC 6733's `<CER> ::=`."""
    messages = []
    prose_title = title is None
    lines = section.lines
    index = 0
    while index < len(lines):
        text = _rule_text(lines[index].text, quirks)
        index += 1
        if prose_title and (intro := _procedure_intro(text)):
            title = intro
        if "::=" not in text:
            continue
        header = _DIAMETER_HEADER_RE.match(text)
        if header is None:
            if (
                prose_title
                and reprints is not None
                and glosses is not None
                and (rule := _AVP_HEADER_RE.match(text))
            ):
                index = _extract_reprint(
                    section, rule, lines, index, quirks, warnings, reprints, glosses
                )
                continue
            raise ExtractionError(f"{section.number}: malformed rule header {text!r}")
        if title is None:
            title = _rfc_command(section, header, quirks)
        if title is None:
            raise ExtractionError(
                f"{section.number}: command ABNF without a named intro"
            )
        if prose_title:
            quirks.fire("procedure-commands")
        rule_name = header["name"].replace(" ", "")
        if prose_title and rule_name == title["abbr"]:
            # `<ASR> ::=`, as RFC 6733 prints it: the long name is the title's.
            rule_name = title["name"]
        if message_heading:
            quirks.fire("message-headings")
            if not re.fullmatch(r"[A-Z]{2,5}", rule_name) or (
                title["abbr"] is not None and title["abbr"] != rule_name
            ):
                raise ExtractionError(
                    f"{section.number}: message heading {title['name']!r} over"
                    f" rule {rule_name!r}, which is not its abbreviation"
                )
            abbreviation = rule_name
            rule_name = title["name"]
        else:
            abbreviation = title["abbr"]
        if rule_name != title["name"]:
            # A real occurrence: TS 29.329 §6.1.8 heading says
            # "Push-Notifications-Answer", the rule "Push-Notification-Answer".
            # The rule name wins; the discrepancy is reported, not fatal.
            warnings.append(
                f"{section.number}: heading name {title['name']!r}"
                f" != rule name {rule_name!r}, using the rule name"
            )
        try:
            command_code, flags, application_id = abnf.diameter_header(header["items"])
        except abnf.AbnfError as error:
            raise ExtractionError(f"{section.number}: {error}") from None
        if application_id is None:
            warnings.append(
                f"{section.number}: {rule_name} header omits the application id"
            )
        avps, index, struck = _abnf_body(
            lines, index, rule_name, section.number, quirks, warnings
        )
        message = ast.Message(
            name=rule_name,
            abbreviation=abbreviation,
            source=ast.SourceRef(section=section.number),
            command_code=command_code,
            flags=flags,
            application_id=application_id,
            avps=avps,
        )
        messages.append(message)
        if struck:
            commented.append((message, struck))
        if prose_title:
            title = None
    if not messages:
        # TS 29.273 §§4.2.2.4.3-4, 5.2.2.3.5-6 and 11.2.2.1.1-2
        # contain only a pointer to another clause, not a definition.
        paragraphs = [p.text for p in section.paragraphs if p.text]
        if (
            quirks.enabled("command-reference-only")
            and len(paragraphs) == 1
            and re.fullmatch(
                r"(?:Refer to|See) clause \d+(?:\.\d+)+"
                # TS 29.273 V19.2.0 clause 11.2.2.1.1 drops the "3GPP".
                r"(?: of (?:3GPP )?TS \d{2}\.\d{3} \[\d+\])?\.?",
                paragraphs[0],
            )
        ):
            quirks.fire("command-reference-only")
            return []
        raise ExtractionError(f"{section.number}: command section without ABNF")
    return messages


def _extract_reprint(
    section: _Section,
    header: re.Match,
    lines: list[_Line],
    index: int,
    quirks: sources.Quirks,
    warnings: list[str],
    reprints: list[ast.ReprintedAvp],
    glosses: _Glosses,
) -> int:
    """A grouped rule printed in a procedure clause, under a sentence saying it
    copies another document's: TS 29.109 clauses 4.2, 5.2 and 5.4 print RFC
    6733's `<Vendor-Specific-Application-Id>` between their commands, glossing
    what its members hold there. No command and no definition, so a block of its
    own, its glosses kept. Returns the index after its body."""
    name = header["name"]
    if not quirks.enabled("reprinted-avps"):
        raise ExtractionError(
            f"{section.number}: grouped rule {name!r} printed in a procedure clause,"
            " which this document's source declaration does not read (the"
            " `reprinted-avps` quirk)"
        )
    intro = _REPRINT_INTRO_RE.match(lines[index - 2].text) if index > 1 else None
    if intro is None:
        raise ExtractionError(
            f"{section.number}: grouped rule {name!r} under no sentence saying what"
            " it copies"
        )
    quirks.fire("reprinted-avps")
    avps, end, _ = _abnf_body(lines, index, name, section.number, quirks, warnings)
    printed = [line.text for line in lines[index:end] if line.text]
    if len(printed) != len(avps):
        raise ExtractionError(
            f"{section.number}: {name}'s body is not one member a line, so its"
            " comments have no member to stay with"
        )
    reprint = ast.ReprintedAvp(
        name=name,
        source=ast.SourceRef(section=section.number),
        origin=f"RFC{intro['rfc']}",
        code=int(header["code"]),
        vendor_id=None if header["vendor"] is None else int(header["vendor"]),
        avps=avps,
    )
    reprints.append(reprint)
    for position, text in enumerate(printed):
        if gloss := text.partition(";")[2].strip():
            glosses.append((reprint, position, gloss))
    return end


def _extract_table_message(
    section: _Section,
    table: _Table,
    start: int,
    title: re.Match,
    warnings: list[str],
    quirks: sources.Quirks,
    commented: _Commented,
) -> ast.Message:
    """A command printed as a table of its rule's lines and whether 3GPP uses
    each: TS 32.299 V11.20.0 clause 6.4.5, the one such rule in the document,
    with `<Diameter Header: 258, PXY>` as its first row. Clause 6.4.1.2 reads
    a member not used as it reads a strike ("in grey in the tables"), so `No`
    is a struck line."""
    quirks.fire("message-tables")
    caption = _message_caption(section, title)
    if caption is None:
        raise ExtractionError(
            f"{section.number}: no caption abbreviates {title['name']!r}"
        )
    lines = []
    for row in table.rows[start + 1 :]:
        used = row.cells[-1].lower()
        if used not in ("yes", "no"):
            raise ExtractionError(
                f"{section.number}: {row.cells[0]!r} marked {row.cells[-1]!r},"
                " neither yes nor no"
            )
        lines.append(
            _Line(
                text=row.cells[0],
                style="",
                bold=frozenset(),
                struck=frozenset({used == "no"}),
            )
        )
    avps, end, struck = _abnf_body(
        lines, 0, title["name"], section.number, quirks, warnings
    )
    if end != len(lines):
        raise ExtractionError(
            f"{section.number}: table row {lines[end].text!r} is no ABNF member"
        )
    header = _MESSAGE_ROW_RE.match(table.rows[start].cells[0])
    assert header is not None
    try:
        command_code, flags, application_id = abnf.diameter_header(header["items"])
    except abnf.AbnfError as error:
        raise ExtractionError(f"{section.number}: {error}") from None
    message = ast.Message(
        name=title["name"],
        abbreviation=caption["abbr"],
        source=ast.SourceRef(section=section.number),
        command_code=command_code,
        flags=flags,
        application_id=application_id,
        avps=avps,
    )
    if struck:
        commented.append((message, struck))
    return message


# What a category table's row says of its member, TS 32.299 table 6.4.4 under
# clause 6.4.1.2's symbols: the dash is its "Not used in 3GPP".
_CATEGORY_PRESENCE = {
    "M": ast.Presence.REQUIRED,
    "OC": ast.Presence.OPTIONAL,
    "-": ast.Presence.OPTIONAL,
}


def _extract_category_message(
    section: _Section,
    table: _Table,
    caption: re.Match,
    title: re.Match,
    quirks: sources.Quirks,
    commented: _Commented,
    declarations: str,
) -> ast.Message:
    """A command printed as a table of its members' categories and no rule: TS
    32.299 V11.20.0 clause 6.4.4 prints RAR so, where V19.0.0 prints the rule.
    Clause 6.4.1.2's symbols make M `{ }` and OC `[ ]`; a dash, "Not used in 3GPP",
    reads as a strike; a row set off by a tab is the grouped AVP above its own,
    kept as a comment. No Diameter header is printed anywhere, so a line an input
    patch supplies states it, and the file says so, naming the `declarations`
    file whose patch says where the header comes from."""
    header = next(
        (
            match
            for line in section.lines
            if (match := _MESSAGE_ROW_RE.match(line.text))
        ),
        None,
    )
    if header is None:
        raise ExtractionError(
            f"{section.number}: table prints {title['name']} with no Diameter"
            " header; an input patch supplies one"
        )
    quirks.fire("message-tables")
    rules: list[ast.AvpRule] = []
    notes: list[tuple[int, ast.AvpRule]] = []
    for row in table.rows[1:]:
        name, category = row.cells[0], row.cells[1]
        presence = _CATEGORY_PRESENCE.get(category)
        if presence is None:
            raise ExtractionError(
                f"{section.number}: {name!r} has category {category!r}, none of M,"
                " OC or a dash"
            )
        struck = category == "-"
        if struck:
            if not quirks.enabled("struck-rules-unused"):
                raise ExtractionError(
                    f"{section.number}: {name!r} marked unused, which this"
                    " document's source declaration does not read (the"
                    " `struck-rules-unused` quirk)"
                )
            quirks.fire("struck-rules-unused")
        rule = ast.AvpRule(name=name, presence=presence, strikethrough=struck)
        if struck or row.indented:
            notes.append((len(rules), rule))
        else:
            rules.append(rule)
    try:
        command_code, flags, application_id = abnf.diameter_header(header["items"])
    except abnf.AbnfError as error:
        raise ExtractionError(f"{section.number}: {error}") from None
    message = ast.Message(
        name=title["name"],
        abbreviation=caption["abbr"],
        source=ast.SourceRef(section=section.number),
        command_code=command_code,
        flags=flags,
        application_id=application_id,
        avps=tuple(rules),
    )
    members = [*rules, *(rule for _, rule in notes)]
    commented.append(
        (
            message,
            [
                (
                    0,
                    f"patched: the table prints no Diameter header, see {declarations}",
                ),
                *(
                    (position, formatter.commented_avp_rule(rule, members))
                    for position, rule in notes
                ),
            ],
        )
    )
    return message


def _message_caption(section: _Section, title: re.Match) -> re.Match | None:
    """The caption naming the command a clause prints as a table."""
    return next(
        (
            match
            for paragraph in section.paragraphs
            if (match := _MESSAGE_CAPTION_RE.search(paragraph.text))
            and match["name"] == title["name"]
        ),
        None,
    )


def _table_message_row(table: _Table) -> int | None:
    """The row printing a table's command header, if one does."""
    return next(
        (
            index
            for index, row in enumerate(table.rows)
            if _MESSAGE_ROW_RE.match(row.cells[0])
        ),
        None,
    )


# Behind `prose-application-ids`: a 3GPP document stating the application id
# its command headers omit. The first two wordings are each used by several
# documents; the retired documents have wordings of their own.
_APPLICATION_ID_RES = (
    # TS 29.212 clause 5.1, and 29.154, 29.214, 29.215, 29.217 likewise:
    # "... and the Application-ID for the Gx Application in the present
    # release is 16777238." 29.212's Sd and St (5b.1, 5c.1) open a sentence
    # with it and drop "in the present release".
    re.compile(
        r"[Tt]he Application-ID for the (?P<name>\S+) [Aa]pplication"
        r"(?: in the present release)? is (?P<id>\d+)\b"
    ),
    # TS 29.219 clause 5.1.5, and 29.343, 29.368, 29.468 likewise: "The
    # Diameter application identifier assigned to the Sy interface
    # application is 16777302."
    re.compile(
        r"^The Diameter application identifier assigned to the (?P<name>\S+)"
        r" interface application(?: in the present release)? is (?P<id>\d+)\."
    ),
    # TS 29.209 V6.8.0 clause 6.1: "The Gq application is defined as an IETF
    # vendor specific Diameter application with application ID 16777222".
    re.compile(
        r"^The (?P<name>\S+) application is defined as an IETF vendor specific"
        r" Diameter application with application ID (?P<id>\d+)\b"
    ),
    # TS 29.210 V6.7.0 clauses 6.1 and 6.2: "The Auth-Application-Id for the
    # Gx over Gy Application is 16777225 as allocated by IANA."; TS 29.211
    # V6.4.0 clause 7.1: "The Application Identifier for the Rx application is
    # 16777229 as allocated by IANA."
    re.compile(
        r"The (?:Auth-Application-Id|Application Identifier) for the"
        r" (?P<name>.+?) [Aa]pplication is (?P<id>\d+) as allocated by IANA"
    ),
    # TS 29.061 clauses 17 and 20.1: "The Gmb application is defined as an IETF
    # vendor specific Diameter application, where the vendor is 3GPP. ... The
    # Gmb application identifier value assigned by IANA is 16777223."
    re.compile(
        r"^The (?P<name>\S+) application is defined as an IETF vendor specific"
        r" Diameter application,.* application identifier value assigned by IANA"
        r" is (?P<id>\d+)\."
    ),
    # TS 29.234 V11.2.0 clauses 6.2 and 11.2: "The Wx reference point shall be
    # Diameter based and shall have an application ID defined for it. ... The
    # application identifier is to 16777219."
    re.compile(
        r"^The (?P<name>\S+) [Rr]eference [Pp]oint shall be Diameter based and"
        r" shall have an application ID defined for it\..*"
        r"The application identifier is to (?P<id>\d+)\."
    ),
)


def _stated_applications(
    section: _Section, quirks: sources.Quirks
) -> list[ast.ApplicationScope]:
    """The applications a clause states the ids of, each applying to the
    interface clause the statement sits in: Gx's clause 5.1 speaks for the
    commands of clause 5 (`5.*`), S9a's A.7.1 for those of A.7 (`A.7.*`)."""
    found = []
    for paragraph in section.paragraphs:
        for pattern in _APPLICATION_ID_RES:
            if match := pattern.search(paragraph.text):
                quirks.fire("prose-application-ids")
                found.append(
                    ast.ApplicationScope(
                        name=match["name"],
                        source=ast.SourceRef(section=section.number),
                        application_id=int(match["id"]),
                        applies_to=(f"{ast.interface_clause(section.number)}.*",),
                    )
                )
    return found


def _sibling_applications(
    applications: list[ast.ApplicationScope],
) -> list[ast.ApplicationScope]:
    """Each stated application, scoped to its own clause where another states
    a different one under the same interface clause: TS 29.210 V6.7.0's clause
    6.1 states Gx's id and 6.2 Gx over Gy's, so neither speaks for clause 6,
    and each for the commands of its own. Alone under its interface clause, a
    statement speaks for all of it: TS 29.212 clause 5.1's Gx id is that of the
    commands of 5.6. A statement at the shared clause itself, beside another's,
    could speak for either, and fails."""
    by_interface: dict[str, list[ast.ApplicationScope]] = {}
    for application in applications:
        interface = ast.interface_clause(application.source.section)
        by_interface.setdefault(interface, []).append(application)
    scoped = []
    for application in applications:
        interface = ast.interface_clause(application.source.section)
        stated = by_interface[interface]
        if len({(each.name, each.application_id) for each in stated}) == 1:
            scoped.append(application)
            continue
        if any(each.source.section == interface for each in stated):
            raise ExtractionError(
                f"{interface}: {', '.join(each.name for each in stated)} are"
                " stated under one interface clause, one of them at the clause"
                " itself, so which commands each is for is ambiguous"
            )
        scoped.append(
            application.model_copy(
                update={"applies_to": (f"{application.source.section}.*",)}
            )
        )
    return scoped
