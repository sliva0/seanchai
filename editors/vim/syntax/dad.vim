" Vim syntax file
" Language: Diameter AVP Dictionary (.dad) — see docs/grammar.md

if exists('b:current_syntax')
  finish
endif

" Defined first, so that every token defined after it wins where both
" match: the names in an interpreted constraint's rule, of a member, a sibling
" or a value.
syn match dadConstraintName "\%(^    \S\+ .\{-}\)\@<=[A-Za-z0-9][A-Za-z0-9_-]*" contained

" Table-row tokens are matched one by one: a cell's vocabulary depends on the
" `; Columns:` line, which a regex highlighter cannot track, and the
" vocabularies rarely collide.
" An integer must be a whole token (bounded by whitespace, a comma or the line
" edge), so the 256 in SHA-256-Indication stays part of the name.
" Dotted identifiers (sections like 6.3.7A or E.6.3.6, versions like 18.6.0)
" are references and get their own group.
syn match dadNumber "\%(^\|[ ,]\)\@<=\d\+\%([ ,]\|$\)\@="
syn match dadSection "\%(^\|\s\)\@<=\%(\d\+[A-Za-z]*\|[A-Za-z]\)\%(\.\d\+[A-Za-z]*\)\+\%(\s\|$\)\@="
" Cell keywords must stand alone as a whole cell (delimited by whitespace, or
" a comma for spec-refs in `; Bases:` lists) — a type name embedded in a
" longer AVP name like MIP-Home-Agent-Address is not a type.
" A spec-ref looks behind for its delimiter rather than matching it: a
" directive's value starts after the space, which a match inside it cannot
" take, so the first entry of `; Bases: RFC6733, TS29.229` would be missed.
syn match dadSpecRef "\%(^\|[ ,]\)\@1<=\%(TS\d\{2}\.\d\{3}\|RFC\d\+\|ETSI-\%(TS\|ES\)\d\{3}\.\d\{3}\%(-\d\+\)\=\|3GPP2-[A-Z]\.[A-Z]\d\{4}\%(-\d\{3}\)\=\|OMA\%(-[A-Za-z0-9_]\+\)\+\|oneM2M-TS-\d\{4}\|Private-[A-Za-z0-9][A-Za-z0-9_.-]*\)\%([ ,]\|$\)\@="
syn match dadDataType "\%(^\|\s\)\zs\%(OctetString\|Integer32\|Integer64\|Unsigned32\|Unsigned64\|Float32\|Float64\|Grouped\|Address\|Time\|UTF8String\|DiameterIdentity\|DiameterURI\|Enumerated\|IPFilterRule\|QoSFilterRule\)\ze\%(\s\|$\)"
syn match dadCellConst "\%(^\|\s\)\zs\%(MUST-NOT\|MUST\|Yes\|No\)\ze\%(\s\|$\)"
syn match dadFlagCell "\%(^\|\s\)\zs[MVP]\%(,\s\?[MVP]\)*\ze\%(\s\|$\)"
syn match dadEmptyCell "\%(^\|\s\)\@1<=-\%(\s\|$\)\@="
" A mark that is not a plain token is quoted, as enum value names are
" (`"All (NOTE 5)"`); `""` is a blank mark cell.
syn match dadQuotedCell #"\%([^"\\]\|\\["\\]\)*"#

" Header and body rules: a command's `<Name> ::= < Diameter Header: 316, REQ,
" PXY, 16777251 >` and an AVP's `Name ::= < AVP header: 1400 10415 >`. The
" command flags are words only there: a registry row's `ERR/ERA` is no flag.
syn match dadMsgHeader "^<[A-Za-z0-9][A-Za-z0-9_-]*> ::= < Diameter Header:[^>]*>" contains=dadMsgName,dadDefine,dadHeaderKw,dadHeaderColon,dadCmdFlag,dadNumber,dadHeaderAngle
syn match dadAvpHeader "^[A-Za-z0-9][A-Za-z0-9_-]* ::= < \%(Enumerated \)\=AVP header:[^>]*>" contains=dadMsgName,dadDefine,dadHeaderKw,dadHeaderColon,dadNumber,dadHeaderAngle
syn match dadDefine " ::= " contained
syn match dadHeaderKw "Diameter Header\|Enumerated AVP header\|AVP header" contained
syn match dadHeaderColon "\%(Header\|header\)\@<=:" contained
syn match dadHeaderAngle "[<>]" contained
syn match dadCmdFlag "\<\%(REQ\|PXY\|ERR\)\>" contained
syn match dadMsgName "\%(^<\)\@1<=[A-Za-z0-9][A-Za-z0-9_-]*\ze> ::=" contained
syn match dadMsgName "^[A-Za-z0-9][A-Za-z0-9_-]*\ze ::=" contained

" The bracket pair carries the presence: <> fixed, {} required, [] optional.
" A `;;` comment may end any line, so the rules tolerate one.
syn match dadAvpRuleFixed "^\s*\%(\d*\*\d*\s*\)\?< [A-Za-z0-9][A-Za-z0-9_-]* >\%(\s*; bold\)\?\%(\s*; strikethrough\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpFixed,dadBold,dadStrike,dadComment
syn match dadAvpRuleRequired "^\s*\%(\d*\*\d*\s*\)\?{ [A-Za-z0-9][A-Za-z0-9_-]* }\%(\s*; bold\)\?\%(\s*; strikethrough\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpRequired,dadBold,dadStrike,dadComment
syn match dadAvpRuleOptional "^\s*\%(\d*\*\d*\s*\)\?\[ [A-Za-z0-9][A-Za-z0-9_-]* \]\%(\s*; bold\)\?\%(\s*; strikethrough\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpOptional,dadBold,dadStrike,dadComment
syn match dadOccur "\d*\*\d*" contained
syn match dadBracket "[<>{}[\]]" contained
syn match dadAvpFixed "\%(< \)\@2<=[A-Za-z0-9][A-Za-z0-9_-]*" contained
syn match dadAvpRequired "\%({ \)\@2<=[A-Za-z0-9][A-Za-z0-9_-]*" contained
syn match dadAvpOptional "\%(\[ \)\@2<=[A-Za-z0-9][A-Za-z0-9_-]*" contained
syn match dadBold "; bold" contained
syn match dadStrike "; strikethrough" contained

" Classic Vim cannot layer a bold attribute over syntax colors, so `; bold`
" lines get a dedicated bold-only name group there (defined after the normal
" rules, so it wins). Neovim keeps the colored groups and adds bold
" additively via extmarks in ftplugin/dad.lua.
if !has('nvim')
  syn match dadAvpRuleFixedB "^\s*\%(\d*\*\d*\s*\)\?< [A-Za-z0-9][A-Za-z0-9_-]* >\s*; bold\%(\s*; strikethrough\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpBoldName,dadBold,dadStrike,dadComment
  syn match dadAvpRuleRequiredB "^\s*\%(\d*\*\d*\s*\)\?{ [A-Za-z0-9][A-Za-z0-9_-]* }\s*; bold\%(\s*; strikethrough\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpBoldName,dadBold,dadStrike,dadComment
  syn match dadAvpRuleOptionalB "^\s*\%(\d*\*\d*\s*\)\?\[ [A-Za-z0-9][A-Za-z0-9_-]* \]\s*; bold\%(\s*; strikethrough\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpBoldName,dadBold,dadStrike,dadComment
  syn match dadAvpBoldName "\%([<{[] \)\@2<=[A-Za-z0-9][A-Za-z0-9_-]*" contained
  hi def dadAvpBoldName term=bold cterm=bold gui=bold
endif

" Enumerated AVP body
" A value name is an identifier or a quoted string, inside which \" and \\
" are escapes; `#` delimits the patterns because they contain the double
" quote.
syn match dadEnumLine #^\s*\%([A-Za-z0-9][A-Za-z0-9_-]*\|"\%([^"\\]\|\\["\\]\)*"\)\s*= \d\+\%(\s\+;.*\)\?$# contains=dadEnumName,dadAssign,dadNumber,dadEnumNote,dadComment
syn match dadEnumName #^\s*\zs\%([A-Za-z0-9][A-Za-z0-9_-]*\|"\%([^"\\]\|\\["\\]\)*"\)# contained
" The note ends where a `;;` comment starts; a value table's `from TS29.229`
" names the document defining the code.
syn match dadEnumNote "\s\@1<=; [^;].\{-}\ze\%(\s*;;.*\)\=$" contained contains=dadFrom
syn match dadFrom "\s\@1<=from \S\+\%(\s\|$\)\@=" contained contains=dadFromKw,dadSpecRef
syn match dadFromKw "from" contained
syn match dadAssign "=" contained
syn match dadReserved "^\s*; RESERVED\s*= \d\+\%(-\d\+\)\?\s*\%(;;.*\)\?$" contains=dadReservedKw,dadAssign,dadNumber,dadRange,dadComment
" A registry's reserved range: `; RESERVED 320..399 TS29.234 "TS 29.234"`.
syn match dadRegistryReserved #^; RESERVED \d\+\.\.\d\+\%( [^ "]\+\)\?\%( "\%([^"\\]\|\\["\\]\)*"\)\?\s*\%(;;.*\)\?$# contains=dadReservedKw,dadRange,dadSpecRef,dadListComma,dadQuotedCell,dadComment
syn match dadReservedKw "; RESERVED" contained
" A value the document withdrew: `; VOID = 0`.
syn match dadVoid "^\s*; VOID\s*= \d\+\%(-\d\+\)\?\s*\%(;;.*\)\?$" contains=dadVoidKw,dadAssign,dadNumber,dadRange,dadComment
syn match dadVoidKw "; VOID" contained
" A range left to vendors: `; VENDOR-SPECIFIC = 100-199 ; Vendor specific SM services`.
syn match dadVendorSpecific "^\s*; VENDOR-SPECIFIC\s*= \d\+\%(-\d\+\)\?\%(\s\+; [^;].\{-}\)\?\s*\%(;;.*\)\?$" contains=dadVendorSpecificKw,dadAssign,dadNumber,dadRange,dadVendorSpecificNote,dadComment
syn match dadVendorSpecificKw "; VENDOR-SPECIFIC" contained
syn match dadVendorSpecificNote "\%(\d\s\+\)\@<=; [^;].\{-}\ze\s*\%(;;.*\)\?$" contained
syn match dadRange "\d\+\%(-\|\.\.\)\d\+" contained contains=dadRangeNumber,dadRangeOp
syn match dadRangeNumber "\d\+" contained
syn match dadRangeOp "-\|\.\." contained

" Interpreted constraints: a quote line, then the rules read from it, each
" indented four spaces under a keyword of the closed set.
syn match dadConstraintQuote #^"\%([^"\\]\|\\["\\]\)*"\s*\%(;;.*\)\?$# contains=dadQuote,dadComment
syn match dadQuote #^"\%([^"\\]\|\\["\\]\)*"# contained
" The names in a constraint's rule, of a member, a sibling or a value (see
" `dadConstraintRule`).
syn match dadConstraintRule "^    \%(length\|range\|exclude\|encoding\|present-if\|absent-if\|requires\|excludes\|default\|bits\|members\|unique\|values\|equals\|text-only\)\>.*$" contains=dadConstraintName,dadConstraintRoot,dadConstraintPath,dadConstraintKw,dadConstraintWord,dadConstraintOp,dadListComma,dadCodec,dadUnit,dadSpecRef,dadSection,dadElementClause,dadConstraintNumber,dadQuotedCell,dadComment
syn match dadConstraintKw "^    \zs\%(length\|range\|exclude\|encoding\|present-if\|absent-if\|requires\|excludes\|default\|bits\|members\|unique\|values\|equals\|text-only\)\>" contained
" A path's root, the request an answer answers, and the `/` between its
" names.
syn match dadConstraintRoot "\s\@1<=request\ze/" contained
syn match dadConstraintPath "/" contained
syn match dadConstraintWord "\s\zs\%(or\|if\|bit\|at-most-one\|at-least-one\|set\|clear\|only\)\ze\s" contained
syn match dadConstraintOp "\.\.\|\%(\s\|\.\.\)\@2<=\*\|\s\@1<==\ze\s" contained
" A codec after `encoding`, a length's unit after its bounds.
syn match dadCodec "\%(encoding \)\@9<=\%(e164-tbcd\|plmn-id-prefix\|plmn-id\|digits\|labels\|apn\|epc-plmn-domain\|plmn-domain\|ip-address\|time-zone\|mac-address\|element\)\ze\%(\s\|$\)" contained
syn match dadUnit "\%([0-9*] \)\@2<=\%(octets\|digits\|characters\)\ze\s*\%(;;.*\)\=$" contained
" An element's clause, after its document: an annex's letter alone too.
syn match dadElementClause "\%(^    encoding element \S\+ \)\@<=\%(\d\+[A-Za-z]*\|[A-Za-z]\+\)\%(\.\d\+[A-Za-z]*\)*\ze\%(\s\|$\)" contained
syn match dadConstraintNumber "\%(\s\|\.\.\)\@2<=-\?\d\+\ze\%(\s\|$\|\.\.\|,\)" contained

" Directives
syn match dadDirectiveLine "^; [A-Za-z][A-Za-z-]*: .*$" contains=dadDirectiveKey,dadDirectiveValue
syn match dadDirectiveKey "^; \zs[A-Za-z][A-Za-z-]*\ze:" contained
syn match dadDirectiveValue ": \zs.*$" contained contains=dadTypeValue,dadValueKind,dadSpecRef,dadSection,dadClauseWildcard,dadVersionRange,dadListComma,dadNumber,dadLink,dadComment
" A block's `; Type:`, a registry's kind: the whole value, a `;;` comment
" after it.
syn match dadTypeValue "\%(: \)\@2<=\%(Application Scope\|Message\|Answer Message\|Grouped AVP\|Enumerated AVP\|AVP Table\|Reused AVPs\|Registry\|Undefined AVP\|Value Table\|Information Elements\|Command Result Codes\|Interpreted Constraints\|Application IDs\|Command Codes\|AVP Codes\|Result Codes\)\ze\s*\%(;;.*\)\=$" contained
" `; Kind:` of a value table, whose rows read as enum values do.
syn match dadValueKind "\%(: \)\@2<=\%(result-codes\|bits\|features\|values\)\ze\s*\%(;;.*\)\=$" contained
syn match dadLink "https\?://\S\+" contained
" `; Applies-To:` entries: a clause and its subclauses, `5.*`, `E.6.*`.
syn match dadClauseWildcard "\%(^\|[ ,]\)\@<=\%(\d\+[A-Za-z]*\|[A-Za-z]\+\)\%(\.\d\+[A-Za-z]*\)*\.\*\%([ ,]\|$\)\@=" contained
" `; Versions:` a range of versions, `18.7.0..19.6.0`, a bound `*` where it is
" open.
syn match dadVersionRange "\%(^\|[ ,]\)\@1<=\%(\d\+\%(\.\d\+\)\+\|\*\)\.\.\%(\d\+\%(\.\d\+\)\+\|\*\)\%([ ,]\|$\)\@=" contained contains=dadVersionBound,dadVersionOpen,dadVersionDots
syn match dadVersionBound "\d\+\%(\.\d\+\)\+" contained
syn match dadVersionOpen "\*" contained
syn match dadVersionDots "\.\." contained
" The comma between a list's entries, `; Applies-To: 5.1.*, 5.2.*`.
syn match dadListComma "," contained

" Free-text directives get one uniform value color — no point picking the
" 29.109 out of "3GPP TS 29.109". Defined after the generic line, so it wins.
syn match dadDirectiveTextLine "^; \%(Specification\|Interprets\|Name\|Table\|Values\|Note\): .*$" contains=dadDirectiveKey,dadDirectiveText
syn match dadDirectiveText ": \zs.*$" contained contains=dadComment

" Free-text comments override everything else on the line. A note the
" corrections layer or the extractor writes names its kind and the
" declaration: `;; corrected: (TS29.272.py#area-scope-code)`, `;; interpreted:
" (TS29.272.dadx#imei-digits)`, `;; excluded: clause 8 (Sh-ee), see
" TS29.329.toml`.
syn match dadComment ";;.*$" contains=dadNoteKw,dadNoteRef
syn match dadNoteKw "\%(;; \)\@3<=\%(corrected\|deleted\|excluded\|foreword\|inserted\|interpreted\|patched\|supplied\)\ze:" contained
syn match dadNoteRef "(\@1<=[A-Za-z0-9_.+-]\+\.\%(py\|dadx\)#[A-Za-z0-9_.-]\+\ze)" contained
syn match dadNoteRef "\%(see \)\@4<=[A-Za-z0-9_.+-]\+\.toml\>" contained

" An Information Elements block, up to the next block of another type: its
" rows are the element's name as printed, the AVPs it maps to (`A,B` carried
" together, `A/B` one of them, a quoted cell naming none) and its category,
" M, C or O, TS 32.299's OM and OC, a dash or a blank. A table naming its
" elements by their AVPs alone (`; Columns: AVP Cat`) has no name cell. Either
" row is set off four spaces a level under a grouped AVP's. A re-used AVP
" table's `Name From Must` row has the same shape, so the block, not the
" row, says which it is.
syn cluster dadElementsBody contains=dadComment,dadDirectiveLine,dadDirectiveTextLine,dadElementName,dadElementAvpCell,dadQuotedCell,dadNumber,dadSection,dadSpecRef,dadDataType,dadCellConst,dadFlagCell,dadEmptyCell
syn region dadElements start="^\%(; Type: Information Elements\>\)\@=" end="^\%(; Type: \%(Information Elements\>\)\@!\)\@=" contains=@dadElementsBody
syn match dadElementName #^\s*\zs\%("\%([^"\\]\|\\["\\]\)*"\|[^; "]\S*\)\ze\s\+\%("\%([^"\\]\|\\["\\]\)*"\|\S\+\)\s\+\%(OM\|OC\|[MCO-]\|""\)\s*\%(;;.*\)\=$# contained contains=dadQuotedCell nextgroup=dadElementMap skipwhite
syn match dadElementAvpCell #^\s*\zs\%("\%([^"\\]\|\\["\\]\)*"\|[^; "]\S*\)\ze\s\+\%(OM\|OC\|[MCO-]\|""\)\s*\%(;;.*\)\=$# contained contains=dadQuotedCell,dadElementAvp,dadElementSep,dadEmptyCell nextgroup=dadElementCat skipwhite
syn match dadElementMap #"\%([^"\\]\|\\["\\]\)*"\|\S\+# contained contains=dadQuotedCell,dadElementAvp,dadElementSep,dadEmptyCell nextgroup=dadElementCat skipwhite
syn match dadElementAvp "[A-Za-z0-9][A-Za-z0-9_-]*" contained
syn match dadElementSep "[,/]" contained
syn match dadElementCat #\%(OM\|OC\|[MCO-]\|""\)\ze\s*\%(;;.*\)\=$# contained
" A Command Result Codes block, up to the next block of another type: a code's
" name a line, bare or quoted.
syn region dadResultCodes start="^\%(; Type: Command Result Codes\>\)\@=" end="^\%(; Type: \%(Command Result Codes\>\)\@!\)\@=" contains=dadComment,dadDirectiveLine,dadDirectiveTextLine,dadResultCodeName
syn match dadResultCodeName #^\%("\%([^"\\]\|\\["\\]\)*"\|[A-Za-z0-9][A-Za-z0-9_-]*\)\ze\s*\%(;;.*\)\=$# contained
syn sync match dadElementsSync grouphere dadElements "^; Type: Information Elements\>"
syn sync match dadElementsSync grouphere NONE "^; Type: \%(Information Elements\>\)\@!"
" After the elements' sync, which a Command Result Codes line would end.
syn sync match dadResultCodesSync grouphere dadResultCodes "^; Type: Command Result Codes\>"
syn sync match dadResultCodesSync grouphere NONE "^; Type: \%(Command Result Codes\>\|Information Elements\>\)\@!"

hi def link dadComment        Comment
hi def link dadNoteKw         SpecialComment
hi def link dadNoteRef        Underlined
hi def link dadDirectiveKey   Keyword
hi def link dadDirectiveValue String
hi def link dadTypeValue      Type
hi def link dadValueKind      Constant
hi def link dadLink           Underlined
hi def link dadDirectiveText  String
hi def link dadSpecRef        Tag
hi def link dadNumber         Number
hi def link dadRangeNumber    Number
hi def link dadRangeOp        Operator
hi def link dadSection        Constant
hi def link dadClauseWildcard Constant
hi def link dadVersionBound   Constant
hi def link dadVersionOpen    Operator
hi def link dadVersionDots    Operator
hi def link dadListComma      Delimiter
hi def link dadDataType       Type
hi def link dadCellConst      Boolean
hi def link dadFlagCell       Constant
hi def link dadEmptyCell      Delimiter
hi def link dadDefine         Operator
hi def link dadHeaderKw       Keyword
hi def link dadHeaderColon    Delimiter
hi def link dadHeaderAngle    Delimiter
hi def link dadCmdFlag        Constant
hi def link dadMsgName        Function
hi def link dadBracket        Delimiter
hi def link dadAvpFixed       Special
hi def link dadAvpRequired    Function
hi def link dadAvpOptional    Identifier
hi def link dadOccur          Operator
hi def link dadBold           SpecialComment
hi def link dadStrike         SpecialComment
hi def link dadEnumName       Identifier
hi def link dadResultCodeName Identifier
hi def link dadEnumNote       String
hi def link dadFromKw         Keyword
hi def link dadAssign         Operator
hi def link dadQuotedCell     String
hi def link dadReservedKw     Keyword
hi def link dadVoidKw         Keyword
hi def link dadVendorSpecificKw Keyword
hi def link dadVendorSpecificNote String
hi def link dadQuote          String
hi def link dadConstraintKw   Statement
hi def link dadConstraintWord Operator
hi def link dadCodec          Type
hi def link dadUnit           Constant
hi def link dadConstraintNumber Number
hi def link dadConstraintName Identifier
hi def link dadConstraintRoot Keyword
hi def link dadConstraintPath Delimiter
hi def link dadElementClause  Constant
hi def link dadConstraintOp   Operator
hi def link dadElementAvp     Identifier
hi def link dadElementSep     Delimiter
hi def link dadElementCat     Constant

let b:current_syntax = 'dad'
