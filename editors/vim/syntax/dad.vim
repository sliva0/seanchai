" Vim syntax file
" Language: Diameter AVP Dictionary (.dad) — see docs/grammar.md

if exists('b:current_syntax')
  finish
endif

" Table-row tokens (token-based: which vocabulary a cell uses depends on the
" `; Columns:` declaration, which a regex highlighter cannot track; these
" vocabularies barely collide in practice).
" Integers must stand alone as a token (delimited by whitespace, comma or
" line edge) — the 256 in SHA-256-Indication is part of a name, not a number.
" Dotted identifiers (section numbers like 6.3.7A or E.6.3.6, versions like
" 18.6.0) are references, not floats, and get their own group.
syn match dadNumber "\%(^\|[ ,]\)\@<=\d\+\%([ ,]\|$\)\@="
syn match dadSection "\%(^\|\s\)\@<=\%(\d\+[A-Za-z]*\|[A-Za-z]\)\%(\.\d\+[A-Za-z]*\)\+\%(\s\|$\)\@="
" Cell keywords must stand alone as a whole cell (delimited by whitespace, or
" a comma for spec-refs in `; Bases:` lists) — a type name embedded in a
" longer AVP name like MIP-Home-Agent-Address is not a type.
syn match dadSpecRef "\%(^\|[ ,]\)\zs\%(TS\d\{2,3}\.\d\{3}\|RFC\d\+\|[A-Z]\.[A-Z]\d\{4}\)\ze\%([ ,]\|$\)"
syn match dadDataType "\%(^\|\s\)\zs\%(OctetString\|Integer32\|Integer64\|Unsigned32\|Unsigned64\|Float32\|Float64\|Grouped\|Address\|Time\|UTF8String\|DiameterIdentity\|DiameterURI\|Enumerated\|IPFilterRule\|QoSFilterRule\)\ze\%(\s\|$\)"
syn match dadCellConst "\%(^\|\s\)\zs\%(MUST-NOT\|MUST\|Yes\|No\)\ze\%(\s\|$\)"
syn match dadFlagCell "\%(^\|\s\)\zs[MVP]\%(,\s\?[MVP]\)*\ze\%(\s\|$\)"
syn match dadEmptyCell "\%(^\|\s\)\zs-\ze\%(\s\|$\)"

" Header and body rules
syn match dadDefine " ::= "
syn match dadHeaderKw "Diameter Header\|Enumerated AVP header\|AVP header"
syn match dadCmdFlag "\<\%(REQ\|PXY\|ERR\)\>"
syn match dadMsgName "^<\zs[A-Za-z0-9][A-Za-z0-9_-]*\ze> ::="
syn match dadMsgName "^[A-Za-z0-9][A-Za-z0-9_-]*\ze ::="

" The bracket pair carries the presence: <> fixed, {} required, [] optional.
" A `;;` comment may end any line, so the rules tolerate one.
syn match dadAvpRuleFixed "^\s*\%(\d*\*\d*\s*\)\?< [A-Za-z0-9][A-Za-z0-9_-]* >\%(\s*; bold\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpFixed,dadBold,dadComment
syn match dadAvpRuleRequired "^\s*\%(\d*\*\d*\s*\)\?{ [A-Za-z0-9][A-Za-z0-9_-]* }\%(\s*; bold\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpRequired,dadBold,dadComment
syn match dadAvpRuleOptional "^\s*\%(\d*\*\d*\s*\)\?\[ [A-Za-z0-9][A-Za-z0-9_-]* \]\%(\s*; bold\)\?\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpOptional,dadBold,dadComment
syn match dadOccur "\d*\*\d*" contained
syn match dadBracket "[<>{}[\]]" contained
syn match dadAvpFixed "[A-Za-z0-9][A-Za-z0-9_-]*" contained
syn match dadAvpRequired "[A-Za-z0-9][A-Za-z0-9_-]*" contained
syn match dadAvpOptional "[A-Za-z0-9][A-Za-z0-9_-]*" contained
syn match dadBold "; bold" contained

" Classic Vim cannot layer a bold attribute over syntax colors, so `; bold`
" lines get a dedicated bold-only name group there (defined after the normal
" rules, so it wins). Neovim keeps the colored groups and adds bold
" additively via extmarks in ftplugin/dad.lua.
if !has('nvim')
  syn match dadAvpRuleFixedB "^\s*\%(\d*\*\d*\s*\)\?< [A-Za-z0-9][A-Za-z0-9_-]* >\s*; bold\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpBoldName,dadBold,dadComment
  syn match dadAvpRuleRequiredB "^\s*\%(\d*\*\d*\s*\)\?{ [A-Za-z0-9][A-Za-z0-9_-]* }\s*; bold\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpBoldName,dadBold,dadComment
  syn match dadAvpRuleOptionalB "^\s*\%(\d*\*\d*\s*\)\?\[ [A-Za-z0-9][A-Za-z0-9_-]* \]\s*; bold\s*\%(;;.*\)\?$" contains=dadOccur,dadBracket,dadAvpBoldName,dadBold,dadComment
  syn match dadAvpBoldName "[A-Za-z0-9][A-Za-z0-9_-]*" contained
  hi def dadAvpBoldName term=bold cterm=bold gui=bold
endif

" Enumerated AVP body
" A value name is an identifier or a quoted string; `#` delimits the
" patterns because they contain the double quote.
syn match dadEnumLine #^\s*\%([A-Za-z0-9][A-Za-z0-9_-]*\|"[^"]*"\)\s*= \d\+\%(\s\+;.*\)\?$# contains=dadEnumName,dadNumber,dadEnumNote,dadComment
syn match dadEnumName #^\s*\zs\%([A-Za-z0-9][A-Za-z0-9_-]*\|"[^"]*"\)# contained
syn match dadEnumNote "; .*$" contained
syn match dadReserved "^\s*; RESERVED\s*= \d\+\%(-\d\+\)\?\s*\%(;;.*\)\?$" contains=dadReservedKw,dadNumber,dadRange,dadComment
syn match dadReservedKw "; RESERVED" contained
syn match dadRange "\d\+-\d\+" contained

" Directives
syn match dadDirectiveLine "^; [A-Za-z][A-Za-z-]*: .*$" contains=dadDirectiveKey,dadDirectiveValue
syn match dadDirectiveKey "^; \zs[A-Za-z][A-Za-z-]*\ze:" contained
syn match dadDirectiveValue ": \zs.*$" contained contains=dadTypeValue,dadSpecRef,dadSection,dadNumber,dadLink,dadComment
syn match dadTypeValue "\%(Application\|Message\|Grouped AVP\|Enumerated AVP\|AVP Table\|Reused AVPs\)$" contained
syn match dadLink "https\?://\S\+" contained

" Free-text directives get one uniform value color — no point picking the
" 29.109 out of "3GPP TS 29.109". Defined after the generic line, so it wins.
syn match dadDirectiveTextLine "^; \%(Specification\|Name\|Table\|Values\): .*$" contains=dadDirectiveKey,dadDirectiveText
syn match dadDirectiveText ": \zs.*$" contained contains=dadComment

" Free-text comments override everything else on the line
syn match dadComment ";;.*$"

hi def link dadComment        Comment
hi def link dadDirectiveKey   Keyword
hi def link dadDirectiveValue String
hi def link dadTypeValue      Type
hi def link dadLink           Underlined
hi def link dadDirectiveText  String
hi def link dadSpecRef        Tag
hi def link dadNumber         Number
hi def link dadRange          Number
hi def link dadSection        Constant
hi def link dadDataType       Type
hi def link dadCellConst      Boolean
hi def link dadFlagCell       Constant
hi def link dadEmptyCell      Delimiter
hi def link dadDefine         Operator
hi def link dadHeaderKw       Keyword
hi def link dadCmdFlag        Constant
hi def link dadMsgName        Function
hi def link dadBracket        Delimiter
hi def link dadAvpFixed       Special
hi def link dadAvpRequired    Function
hi def link dadAvpOptional    Identifier
hi def link dadOccur          Operator
hi def link dadBold           SpecialComment
hi def link dadEnumName       Identifier
hi def link dadEnumNote       String
hi def link dadReservedKw     Keyword

let b:current_syntax = 'dad'
