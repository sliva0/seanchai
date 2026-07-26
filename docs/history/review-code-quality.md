# Code-quality review

This is a second whole-project review after the seven items in
`plan-code-quality.md` were completed. It checks the earlier findings against
the current implementation, reviews the correction and packaged-downloader
work added since, and leaves one prioritized list of what is still worth doing.

The review is based on commit `6b5b9a6`. At that commit:

- all 155 tests pass;
- ruff lint and format checks pass;
- ty and basedpyright pass;
- the sdist and wheel build successfully; and
- `src/seanchai/downloader/specs.toml` is present in the wheel.

The clean baseline is meaningful, but the most important findings below are
cases outside the current tests. Each high-priority failure was reproduced
directly rather than inferred only from reading the code.

## What the completed plan fixed

Several findings from the first review are closed.

- Empty AVP and re-used tables are rejected by the AST, so the formatter no
  longer crashes while trying to size an empty table
  (`src/seanchai/dad/ast.py:173-209`).
- Parser integer conversions and pydantic validation failures now surface as
  `DadParseError` rather than leaking bare `ValueError` or `ValidationError`
  (`src/seanchai/dad/parser.py:104-127`, `330-357`).
- Constructed-AST round trips and the previously missing extractor conventions
  are covered: mixed bold, multiple ABNFs in one command clause, NOTE-derived
  reused rows, enum ordering and patch-file naming.
- The misleading correction examples in `docs/corrections.md` were
  replaced with the real TS 29.272 VCSG application-id correction.
- The correction layer now exists, has a committed real correction set, and is
  exposed through both extraction and a separate `correct` command.
- The downloader is importable library code behind `seanchai download`; its
  catalog is loaded on demand and is packaged in the wheel.
- The old plan's open items are now recorded as completed rather than left as
  stale tasks.

Those changes substantially improve the project. The remaining work is not a
request to repeat them; it starts with defects exposed by the new correction
and downloader code, then carries forward the earlier findings that remain
applicable.

## 1. Correction rebuilding silently drops child edits

This is the highest-priority correctness defect.

`corrections.apply()` permits two corrections to different nodes in the same
branch. It records replacements by object identity and `_replaced()` walks the
tree afterwards (`src/seanchai/dad/corrections.py:238-287`). When it reaches a
node that has its own replacement, `_replaced()` returns that replacement
immediately and never visits its children.

Consequently, a correction to a `Message.application_id` and a correction to
one of that message's `AvpRule` children produce two successful `Result`
entries, but only the message correction appears in the returned
specification. Reversing declaration order makes no difference. The same
problem applies to an `EnumeratedAvp` corrected alongside one of its
`EnumValue` children.

Rebuilding should recurse through the chosen replacement rather than returning
it immediately, and the final tree should be rebuilt through validation. If
corrections that replace a structural field such as `avps` are not intended,
reject them explicitly; otherwise their interaction with child corrections
needs defined conflict semantics.

Add regression tests for:

- a definition and one of its AVP rules corrected together;
- an enumerated definition and one of its values corrected together;
- both declaration orders; and
- a parent structural-field replacement that conflicts with a child
  correction.

## 2. A specification header can escape the corrections directory

`Specification.specification` is an unconstrained string. `ast.spec_ref()`
removes a prefix and spaces but does not validate that the result is a
single safe filename (`src/seanchai/dad/ast.py:218-232`). `corrections.load()`
then joins that value to the explicitly supplied corrections directory and
executes the resulting Python module
(`src/seanchai/dad/corrections.py:290-307`).

A parsed file with `; Specification: ../outside` therefore loads
`../outside.py` if it exists. An absolute value can discard the corrections
directory entirely. This violates the CLI's promise that it executes Python
from the directory the user named.

Turn specification-to-reference conversion into validation, not string
cleanup. It should accept only canonical supported forms, return a basename
matching `SpecRef`, and reject path separators, `.`/`..` components and
absolute paths. As a second boundary, resolve the candidate and verify that its
parent is exactly the resolved corrections directory before importing it.

Tests should cover relative traversal, absolute paths, both platform separator
styles, malformed specification names and a valid TS reference.

## 3. Correction loading can silently do no work

`corrections.load()` returns an empty list when the expected module is absent
(`src/seanchai/dad/corrections.py:298-302`). That behavior is convenient for
batch extraction, but it is dangerous for `seanchai correct`, where the user
has explicitly requested correction: a mistyped or missing module produces a
successful "corrected" output with no correction and no notice.

The loader also accepts any iterable while its error says `CORRECTIONS` must
be a list. `all(...)` consumes a generator, after which `list(corrections)`
returns an empty list (`src/seanchai/dad/corrections.py:308-313`). Syntax
errors and exceptions raised while importing a correction module are not
translated to `CorrectionError`.

Give the two callers distinct semantics. `extract --corrections` may allow a
spec with no module when running a mixed corpus, preferably with an explicit
report. `correct --corrections` should require a matching module and at least
one correction. Require a concrete list or tuple, validate it without
consuming it twice, and wrap loader/import failures with the module path.

The correction module docstring still uses the old fictional
`MME-Location-Information` 1600 → 1602 example
(`src/seanchai/dad/corrections.py:15-26`). The implemented design document
already replaced that example because it contradicted the committed corpus;
the source docstring should use the real VCSG example too.

## 4. Library and CLI error boundaries are still inconsistent

The parser's error type has improved, but the end-to-end contracts remain
incomplete.

The downloader module says it raises `DownloadError`
(`src/seanchai/downloader/__init__.py:1-13`), yet catalog loading, HTTP
requests, archive validation and several helpers still raise `OSError`,
`TOMLDecodeError`, `ValueError` or `RuntimeError`. Most worker failures are
wrapped, but URL discovery happens before the worker-result wrapper
(`src/seanchai/downloader/__init__.py:376-412`). A discovery network failure
therefore escapes `download_corpus()` as `RuntimeError`. The CLI loads the
catalog before its `try` block and catches only `DownloadError`
(`src/seanchai/__init__.py:139-161`), so these failures become tracebacks.

The extraction and correction commands have the same user-facing problem.
`extract` preserves warnings with `finally` but does not translate
`ExtractionError`; `correct` does not translate `DadParseError` or
`CorrectionError` (`src/seanchai/__init__.py:53-67`, `85-110`). A malformed
`.dad` currently gives exit code 1 with no Click-formatted stderr under
`CliRunner`, and a normal console invocation can show a traceback.

The extractor's documented hierarchy is also still porous. Invalid encryption
or M-bit cells can raise `KeyError`; invalid codes and AST fields can raise
`ValueError` or pydantic errors; malformed table widths can reach list indexes
before the width check (`src/seanchai/extractor/tgpp_docx.py:353-405`,
`416-435`, `499-518`).

Use one exception boundary per library operation:

- `parse()` always raises `DadParseError`;
- extraction and page attachment always raise `ExtractionError`;
- correction loading/application always raises `CorrectionError`; and
- `download_corpus()` always raises `DownloadError`.

The CLI can then catch those four types and raise `click.ClickException`,
without broadly hiding programming errors. Add failing CLI tests that assert a
useful `Error: ...` message, not only a nonzero exit code.

## 5. The AST still permits non-round-trippable or contradictory states

The empty-table case is fixed, but the broader earlier finding remains.

- `AvpRule(min_occurs=5, max_occurs=2)` is accepted even though the occurrence
  range is inverted (`src/seanchai/dad/ast.py:57-67`).
- The same AVP flag can appear in `must` and `may`, or in any other conflicting
  combination (`src/seanchai/dad/ast.py:147-153`).
- Free string fields written into the line-oriented format—specification name,
  enum description and table label—accept embedded newlines. Formatting such
  a model produces text that does not parse back, and a specification newline
  can inject another directive (`src/seanchai/dad/ast.py:107-113`,
  `173-209`, `227-233`).

Add a shared constrained single-line string where the format requires one,
validate occurrence ordering, and require the four flag-rule sets to be
disjoint. Targeted boundary tests are sufficient, though this model is also a
good candidate for property-based `parse(format_spec(spec)) == spec` testing.

## 6. Enumerated vendor resolution can silently discard information

The 3GPP extractor derives an enumerated AVP's vendor id from grouped AVP
headers. Exactly one candidate is treated as resolved; zero or multiple
candidates silently become `None`
(`src/seanchai/extractor/tgpp_docx.py:560-580`). That contradicts `_Resolved`'s
own statement that every enumerated AVP has a vendor id
(`src/seanchai/extractor/tgpp_docx.py:486-496`).

For a local enumerated AVP in the 3GPP extractor, an absent or ambiguous vendor
is a resolution failure, not a meaningful vendor-less result. Raise an
`ExtractionError` with the candidate set and cover the zero-, one- and
multiple-vendor cases.

## 7. Re-used table source metadata is still attributed to the AVP table

Collection stores a re-used table's rows and caption but discards the section
where it was found (`src/seanchai/extractor/tgpp_docx.py:476-481`,
`513-518`). Assembly then assigns the main AVP table's section to the
`ReusedAvps` block (`src/seanchai/extractor/tgpp_docx.py:592-602`).

Current fixtures place both tables under the same parent clause, which hides
the defect. Preserve the re-used table's section in `_Collected`/`_Resolved`
and add a test with the two tables in different sections.

## 8. Correction selectors cannot express every identity they describe

`definition.application_id` uses `None` both as "do not filter" and as a real
application-id value (`src/seanchai/dad/corrections.py:66-92`). It cannot
select specifically the omitted-ID definition when another definition with
the same name has an application id.

`avp_rule(parent, name)` similarly has no way to distinguish the same command
defined for two applications (`src/seanchai/dad/corrections.py:145-161`), even
though multi-application command sections are an explicitly supported 29.272
case.

Use a private sentinel for "not specified" and let `application_id=None`
mean an explicit filter. Give `avp_rule` the same parent discriminator, or
compose it with a `definition` selector rather than duplicating an incomplete
parent identity.

## 9. Correction tests prove reproducibility, not correctness

The committed-correction test loads each correction, applies it to raw output,
counts results and checks that the result round-trips
(`tests/test_corrections.py:229-243`). This is a useful rot test, but the
expected replacement is read from the correction being tested. Changing a
wrong `expect`, `replace` and reason together can keep the test green.

Until the linter and independent-oracle validation exist, pin the intended
semantic diff separately: for TS 29.272, assert that exactly the four named
VCSG messages change from `None` to `16777308` and that no other field changes.
A committed corrected golden file is another option if the corpus layout is
settled.

The advertised `reused_row` selector has no direct test, and the suite also
needs the loader, path-safety, missing-module, explicit-`None` and
ancestor/descendant cases described above.

## 10. Downloader integrity work remains more urgent than downloader features

Moving the downloader did not fix its known data-integrity problems, which are
accurately listed in `docs/downloader.md:27-43`:

- nonempty cached ZIP and RFC files are accepted without validation;
- a bad cached PDF remains when replacement validation fails;
- a `%PDF-` prefix is not enough to establish a complete PDF; and
- extracting a new archive into the same specification directory leaves stale
  files from the previous version.

There is another ordering assumption in URL discovery: when an index contains
multiple matching archives, `matches[-1]` is chosen
(`src/seanchai/downloader/__init__.py:135-155`). The test puts the newer link
last, so it verifies HTML order rather than selection of the maximum decoded
version.

Before link derivation or more downloader restructuring:

- validate fresh and cached ZIPs with `ZipFile.testzip()`;
- apply a plausible RFC-text check;
- validate PDFs by opening them, not only by prefix;
- download/extract into version-specific directories or atomically replace a
  staged directory; and
- choose the maximum decoded archive version independently of listing order.

The planned switch from `latest/Rel-N` to the version-preserving archive is
also a prerequisite for the documented raw-vs-raw upgrade workflow, not merely
a convenience.

## 11. Page and parser diagnostics are correct in type but imprecise in place

`attach_pages()` says the first matching outline entry wins, but assignment to
the page map overwrites an earlier duplicate, so the last entry wins
(`src/seanchai/extractor/tgpp_docx.py:667-700`). Use `setdefault` if the
documented behavior is intended and test duplicate bookmarks.

The parser now translates model failures correctly, but it usually reports the
start of the section block rather than the line holding the invalid value. For
example, an invalid `; Page:` on line 7 reports line 4 because directives are
reduced to a `dict[str, str]` and their source lines are discarded
(`src/seanchai/dad/parser.py:73-89`, `130-136`, `343-349`). The new tests
explicitly pin that coarse line.

Retain directive line numbers in the intermediate representation and associate
row-model validation with the row line. Strict errors are most useful when
they point at the value to edit.

## 12. Architecture cleanup should follow the integrity fixes

The CLI has grown to three commands and helper functions inside the top-level
package `__init__.py` (`src/seanchai/__init__.py`). Move it to `cli.py` and
point the console entry point there; keep `__init__.py` for a deliberately
small public surface.

The downloader move similarly put a 451-line HTTP, cache, ZIP, manifest and
thread-pool implementation in `src/seanchai/downloader/__init__.py`. A
`core.py` plus explicit exports would make the library boundary clearer.
Further splitting should follow real seams—artifact validation and corpus
orchestration are already two—not file length alone.

The formatter still uses `singledispatch` and then rejects its inheritance
semantics with an exact-registry check
(`src/seanchai/dad/formatter.py:69-71`, `193-204`). For a closed,
discriminated five-type union, direct explicit dispatch would be simpler and
would remove the unusually long explanation and two tests around a
hypothetical subclass.

No broad split of `tgpp_docx.py` is justified solely because it is long. Its
collect → resolve → assemble phases are coherent. Fix their error and metadata
contracts before moving them into more files.

## 13. Documentation, configuration and packaging need a small consistency pass

The documentation currently gives two incompatible accounts of corrected
output. README and `docs/workflow.md` call corrected `.dad` files the source of
truth, while `docs/corrections.md:130-133` says none are committed and
their location is undecided. If raw file plus correction module is the durable
source and corrected `.dad` is generated output, say that consistently.

Now that corrections are implemented, `corrections.md` should be
renamed to `corrections.md`. `plan-code-quality.md` is a useful implementation
record, but README and roadmap still call it current planned work. Move it to a
history/decision register or update those references. The "working on these
documents" section of `development.md` also says the plan contains scheduled
work, which is no longer true.

The type-checker configuration still includes the deleted top-level
`downloader` directory (`pyproject.toml:43-50`). Remove that stale include.

The built wheel contains the catalog as intended, but it has no `py.typed`
marker. Add one before presenting the annotated AST and correction API as a
typed downstream library. Python `>=3.14` also appears stricter than the
features used; either document the reason or lower it to the real supported
minimum before external adoption.

Most source comments are not overcommented. The extractor's spec-and-clause
notes carry valuable evidence and should stay. The formatter dispatch rationale
and repeated meta-policy/changelog prose are the main places where explanation
has grown larger than the mechanism it protects.

The deliberate no-CI decision is not reopened here. The current local checks
are healthy; the decision should simply be revisited if releases or external
contributors make an unenforced local-only acceptance criterion costly.

## Recommended order

The safest implementation order is:

1. fix correction ancestor/descendant rebuilding and correction-path
   containment;
2. make correction loading explicit and close the library/CLI exception
   boundaries;
3. finish AST invariants, vendor resolution and re-used-table provenance;
4. add independent correction-diff tests, then implement the single-file
   linter already at the top of the roadmap;
5. fix downloader validation, version selection and extraction isolation;
6. correct bookmark/line diagnostics; and
7. finish with CLI/package layout and documentation/configuration cleanup.

Every item can preserve the current canonical output for the committed examples
except deliberate correction results. The existing command set remains the
right regression baseline:

```sh
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check
uv run basedpyright
uv build
```
