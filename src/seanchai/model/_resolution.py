"""How a name resolves: `_Resolver`, `Model`'s base, which indexes the corpus
per copy and reads a name through the resolution order (the package
docstring), from the local definition to an `Undefined AVP` block, filling,
overlaying flag rules and reading grouped bodies through the citing
document."""

from __future__ import annotations

import difflib
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path

from .. import corpus, oracle
from ..corpus import Missing
from ..dad import ast
from ._draft import _Draft
from ._errors import ModelError
from ._flags import _overlay, _stated
from ._types import (
    Alias,
    Avp,
    Enumerated,
    Grouped,
    Hole,
    Member,
    Placeholder,
    Supplied,
    SupplyKey,
    Undefined,
    UndefinedPolicy,
    _identity,
    is_cut,
)
from ._view import _folded, _View

# Marks a resolution stack entry as an `Alias` being followed, beside the
# `(path, name)` entries of the names being resolved.
_ALIASED = object()


class _Resolver:
    """The corpus indexed per copy, and every name resolved in it, by the
    order the package docstring states: the machinery `Model` answers its
    queries from, and the state `Model.build` sets up."""

    def _index(
        self,
        books: corpus.Corpus,
        wireshark: oracle.Oracle | None,
        undefined: UndefinedPolicy,
        supply: Mapping[SupplyKey, Supplied | Alias] | None,
    ) -> None:
        self._books = books
        self._wireshark = wireshark
        self._policy = undefined
        self._supply: dict[SupplyKey, Supplied | Alias] = dict(supply or {})
        self._known: dict[tuple[str, str], corpus.KnownHole] = {
            (entry.document, entry.name): entry
            for entry in (() if books.record is None else books.record.holes)
        }
        # Supplied readings, by the copy declaring the name, built once.
        self._supplied: dict[tuple[Path, str], Avp] = {}
        # One view per copy, and per reference the newest, which every
        # reference-level query answers from: the corpus sorts candidates
        # newest first. An older copy (TS 32.299 V11.20.0) is read only
        # where a citation resolves to it (`corpus.Corpus.resolution`).
        self._copies: dict[Path, _View] = {
            entry.path: _View.index(entry) for entry in books
        }
        self._views: dict[str, _View] = {
            entry.reference: self._copies[entry.path] for entry in books.newest()
        }
        self._spellings = {_folded(each): each for each in self._views}
        # Memo of resolved readings, keyed by the copy that reads the name.
        self._resolved: dict[tuple[Path, str], _Draft | None] = {}
        # The identity each reading still being resolved has settled, which
        # `_through` compares a cut member against: a key is resolved once,
        # so an entry is read only while its key is on the stack.
        self._settled: dict[tuple[Path, str], tuple[int, int]] = {}

    def references(self) -> tuple[str, ...]:
        """Every specification the model answers for, `TS29.229`-spelled, in
        sort order. Every query taking a reference reads it however it is
        spelled: "TS 29.229", "ts29.229", "3GPP TS 29.229"."""
        return tuple(sorted(self._views))

    def canonical(self, reference: str) -> str:
        """The reference `reference` spells, `TS29.229` for "ts 29.229", or
        `ModelError` suggesting the close ones."""
        if reference in self._views:
            return reference
        folded = _folded(str(reference))
        found = self._spellings.get(folded)
        if found is not None:
            return found
        close = difflib.get_close_matches(folded, self._spellings, n=3)
        hint = (
            f"; did you mean {', '.join(self._spellings[each] for each in close)}?"
            if close
            else "; Model.references() lists what it holds"
        )
        raise ModelError(f"the corpus holds no copy of {reference}{hint}")

    def _view(self, reference: str, version: str | None = None) -> _View:
        reference = self.canonical(reference)
        if version is None:
            return self._views[reference]
        for view in self._copies.values():
            if view.entry.reference == reference and view.entry.spec.version == version:
                return view
        held = ", ".join(self._books.versions(reference))
        raise ModelError(
            f"the corpus holds no copy of {reference} V{version}; it holds {held}"
        )

    # --- resolution ---------------------------------------------------------

    def _names(self, reference: str) -> dict[str, None]:
        view = self._view(reference)
        return dict.fromkeys(
            (*view.defined, *view.tabled, *view.reused, *view.undefined)
        )

    def _final(self, view: _View, name: str, stack: tuple = ()) -> Avp | Hole:
        draft = self._resolve(view, name, stack)
        if draft is None:
            return self._on_record(
                Hole(
                    view.entry.reference,
                    name,
                    (Missing.DEFINITION,),
                    version=self._older(view),
                )
            )
        found = draft.final
        if (
            isinstance(found, Hole)
            and found.undefined is not None
            and self._policy is UndefinedPolicy.SUPPLY
        ):
            answered = self._answered(found.undefined, stack)
            if answered is None:
                return self._on_record(found)
            if answered.supplied is not None and found.across_releases is not None:
                # The supplied definition is the declaring document's; the
                # citation that reached it is this reading's, as it is for
                # any field a reading takes across releases.
                return replace(answered, across_releases=found.across_releases)
            return answered
        return self._on_record(found) if isinstance(found, Hole) else found

    def _on_record(self, hole: Hole) -> Hole:
        """`hole` with the reason the record states for it, when an entry
        lists it as it is."""
        entry = self._known.get((hole.document, hole.name))
        if entry is None or entry.missing != hole.missing:
            return hole
        return replace(hole, recorded=entry.reason)

    def _undefined_of(self, view: _View, block: ast.UndefinedAvp) -> Undefined:
        return Undefined(
            reference=view.entry.reference,
            name=block.name,
            section=block.source.section,
            page=block.source.page,
            note=block.note,
            cited_in=view.cited_in(block.name),
            version=self._older(view),
        )

    def _declaring(self, undefined: Undefined) -> _View:
        """The copy whose block `undefined` is."""
        return next(
            view
            for view in self._copies.values()
            if view.entry.reference == undefined.reference
            and self._older(view) == undefined.version
        )

    def _answer(self, undefined: Undefined) -> Supplied | Alias | None:
        """What `supply` says of a declared name, a document key first."""
        answer = self._supply.get((undefined.reference, undefined.name))
        return self._supply.get(undefined.name) if answer is None else answer

    def _answered(self, undefined: Undefined, stack: tuple) -> Avp | None:
        """What `supply` answers for a declared name: the `Supplied`
        definition read in the declaring document, or the AVP an `Alias`
        names; None where it says nothing of it."""
        answer = self._answer(undefined)
        if answer is None:
            return None
        if isinstance(answer, Alias):
            # The stack carries each alias being followed, so one leading
            # back to a name already being answered is refused rather than
            # followed forever.
            mark = (_ALIASED, undefined.reference, undefined.version, undefined.name)
            if mark in stack:
                chain = [each for each in stack if each[0] is _ALIASED]
                cycle = [*chain[chain.index(mark) :], mark]
                raise ModelError(
                    "supply aliases form a cycle: "
                    + " -> ".join(f"{each[1]} {each[3]}" for each in cycle)
                )
            found = self._final(
                self._view(answer.reference), answer.name, (*stack, mark)
            )
            return found if isinstance(found, Avp) else None
        view = self._declaring(undefined)
        key = (view.entry.path, undefined.name)
        if key in self._supplied:
            return self._supplied[key]
        kind = {
            ast.DataType.GROUPED: Grouped,
            ast.DataType.ENUMERATED: Enumerated,
        }.get(answer.data_type, Avp)
        draft = _Draft(
            kind,
            undefined.name,
            undefined.reference,
            undefined.version,
            vendor_id=answer.vendor_id,
            vendor_stated=True,
            code=answer.code,
            data_type=answer.data_type,
            flag_rules=answer.flag_rules,
            section=undefined.section,
            values=answer.values,
            supplied=answer.source,
        )
        if kind is Grouped:
            # A member that is itself declared undefined follows the
            # policy, and the name among its own members is cut.
            members = self._body(view, answer.members, (*stack, key))
            draft.members, draft.dropped = self._split(members)
        if self._wireshark is not None:
            draft.wireshark_name = self._wireshark.name_for(
                answer.vendor_id, answer.code, undefined.name, answer.data_type
            )
        found = draft.final
        assert isinstance(found, Avp)
        self._supplied[key] = found
        return found

    def _older(self, view: _View) -> str | None:
        """`view`'s version when it is an older copy the corpus holds for a
        citation, not the one reference-level queries answer from: the
        version a hole falling short there names (TS 32.299 V11.20.0)."""
        if view is self._views[view.entry.reference]:
            return None
        return view.entry.spec.version

    def _document(self, view: _View) -> str:
        """`view`'s reference, spelled as `Hole.document`."""
        version = self._older(view)
        return view.entry.reference + ("" if version is None else f" V{version}")

    def _resolve(self, view: _View, name: str, stack: tuple) -> _Draft | None:
        key = (view.entry.path, name)
        if key in self._resolved:
            return self._resolved[key]
        if key in stack:
            # A grouped AVP among its own descendants. No real specification
            # does this; stopping here keeps a defective one from recursing.
            return None
        result = self._resolve_here(view, name, (*stack, key))
        self._resolved[key] = result
        return result

    def _resolve_here(self, view: _View, name: str, stack: tuple) -> _Draft | None:
        """The first reading along the resolution order, with whatever it
        leaves unstated filled from the readings after it.

        A re-print that tabulates no flag rules (TS 29.272's
        `Allocation-Retention-Priority`, re-used from TS 29.212) takes them
        from its origin, and an origin that states no Diameter type (RFC
        4590's RADIUS-derived `Digest-*` rows, uncorrected) takes it from
        the citing document's table. The first reading still names the defining
        document.

        A re-used name whose row in the citing document's own AVP table
        states flag cells takes those cells over every other reading's
        (`_own_flags`), the others supplying only the flags the row places
        in no column: TS 29.229's `Digest-Qop` is M in Must through TS
        29.229 and M in May through RFC 4590. Below those cells and above
        the origin ranks the M-bit cell of the citing document's re-used
        row (`_own_m_bit`): TS 29.272's `RAT-Type` is M in Must, TS 29.212's
        M in Must not.

        A grouped AVP defined elsewhere keeps its defining document's body,
        but each member this document says anything of is read through it
        (`_through`): TS 32.299's `Supported-Features` is TS 29.229's, and
        its `Feature-List` member TS 32.299's, M in Must.
        """
        own = self._own_flags(view, name)
        m_bit = self._own_m_bit(view, name)
        found: _Draft | None = None
        for reading in self._readings(view, name, stack, own is None):
            found = reading if found is None else found.fill(reading)
            if found.complete or found.conflict is not None:
                break
        if found is not None and found.kind is not None:
            rules = found.flag_rules
            if m_bit is not None and (
                rules is not None or found.vendor_id == ast.IETF_VENDOR
            ):
                # Over an IETF reading stating no flags, RFC 6733's V rule
                # completes the M-bit (`_ietf_rules`); anywhere else an M
                # alone would complete rules nothing else states.
                rules = _overlay(m_bit, rules)
            if own is not None:
                rules = _overlay(own, rules)
            completed = found.completed_by
            if (
                rules is not None
                and found.flag_rules is None
                and found.reference != view.entry.reference
            ):
                completed += ((Missing.FLAG_RULES, view.entry.reference),)
            found = replace(
                found,
                flag_rules=rules,
                completed_by=completed,
                read_through=(
                    self._document(view)
                    if rules != found.flag_rules
                    else found.read_through
                ),
            )
            if found.kind is Grouped and not isinstance(
                view.defined.get(name), ast.GroupedAvp
            ):
                self._settle(stack[-1], found.vendor_id, found.code)
                members = self._through(view, found.members, stack)
                if members != found.members:
                    found.read_through = self._document(view)
                found.members = members
        if found is not None and found.kind is Avp:
            tables = tuple(
                table for table in view.value_tables if table.avp == found.name
            )
            found = replace(found, value_tables=tables or found.value_tables)
        if (
            found is not None
            and self._wireshark is not None
            and found.vendor_id is not None
            and found.code is not None
        ):
            # Looked up once the identity is final: a reading filled through
            # may take its code from the next document.
            wireshark_name = self._wireshark.name_for(
                found.vendor_id, found.code, found.name, found.data_type
            )
            found = replace(found, wireshark_name=wireshark_name)
        return found

    def _own_flags(self, view: _View, name: str) -> ast.AvpFlagRules | None:
        """The flag rules `view`'s AVP-table rows state for a name it
        re-uses, each flag where the first row placing it puts it, or None
        when it re-uses no such name or no row places any flag.

        RFC 6733 section 4.1 leaves the M bit to "the application
        specification that introduces or reuses this AVP" and section 4.5
        has each application state its AVPs' flag rules, so where the citing
        table states them they are its application's, and resolution through
        the citing document reads them rather than the origin's. Per flag,
        since a row leaving a flag in no column says nothing of it: a later
        row is read only for a flag no earlier row places. A file citing
        itself (TS 29.212's Gxx tables, "from" TS 29.212) re-uses
        nothing, and its rows are read as any other."""
        rows = view.tabled.get(name)
        origin = view.reused.get(name)
        if origin is None or rows is None:
            return None
        if self._cited(view, origin)[0] is view:
            return None
        rules = rows[0].flag_rules
        for row in rows[1:]:
            rules = _overlay(rules, row.flag_rules)
        return rules if _stated(rules) else None

    def _own_m_bit(self, view: _View, name: str) -> ast.AvpFlagRules | None:
        """The M rule the first of `view`'s re-used rows for a name whose
        M-bit cell states one gives, as flag rules placing M alone, or None
        when no row's cell does (a dash, a blank, no M-bit column) or the
        rows cite `view` itself.

        The column is the citing interface's own M setting (TS 29.272 table
        7.3.1/2 marks TS 29.212's `RAT-Type` `MUST`), so it outranks the
        origin's rule as `_own_flags` does, and ranks below the citing
        document's AVP-table cells, the fuller statement. A row whose cell
        says nothing is passed over: TS 29.336's `DRMP` rows read `-` for
        its first interface and `MUST-NOT` for its second, so M is in Must
        not."""
        for row in view.reused_rows.get(name, ()):
            if row.m_bit is None or self._cited(view, row.origin)[0] is view:
                continue
            if row.m_bit is ast.MBitOverride.MUST:
                return ast.AvpFlagRules(must=frozenset({ast.AvpFlag.MANDATORY}))
            return ast.AvpFlagRules(must_not=frozenset({ast.AvpFlag.MANDATORY}))
        return None

    def _through(
        self, view: _View, members: tuple[Member, ...], stack: tuple
    ) -> tuple[Member, ...]:
        """A body another document resolved, with each member `view`
        defines, tabulates or re-uses read through `view` instead, so that
        its own rules for the member (`_own_flags`, `_own_m_bit`) hold
        inside the grouped AVP as they do at top level. A member `view` says
        nothing of keeps the other document's reading, and so does one
        `view` reads as another AVP: the body names its members in the
        defining document's sense, and a name is no identity. TS 32.299's
        own `Originator` is (10415, 864) Enumerated, but the re-used
        `M2M-Information` it reads through oneM2M TS-0004 holds oneM2M's,
        (45687, 1008) UTF8String. Only a reading whose vendor and code are
        both known and both the member's is read through `view`: two holes
        stating no code are no evidence of one AVP. A grouped member read
        through `view` has
        its own members read the same way; one already being resolved
        through `view` (a body among its own descendants) is cut as `_body`
        cuts it, but only where the identity that reading has settled
        (`_settled`) is known and the member's: a citing document's own
        `Feature` holding a re-used `Bundle` whose `Feature` is the
        origin's, another AVP, keeps the origin's member."""
        says = view.defined.keys() | view.tabled.keys() | view.reused.keys()
        read = []
        for member in members:
            mine = member
            if member.name in says:
                mine = self._member(view, member.rule, stack)
                identity = (
                    self._settled.get((view.entry.path, member.name))
                    if is_cut(mine)
                    else _identity(mine)
                )
                if identity is None or identity != _identity(member):
                    mine = member
            read.append(mine)
        return tuple(read)

    def _settle(
        self, key: tuple[Path, str], vendor_id: int | None, code: int | None
    ) -> None:
        """Record the identity the reading under `key`, still being
        resolved, has settled before its members are read, if it is
        known."""
        if vendor_id is not None and code is not None:
            self._settled[key] = (vendor_id, code)

    def _readings(
        self, view: _View, name: str, stack: tuple, own_flags: bool = True
    ) -> Iterator[_Draft]:
        """Every document's reading of `name`, in resolution order, lazily:
        the local definition, the re-used origin, the local table row, the
        `; Bases:` documents.

        Without `own_flags` the local readings carry no flag rules, so that
        flags the caller lays over the result (`_own_flags`) neither fill nor
        disagree with another document's."""
        rows = view.tabled.get(name)
        origin = view.reused.get(name)
        theirs, across = (None, None) if origin is None else self._cited(view, origin)
        unread = origin if theirs is None else None
        definition = view.defined.get(name)
        if definition is not None:
            draft = self._from_definition(view, definition, rows, unread, stack)
            yield draft if own_flags else replace(draft, flag_rules=None)
        if theirs is not None and (found := self._resolve(theirs, name, stack)):
            yield found if across is None else replace(found, across=across)
            assert origin is not None
            if (later := self._later_release(view, origin, name, stack)) is not None:
                yield later
        if rows is not None and definition is None:
            draft = self._from_row(view, name, rows[0], unread)
            yield draft if own_flags else replace(draft, flag_rules=None)
        for base in view.entry.spec.bases:
            cited, across = self._cited(view, base)
            if cited is not None and (found := self._resolve(cited, name, stack)):
                yield found if across is None else replace(found, across=across)
        if unread is not None:
            yield _Draft(
                None, name, view.entry.reference, self._older(view), origin=unread
            )
        if (block := view.undefined.get(name)) is not None:
            # Last: it explains the failure and defines nothing.
            yield _Draft(
                None,
                name,
                view.entry.reference,
                self._older(view),
                section=block.source.section,
                undefined=self._undefined_of(view, block),
            )

    def _later_release(
        self, view: _View, origin: str, name: str, stack: tuple
    ) -> _Draft | None:
        """What a later release's copy states of `name` for a citation of
        `origin` whose own copy leaves it unstated, by a
        `corpus.Rules.release_fills` entry: the entry's fields and no other,
        each naming that copy in `completed_by`. Its code still has to agree
        (`_Draft.fill`), and its vendor is the citation's copy's to state. TS
        29.210's `3GPP-SGSN-MCC-MNC` takes its type from TS 29.061 V19.1.0 and
        not the flags, whose M Release 19's table 9a puts in Must not."""
        found = self._books.release_fill(origin, like=view.entry.spec)
        if found is None or name not in found[1].names:
            return None
        entry, fill, crossing = found
        later = self._resolve(self._copies[entry.path], name, stack)
        if later is None:
            return None
        stating = f"{later.reference} V{entry.spec.version}"
        return replace(
            later,
            vendor_stated=False,
            data_type=later.data_type if Missing.DATA_TYPE in fill.fields else None,
            flag_rules=later.flag_rules if Missing.FLAG_RULES in fill.fields else None,
            across=crossing,
            completed_by=tuple((each, stating) for each in fill.fields),
            read_through=None,
        )

    def _cited(
        self, view: _View, reference: str
    ) -> tuple[_View | None, corpus.CrossRelease | None]:
        """The copy `reference` names when cited from `view`, if the corpus
        holds the one the drafting rules mean, and how it was reached when
        that is outside `view`'s release (`corpus.Corpus.resolution`)."""
        entry, across = self._books.resolution(reference, like=view.entry.spec)
        return (None, None) if entry is None else (self._copies[entry.path], across)

    def _from_row(
        self, view: _View, name: str, row: ast.AvpTableRow, unread: str | None
    ) -> _Draft:
        file_vendor = view.entry.spec.vendor_id
        stated = row.stated_vendor(file_vendor)
        return _Draft(
            Avp,
            name,
            view.entry.reference,
            self._older(view),
            vendor_id=file_vendor if stated is None else stated,
            vendor_stated=stated is not None,
            code=row.code,
            data_type=row.data_type,
            flag_rules=row.flag_rules if _stated(row.flag_rules) else None,
            section=row.section,
            origin=unread,
        )

    def _from_definition(
        self,
        view: _View,
        definition: ast.GroupedAvp | ast.EnumeratedAvp,
        rows: list[ast.AvpTableRow] | None,
        unread: str | None,
        stack: tuple,
    ) -> _Draft:
        flag_rules = None if rows is None else rows[0].flag_rules
        draft = _Draft(
            Grouped if isinstance(definition, ast.GroupedAvp) else Enumerated,
            definition.name,
            view.entry.reference,
            self._older(view),
            # A definition written with no vendor-id is IETF-space; the wire
            # format calls that vendor 0.
            vendor_id=(
                ast.IETF_VENDOR
                if definition.vendor_id is None
                else definition.vendor_id
            ),
            vendor_stated=True,
            code=definition.code,
            flag_rules=(
                flag_rules if flag_rules is not None and _stated(flag_rules) else None
            ),
            section=definition.source.section,
            origin=unread,
        )
        if isinstance(definition, ast.GroupedAvp):
            draft.data_type = ast.DataType.GROUPED
            self._settle(stack[-1], draft.vendor_id, draft.code)
            draft.members, draft.dropped = self._split(
                self._body(view, definition.avps, stack)
            )
        else:
            draft.data_type = ast.DataType.ENUMERATED
            draft.values = definition.values
            draft.values_source = definition.values_source
        return draft

    def _body(
        self, view: _View, rules: tuple[ast.AvpRule, ...], stack: tuple = ()
    ) -> tuple[Member, ...]:
        return tuple(self._member(view, rule, stack) for rule in rules)

    def _member(self, view: _View, rule: ast.AvpRule, stack: tuple) -> Member:
        """One body line, its name read through `view`."""
        # `AVP` is RFC 6733's any-AVP wildcard — grammar, not a name.
        if rule.name == "AVP" or (view.entry.path, rule.name) in stack:
            return Member(rule=rule, avp=None)
        found = self._final(view, rule.name, stack)
        if isinstance(found, Avp):
            return Member(rule=rule, avp=found, alias=self._alias(view, rule.name))
        if found.undefined is not None and self._policy is UndefinedPolicy.PLACEHOLDER:
            return Member(rule=rule, avp=None, placeholder=Placeholder(found.undefined))
        return Member(rule=rule, avp=None, hole=found)

    def _alias(self, view: _View, name: str) -> Alias | None:
        """The `Alias` `name` resolves through in `view`, if it does."""
        if self._policy is not UndefinedPolicy.SUPPLY:
            return None
        draft = self._resolved.get((view.entry.path, name))
        hole = None if draft is None else draft.final
        if not isinstance(hole, Hole) or hole.undefined is None:
            return None
        answer = self._answer(hole.undefined)
        return answer if isinstance(answer, Alias) else None

    def _split(
        self, members: tuple[Member, ...]
    ) -> tuple[tuple[Member, ...], tuple[Member, ...]]:
        """A body's members, and those `UndefinedPolicy.DROP` takes out of
        it: the undefined ones, required or not."""
        if self._policy is not UndefinedPolicy.DROP:
            return members, ()
        kept: list[Member] = []
        dropped: list[Member] = []
        for member in members:
            undefined = member.hole is not None and member.hole.undefined is not None
            (dropped if undefined else kept).append(member)
        return tuple(kept), tuple(dropped)
