"""The editors' highlighting: the TextMate grammar
(`src/seanchai/dad/syntax/dad.tmLanguage.json`, copied to `editors/vscode/`)
scopes each shape of line the format has as `tests/fixtures/syntax/sample.dad`
and, for an interpretations file, `sample.dadx` pin, and the Vim syntax
(`editors/vim/syntax/dad.vim`) colours every character of the samples, of
each distinct line of the corpus and of the interpretations files as the
grammar's scope there says, skipped without `vim`.

The grammar is read by a small tokenizer after vscode-textmate's: `match` and
`captures` (a capture's patterns matched over the line cut at the capture's
end), `include`, and one `begin`/`end` level. Python's `re` takes the
grammar's patterns once a lookbehind's alternatives of unequal width are split
into lookbehinds of their own.
"""

import collections
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from seanchai.dad import parser

ROOT = Path(__file__).resolve().parent.parent
GRAMMAR = ROOT / "src" / "seanchai" / "dad" / "syntax" / "dad.tmLanguage.json"
VIM = ROOT / "editors" / "vim"
SAMPLE = ROOT / "tests" / "fixtures" / "syntax" / "sample.dad"
SAMPLE_DADX = SAMPLE.with_suffix(".dadx")
CORPUS = ROOT / "packages" / "seanchai-corpus" / "src" / "seanchai_corpus" / "dad"
INTERPRETATIONS = ROOT / "edits" / "interpretations"

_LOOKBEHIND = re.compile(r"\(\?<=((?:\\.|[^()\\])+)\)")


def _compile(pattern: str) -> re.Pattern[str]:
    def split(found: re.Match[str]) -> str:
        parts = found.group(1).split("|")
        if len(parts) == 1:
            return found.group(0)
        return "(?:" + "|".join(f"(?<={part})" for part in parts) + ")"

    return re.compile(_LOOKBEHIND.sub(split, pattern))


class Grammar:
    def __init__(self, path: Path) -> None:
        self.grammar = json.loads(path.read_text("utf-8"))
        self.repository = self.grammar["repository"]
        self.compiled: dict[str, re.Pattern[str]] = {}

    def rx(self, pattern: str) -> re.Pattern[str]:
        if pattern not in self.compiled:
            self.compiled[pattern] = _compile(pattern)
        return self.compiled[pattern]

    def flatten(self, patterns: list[dict]) -> list[dict]:
        out = []
        for each in patterns:
            if "include" in each:
                rule = self.repository[each["include"][1:]]
                if "match" in rule or "begin" in rule:
                    out.append(rule)
                else:
                    out.extend(self.flatten(rule["patterns"]))
            else:
                out.append(each)
        return out

    def tokenize(self, lines: list[str]) -> list[list[list[str]]]:
        """Each line's scopes: per character, the stack of scope names."""
        entered: list[dict] = []
        result = []
        for line in lines:
            scopes: list[list[str]] = [[] for _ in line]
            at = 0
            while at <= len(line):
                rule = entered[-1] if entered else None
                patterns = self.flatten(
                    rule["patterns"] if rule else self.grammar["patterns"]
                )
                best = None
                if rule and (found := self.rx(rule["end"]).search(line, at)):
                    best = (found.start(), found, "end", rule)
                for each in patterns:
                    key = "match" if "match" in each else "begin"
                    found = self.rx(each[key]).search(line, at)
                    if found and (best is None or found.start() < best[0]):
                        best = (found.start(), found, key, each)
                if best is None:
                    break
                _, found, kind, each = best
                if kind == "end":
                    entered.pop()
                    at = found.end()
                elif kind == "begin":
                    entered.append(each)
                    at = found.end()
                else:
                    self.apply(line, found, each, scopes)
                    at = found.end() + (found.end() == found.start())
            result.append(scopes)
        return result

    def apply(
        self, line: str, found: re.Match[str], rule: dict, scopes: list[list[str]]
    ) -> None:
        if name := rule.get("name"):
            for index in range(found.start(), found.end()):
                scopes[index].append(name)
        for group, capture in sorted(
            rule.get("captures", {}).items(), key=lambda item: int(item[0])
        ):
            number = int(group)
            if found.group(number) is None or found.start(number) == found.end(number):
                continue
            if "name" in capture:
                for index in range(found.start(number), found.end(number)):
                    scopes[index].append(capture["name"])
            if "patterns" in capture:
                self.within(
                    line[: found.end(number)],
                    found.start(number),
                    capture["patterns"],
                    scopes,
                )

    def within(
        self, text: str, at: int, patterns: list[dict], scopes: list[list[str]]
    ) -> None:
        patterns = self.flatten(patterns)
        while at < len(text):
            best = None
            for each in patterns:
                found = self.rx(each["match"]).search(text, at)
                if found and (best is None or found.start() < best[0].start()):
                    best = (found, each)
            if best is None:
                return
            found, each = best
            self.apply(text, found, each, scopes)
            at = found.end() + (found.end() == found.start())


@pytest.fixture(scope="module")
def grammar() -> Grammar:
    return Grammar(GRAMMAR)


def test_the_sample_is_a_dad_file():
    parser.parse(SAMPLE.read_text("utf-8"))


def test_the_dadx_sample_is_an_interpretations_file():
    parser.parse_interpretations(SAMPLE_DADX.read_text("utf-8"))


# A line of the sample by its start, a token in it (its first occurrence, or
# the one after `after`) and the innermost scope it takes.
_SCOPED = [
    ("; Specification: Private", "Private ACME-HSS", "string.unquoted.directive-value"),
    ("; Obsoletes:", "RFC4006", "entity.name.tag.spec-ref"),
    ("; Transcribed:", "https://example.com/acme-hss.html", "markup.underline.link"),
    ("; Applies-To:", "E.6.*", "constant.other.section.wildcard"),
    ("; Applies-To:", ",", "punctuation.separator.comma"),
    ("; Applies-To:", "inserted", "keyword.other.note"),
    ("; Applies-To:", "Private-ACME-HSS.py#scope", "markup.underline.link.declaration"),
    ("; Reprints:", "TS29.272", "entity.name.tag.spec-ref"),
    ("<answer-message>", "ERR", "constant.language.command-flag"),
    ("       1*2 [", "1*2", "keyword.operator.occurrences"),
    ("       1*2 [", "; strikethrough", "storage.modifier.strikethrough"),
    ("       1*2 [", "corrected", "keyword.other.note"),
    ('         "Second one"', "supplied", "keyword.other.note"),
    ("         ; RESERVED", "-", "keyword.operator.range"),
    ("         ; VENDOR-SPECIFIC", "patched", "keyword.other.note"),
    (
        "         ; VENDOR-SPECIFIC",
        "Private-ACME-HSS.toml",
        "markup.underline.link.declaration",
    ),
    ("; Columns: Name ", "Applicability", "string.unquoted.directive-value"),
    ("; Command-Section:", "6.2.1", "constant.other.section"),
    ("ACME-Flags  ", "3GPP-EPS,Non-3GPP-EPS", ""),
    ("ACME-Data   ", '""', "string.quoted.double.mark"),
    ("ACME-Id  ", "7.3.5.1", "comment.line.double-semicolon"),
    ("ACME-Id  ", "Private-ACME-HSS.py#id-row", "markup.underline.link.declaration"),
    ("; Kind: bits", "bits", "constant.language.value-kind"),
    ("; Kind: bits", "corrected", "keyword.other.note"),
    ("; Kind: result-codes", "result-codes", "constant.language.value-kind"),
    ("; Kind: values", "values", "constant.language.value-kind"),
    ('"Insufficient', '"Insufficient resources"', "variable.other.enum"),
    ("DIAMETER_ACME_UNKNOWN", "from", "keyword.other.from"),
    ("DIAMETER_ACME_UNKNOWN", "TS29.272", "entity.name.tag.spec-ref"),
    ("; Type: Information Elements", "Information Elements", "storage.type.section"),
    ("IMSI", "IMSI", ""),
    ("IMSI", "User-Name", "variable.other.avp"),
    ("IMSI", "M", "constant.language.category", "User-Name "),
    (
        '"Supported Features',
        '"Supported Features (See TS 29.229 [9])"',
        "string.quoted.double.mark",
    ),
    ("Hosts", ",", "punctuation.separator.avp"),
    ("Hosts", "C", "constant.language.category"),
    ("Result ", "/", "punctuation.separator.avp"),
    ("Result ", "Experimental-Result", "variable.other.avp"),
    ('"EAP payload"', "O", "constant.language.category"),
    ("Unmapped", "-", "punctuation.definition.empty-cell"),
    ("Unmapped", "-", "constant.language.category", "- "),
    ("Blank ", '""', "constant.language.category"),
    # A table naming its elements by their AVPs, set off under a grouped AVP.
    ("ACME-Origin ", "ACME-Origin", "variable.other.avp"),
    ("Proxy-Info ", "OC", "constant.language.category"),
    ("    Proxy-Host", "Proxy-Host", "variable.other.avp"),
    ("    Proxy-Host", "M", "constant.language.category"),
    ("    Proxy-State", '""', "constant.language.category"),
    ("    Proxy-State", "corrected", "keyword.other.note"),
    ("ACME-Grouped", "OM", "constant.language.category"),
    ('"ACME Typo"', '"ACME Typo"', "string.quoted.double.mark"),
    ('"ACME Typo"', "-", "constant.language.category"),
    ("AVP  ", "AVP", "variable.other.avp"),
    ("AVP  ", "OC", "constant.language.category"),
    ("; Type: Command Result Codes", "Command Result Codes", "storage.type.section"),
    ("DIAMETER_SUCCESS", "DIAMETER_SUCCESS", "variable.other.enum"),
    ("DIAMETER_ERROR_ACME", "corrected", "keyword.other.note"),
    ('"ACME odd code"', '"ACME odd code"', "variable.other.enum"),
    # A re-used AVP's row has the shape of an element's, outside the block.
    ("Session-Id  ", "MUST", "constant.language"),
    ("Destination-Host  ", "-", "punctuation.definition.empty-cell", "RFC6733 "),
    ("; Type: Interpreted Constraints ;;", "interpreted", "keyword.other.note"),
    (
        "; Type: Interpreted Constraints ;;",
        "Private-ACME-HSS.dadx#id-length",
        "markup.underline.link.declaration",
    ),
    ("; Versions: *..", "*", "keyword.operator"),
    ("; Versions: *..", "..", "keyword.operator.range"),
    ("    length 1..15", "characters", "constant.language.unit"),
    ("    length *..15", "*", "keyword.operator"),
    ("    encoding digits", "digits", "support.type.codec"),
    ("    exclude", ",", "punctuation.separator.comma"),
    ("    range -5", "-5", "constant.numeric"),
    ("    range -5", "*", "keyword.operator"),
    ("    unique", "unique", "keyword.control.constraint"),
    ("    present-if", "ACME-Flags", "variable.other.avp"),
    ("    present-if", "bit", "keyword.operator.condition"),
    ("    present-if", "or", "keyword.operator.condition"),
    ("    present-if", '"Withdraw Data"', "string.quoted.double.mark"),
    ("    absent-if", "=", "keyword.operator"),
    ("    absent-if ACME-Kind = 2", "and", "keyword.operator.condition"),
    ("    absent-if ACME-Kind = 2", "not", "keyword.operator.condition"),
    ("    requires ACME-Data/", "/", "punctuation.separator.path"),
    ("    requires ACME-Data/", "ACME-Id", "variable.other.avp"),
    ("    excludes", "FIRST", "variable.other.avp"),
    # A value's name may begin with a digit; one of digits only is quoted.
    ("    absent-if ACME-Kind = 3GPP", "3GPP_ACME", "variable.other.avp"),
    ("    absent-if ACME-Kind = 3GPP", '"16"', "string.quoted.double.mark"),
    ("    excludes ACME-Code in", "in", "keyword.operator.condition"),
    ("    excludes ACME-Code in", "2000", "constant.numeric"),
    ("    excludes ACME-Code in", "..", "keyword.operator", "2000"),
    ("    excludes ACME-Code in", ",", "punctuation.separator.comma"),
    # A wrapped rule goes on in a line indented eight spaces.
    ('        "16", 4000', '"16"', "string.quoted.double.mark"),
    ('        "16", 4000', "4000", "constant.numeric"),
    ('        "16", 4000', "..", "keyword.operator"),
    ("    default 0", "0", "constant.numeric"),
    ("    encoding element TS29.002", "element", "support.type.codec"),
    ("    encoding element TS29.002", "17.7.8", "constant.other.section"),
    ("    encoding element 3GPP2", "3GPP2-A.S0022", "entity.name.tag.spec-ref"),
    ("    encoding element 3GPP2", "A", "constant.other.section", "S0022 "),
    (
        "    encoding element 3GPP2",
        '"Mobile Identity (MEID)"',
        "string.quoted.double.mark",
    ),
    ("    encoding e164-tbcd", "e164-tbcd", "support.type.codec"),
    ("    text-only", "text-only", "keyword.control.constraint"),
    ("    bits at-most-one", "at-most-one", "keyword.operator.condition"),
    ("    bits only", "only", "keyword.operator.condition"),
    ("    values", "if", "keyword.operator.condition"),
    ("    values", ",", "punctuation.separator.comma"),
    ("    default FIRST", "FIRST", "variable.other.avp"),
    ("    members at-least-one", "ACME-Kind", "variable.other.avp"),
    ("    members only", "only", "keyword.operator.condition"),
    ("; Request-Section:", "6.2.1", "constant.other.section"),
    ("    absent", "absent", "keyword.control.constraint"),
    ("    equals", "equals", "keyword.control.constraint"),
    ("    equals", "request", "keyword.other.root"),
    ("    equals", "/", "punctuation.separator.path"),
    ("    equals", "ACME-Id", "variable.other.avp"),
    ("    present-if request", "request", "keyword.other.root", "= "),
    ("    present-if request", "ACME-Kind", "variable.other.avp", "/"),
    (";; deleted:", "deleted", "keyword.other.note"),
]


# As `_SCOPED`, over `sample.dadx`.
_SCOPED_DADX = [
    ("; Interprets:", "Interprets", "keyword.other.directive"),
    ("; Interprets:", "Private ACME-HSS", "string.unquoted.directive-value"),
    ("; Id:", "Id", "keyword.other.directive"),
    ("; Id:", "id-length", "string.unquoted.directive-value"),
    (";; Read from", "Read", "comment.line.double-semicolon"),
    ("    length 1..15", "characters", "constant.language.unit"),
    ("    length 1..15", "the octets", "comment.line.double-semicolon"),
    ("; Versions: 1.0.0", "..", "keyword.operator.range"),
    ("; Command-Section:", "6.1.1", "constant.other.section"),
    ("; Messages:", "Messages", "keyword.other.directive"),
    ("; Messages:", "answers", "string.unquoted.directive-value"),
    ("    absent-if ACME-Code in", "in", "keyword.operator.condition"),
    ("        5000..5999", "or", "keyword.operator.condition"),
    ("        5000..5999", "ACME-Flags", "variable.other.avp"),
    ("        5000..5999", "5000", "constant.numeric"),
]


def _innermost(stack: list[str]) -> str:
    return stack[-1].removesuffix(".dad") if stack else ""


@pytest.mark.parametrize(
    ("sample", "case"),
    [(SAMPLE, case) for case in _SCOPED]
    + [(SAMPLE_DADX, case) for case in _SCOPED_DADX],
    ids=lambda each: f"{each[0]}|{each[1]}" if isinstance(each, tuple) else each.name,
)
def test_the_grammar_scopes_each_shape(grammar, sample, case):
    start, token, scope, *rest = case
    lines = sample.read_text("utf-8").split("\n")
    scopes = grammar.tokenize(lines)
    (index,) = [n for n, line in enumerate(lines) if line.startswith(start)][:1]
    line = lines[index]
    after = rest[0] if rest else ""
    at = line.index(token, line.index(after) + len(after) if after else 0)
    assert {_innermost(scopes[index][i]) for i in range(at, at + len(token))} == {
        scope
    }, line


# The Vim highlight group each scope pairs with: the innermost scope, by its
# longest listed prefix.
_GROUPS = {
    "comment": "Comment",
    "keyword.other": "Keyword",
    "keyword.other.note": "SpecialComment",
    "keyword.control.constraint": "Statement",
    "keyword.operator": "Operator",
    "string": "String",
    "storage.type": "Type",
    "support.type.codec": "Type",
    "storage.modifier": "SpecialComment",
    "entity.name.tag.spec-ref": "Tag",
    "markup.underline.link": "Underlined",
    "constant.other.section": "Constant",
    "constant.numeric": "Number",
    "constant.language.dad": "Boolean",
    "constant.language": "Constant",
    "punctuation": "Delimiter",
    "entity.name.function": "Function",
    "support.function": "Function",
    "support.class": "Special",
    "variable": "Identifier",
}


def _group(stack: list[str]) -> str:
    if not stack:
        return ""
    scope = stack[-1]
    for prefix in sorted(_GROUPS, key=len, reverse=True):
        if scope == prefix or scope.startswith(prefix + "."):
            return _GROUPS[prefix]
    return "?" + scope


_DUMP = r"""
for job in json_decode(join(readfile(g:jobs), "\n"))
  execute 'edit ' . fnameescape(job.file)
  let out = []
  for l in job.lines
    let names = []
    for c in range(1, strlen(getline(l)))
      call add(names, synIDattr(synID(l, c, 1), 'name'))
    endfor
    call add(out, l . "\t" . join(names, ' '))
  endfor
  call writefile(out, job.out)
endfor
"""


def _distinct(lines: list[str], seen: set) -> list[int]:
    """The lines no earlier file or line printed in the same kind of block."""
    kind = None
    chosen = []
    for number, line in enumerate(lines):
        if line.startswith("; Type: "):
            kind = line.split(";;")[0].strip()
        elif not line.strip():
            kind = None
        if (kind, line) not in seen:
            seen.add((kind, line))
            chosen.append(number)
    return chosen


@pytest.mark.skipif(shutil.which("vim") is None, reason="no vim on PATH")
def test_vim_colours_each_line_as_the_grammar_scopes_it(grammar, tmp_path):
    links = {}
    for row in (VIM / "syntax" / "dad.vim").read_text("utf-8").splitlines():
        words = row.split()
        if words[:3] == ["hi", "def", "link"]:
            links[words[3]] = words[4]
    files = [
        SAMPLE,
        SAMPLE_DADX,
        *sorted(CORPUS.rglob("*.dad")),
        *sorted(INTERPRETATIONS.glob("*.dadx")),
    ]
    seen: set = set()
    jobs, texts = [], {}
    for index, path in enumerate(files):
        lines = path.read_text("utf-8").split("\n")
        chosen = _distinct(lines, seen)
        if chosen:
            out = tmp_path / f"{index}.txt"
            texts[out] = (path, lines)
            jobs.append(
                {"file": str(path), "lines": [n + 1 for n in chosen], "out": str(out)}
            )
    (tmp_path / "jobs.json").write_text(json.dumps(jobs), "utf-8")
    (tmp_path / "dump.vim").write_text(_DUMP, "utf-8")
    subprocess.run(
        [
            "vim", "-N", "-u", "NONE", "-i", "NONE", "-n", "-es",
            "-c", f"set runtimepath^={VIM}",
            "-c", "filetype plugin on",
            "-c", "syntax on",
            "-c", f"let g:jobs = '{tmp_path / 'jobs.json'}'",
            "-c", f"source {tmp_path / 'dump.vim'}",
            "-c", "qa!",
        ],
        check=True,
        timeout=600,
    )  # fmt: skip
    wrong: collections.Counter = collections.Counter()
    example = {}
    for out, (path, lines) in texts.items():
        scopes = grammar.tokenize(lines)
        for row in out.read_text("utf-8").splitlines():
            number, _, names = row.partition("\t")
            index = int(number) - 1
            groups = names.split(" ") if names else []
            byte = 0
            for at, char in enumerate(lines[index]):
                name = groups[byte] if byte < len(groups) else ""
                byte += len(char.encode("utf-8"))
                want, got = _group(scopes[index][at]), links.get(name, "")
                # Classic Vim names a `; bold` rule's AVP in a bold group of
                # its own, which cannot also carry a colour.
                bold = name == "dadAvpBoldName"
                if char == " " or want == got or (bold and want != "Comment"):
                    continue
                key = (want, name)
                wrong[key] += 1
                example.setdefault(key, f"{path.name}:{index + 1}:{at + 1}")
    assert not wrong, [
        (key, count, example[key]) for key, count in wrong.most_common(10)
    ]
