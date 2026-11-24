"""Information-element tables against the commands they describe: which
command a table names, the AVPs its rows map, and where a row's category
and the command's ABNF disagree."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ..dad import ast
from ._findings import Finding, Severity
from ._index import _Index

# The rules this module reports; with a corpus, its bases' commands answer
# too, and these replace the single-file findings.
ELEMENT_RULES = frozenset(
    {
        "elements-unattached",
        "elements-command-unknown",
        "elements-command-ambiguous",
        "element-unmapped",
        "element-not-in-command",
        "element-required-in-abnf",
        "element-optional-in-abnf",
    }
)


def _label(block: ast.InformationElements) -> str:
    return block.table or f"(clause {block.source.section})"


def _application_id(spec: ast.Specification, message: ast.Message) -> int | None:
    """The id on the wire: the header's, or the scope covering its clause."""
    if message.application_id is not None:
        return message.application_id
    for section in spec.sections:
        if isinstance(section, ast.ApplicationScope) and section.covers(
            message.source.section
        ):
            return section.application_id
    return None


def _grouped(specs: Sequence[ast.Specification], name: str) -> ast.GroupedAvp | None:
    """The first grouped definition of `name` in `specs`."""
    for spec in specs:
        for section in spec.sections:
            if (
                isinstance(section, ast.GroupedAvp)
                and section.defines
                and section.name == name
            ):
                return section
    return None


def _required(rule: ast.AvpRule) -> bool:
    return rule.presence is not ast.Presence.OPTIONAL and rule.min_occurs >= 1


def _elements(
    spec: ast.Specification,
    index: _Index,
    cited: Callable[[str], ast.Specification | None] | None,
) -> list[Finding]:
    """Check each information-element table against its command, found in
    the file, else in the document its `; From:` names, else in its bases,
    as the model finds it; `cited` resolves a document the file cites.

    `elements-unattached` (note): the table names no command.
    `elements-command-unknown` (error): neither the file nor, with a corpus,
    the documents it cites for the command print it.
    `elements-command-ambiguous` (error): the file prints it under several
    applications and the table names none, or more than once under the one
    application and the table names no clause (`; Command-Section:`). A
    clause at which the printing document has no such command is
    `elements-command-unknown`.
    `element-unmapped` (note): a row's mapping cell names no AVP.
    `element-not-in-command` (note): a row maps an AVP the command's body,
    or the grouped AVP's the table describes, does not hold.
    `element-required-in-abnf` (note): the body requires the AVP ({ } or
    < >) where the row's category is O or C. `element-optional-in-abnf`
    (note): the body makes it optional ([ ]) where the category is M. A row
    offering one of several AVPs ("Result-Code / Experimental-Result") says
    nothing of each, so is not compared.

    Without `cited` (a single file), a table whose command the file does not
    print is not judged."""
    findings = []
    for block in (s for s in spec.sections if isinstance(s, ast.InformationElements)):
        label = _label(block)
        path = index.path(block)
        for position, row in enumerate(block.rows):
            if row.printed is not None:
                findings.append(
                    Finding(
                        Severity.NOTE,
                        "element-unmapped",
                        f"table {label} maps {row.name!r} to {row.printed!r},"
                        " which names no AVP",
                        block.source.section,
                        paths=((*path, "rows", position),),
                    )
                )
        if block.command is None:
            findings.append(
                Finding(
                    Severity.NOTE,
                    "elements-unattached",
                    f"table {label} names no command; a correction names the one"
                    " it describes",
                    block.source.section,
                    paths=(path,),
                )
            )
            continue
        found = _command(spec, block)
        printing = spec
        searched = [spec]
        unread = cited is None
        if not found and cited is not None:
            origin = [] if block.origin is None else [block.origin]
            for reference in (*origin, *spec.bases):
                document = cited(reference)
                if document is None:
                    unread = True
                    continue
                searched.append(document)
                if found := _command(document, block):
                    printing = document
                    break
        if not found:
            if not unread:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "elements-command-unknown",
                        f"table {label} describes {block.command}, which neither"
                        " the file nor its bases print",
                        block.source.section,
                        paths=(path,),
                    )
                )
            continue
        where = "the file" if printing is spec else printing.specification
        if block.command_section is not None:
            clauses = ", ".join(message.source.section for message in found)
            found = [
                message
                for message in found
                if message.source.section == block.command_section
            ]
            if not found:
                findings.append(
                    Finding(
                        Severity.ERROR,
                        "elements-command-unknown",
                        f"table {label} describes {block.command} at clause"
                        f" {block.command_section}, which {where} prints at"
                        f" {_clauses(clauses)} only",
                        block.source.section,
                        paths=(path,),
                    )
                )
                continue
        ids = sorted({_application_id(printing, message) or 0 for message in found})
        if len(ids) > 1:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "elements-command-ambiguous",
                    f"table {label} describes {block.command}, which"
                    f" {where} prints under applications"
                    f" {', '.join(map(str, ids))}; a correction names the"
                    " application",
                    block.source.section,
                    paths=(path,),
                )
            )
            continue
        if len(found) > 1:
            findings.append(
                Finding(
                    Severity.ERROR,
                    "elements-command-ambiguous",
                    f"table {label} describes {block.command}, which {where}"
                    f" prints at clauses"
                    f" {', '.join(message.source.section for message in found)}"
                    f" under application {ids[0]}; a correction names the clause",
                    block.source.section,
                    paths=(path,),
                )
            )
            continue
        message = found[0]
        if block.avp is not None:
            grouped = _grouped(searched, block.avp)
            if grouped is None:
                continue
            body, holder = grouped.avps, f"{block.avp}'s body (clause"
            holder += f" {grouped.source.section})"
        else:
            body = message.avps
            holder = f"{message.abbreviation}'s ABNF (clause {message.source.section})"
        rules = {rule.name: rule for rule in reversed(body)}
        for position, row in enumerate(block.rows):
            if row.either:
                continue
            at = ((*path, "rows", position),)
            for name in row.avps:
                rule = rules.get(name)
                if rule is None:
                    findings.append(
                        Finding(
                            Severity.NOTE,
                            "element-not-in-command",
                            f"table {label} maps {row.name!r} to {name}, which"
                            f" {holder} does not hold",
                            block.source.section,
                            paths=at,
                        )
                    )
                elif (
                    _required(rule)
                    and row.category is not None
                    and row.category is not ast.Category.MANDATORY
                ):
                    findings.append(
                        Finding(
                            Severity.NOTE,
                            "element-required-in-abnf",
                            f"{name} is required in {holder}, but table {label}"
                            f" gives {row.name!r} category {row.category.value}",
                            block.source.section,
                            paths=at,
                        )
                    )
                elif not _required(rule) and row.category is ast.Category.MANDATORY:
                    findings.append(
                        Finding(
                            Severity.NOTE,
                            "element-optional-in-abnf",
                            f"{name} is optional in {holder}, but table {label}"
                            f" gives {row.name!r} category M",
                            block.source.section,
                            paths=at,
                        )
                    )
    return findings


def _clauses(clauses: str) -> str:
    return f"clause{'s' if ',' in clauses else ''} {clauses}"


def _command(
    spec: ast.Specification, block: ast.InformationElements
) -> list[ast.Message]:
    """`spec`'s commands named as `block`'s, of its application where it
    names one."""
    return [
        section
        for section in spec.sections
        if isinstance(section, ast.Message)
        and block.command is not None
        and section.name.casefold() == block.command.casefold()
        and block.application_id in (None, _application_id(spec, section))
    ]
