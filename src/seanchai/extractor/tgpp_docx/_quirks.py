"""The quirk vocabulary of the docx extractor."""

# The quirk vocabulary this extractor defines, by name, with what declaring it
# enables: readings that would succeed silently on a document they were not
# written for (`sources.py`). Closed vocabularies that cannot be misread stay
# global, such as "Y"/"N" Encrypt cells and 29.338's "Must"/"Must not" M-bit
# short forms.
QUIRKS: dict[str, str] = {
    "prose-avp-origins": (
        "read explicit AVP definition citations in prose as re-used origins,"
        " retaining the citing AVP table's own facts (TS 29.329 6.3.15)"
    ),
    "trailing-result-codes": (
        "read a result code printed as the last sentence of a paragraph, after"
        " the description of the code before it (TS 32.299 V11.20.0 clause"
        " 7.1.11)"
    ),
    "see-result-code-origins": (
        "read a result code's line saying only 'See <doc> [n]', or ending"
        " '(see <doc> [n]).', as naming the document defining the code (TS"
        " 29.329 6.2.2.8, TS 29.273 10.3.2)"
    ),
    "bare-avp-citations": (
        "under prose-avp-origins, read 'See <doc> clause N.' as the whole of an"
        " AVP's clause, and 'for further description of this AVP', as origins"
        " (TS 29.329 6.3.9, 6.3.11-21)"
    ),
    "list-numbered-headings": (
        "number a heading printing no clause number with the number Word's"
        " list numbering renders for it (word/numbering.xml), replayed over"
        " the document (oneM2M TS-0004 annex A)"
    ),
    "message-headings": (
        "read a 'Name message' or 'Name Command' heading over a rule spelled"
        " with the abbreviation ('<ACR> ::=') as the command's long name (TS"
        " 32.299 clauses 6.2.2-6.4.5, oneM2M TS-0004 clauses A.2.1-A.2.2)"
    ),
    "message-tables": (
        "read a table whose first column prints a Diameter header and members"
        " and whose second says if 3GPP uses them, or an 'AVP, Category,"
        " Description' table under a line stating the header, as a 'Name"
        " message' heading's command (TS 32.299 V11.20.0 clauses 6.4.4, 6.4.5)"
    ),
    "placeholder-codes": (
        "keep a registry row whose code cell prints a placeholder rather than"
        " a code, quoted as printed (TS 29.230 V19.3.0 tables 4.1, 5.1/4)"
    ),
    "spaced-rule-operator": (
        "read the rule operator spelled ':: =' as '::=' (TS 32.299 clause 7.2,"
        " TS 29.229)"
    ),
    "struck-rules-unused": (
        "comment out struck-through ABNF members, which the document's legend"
        " says are not used (TS 32.299 clauses 6.2.1.2, 6.4.1.2)"
    ),
    "physical-avp-columns": (
        "read physical cells in an AVP table with ragged grid spans, dropping"
        " an empty trailing sliver cell (TS 32.299 table 7.2.0.1)"
    ),
    "vendor-avp-tables": (
        "read tables of other vendors' AVPs, whose Reference cell cites a"
        " clause-2 entry, as re-used blocks (TS 32.299 tables 7.3.1, 7.4.1,"
        " 7.5.1)"
    ),
    "origins-by-reference": (
        "read a re-used row's From cell printing a TS series 3GPP does not"
        " number ('3GPP TS 283 034 [37]') as the document its clause-2"
        " reference names (TS 29.212, 29.214)"
    ),
    "refer-type-cells": (
        "read a 'refer [n]' Value Type cell as no type plus a re-used row"
        " citing clause 2's reference n (TS 32.299 table 7.2.0.1)"
    ),
    "referred-type-sentences": (
        "type a row whose Value Type cell is 'refer [n]' from its own clause's"
        " sentence 'The Name AVP (AVP code n) is of type T', where the"
        " document has such a clause (TS 32.299 clauses 7.2.50, 7.2.69,"
        " 7.2.191)"
    ),
    "type-short-forms": (
        "read RFC 6733's DiamIdent and DiamURI type abbreviations (TS 32.299"
        " table 7.1.0.1)"
    ),
    "wildcard-avp-row": (
        "read the 'AVP' row with code '*' as the * [ AVP ] wildcard, a note where"
        " it stood and no AVP (TS 32.299 tables 7.1 and 7.1.0.1)"
    ),
    "value-first-enums": (
        "read 'n Label' enumerated values, the label ending at the first"
        " colon and the rest of the line its description (TS 32.299)"
    ),
    "elided-members": (
        "keep a body's lone '…' or '...' line, where a rule leaves out what it"
        " does not change, as a comment where it stood (TS 29.273 clause"
        " 4.2.2.1.1)"
    ),
    "reprinted-avps": (
        "read a grouped rule printed in a procedure clause, under 'The content"
        " of X according IETF RFC n [m] is:', as a re-print of that RFC's rule,"
        " keeping what its members' comments gloss (TS 29.109 clauses 4.2, 5.2"
        " and 5.4)"
    ),
    "abnf-comments": (
        "read an ABNF member line's trailing '; comment' (RFC 5234 section"
        " 3.9) as the member, dropping the comment (TS 29.209 V6.8.0 clauses"
        " 6.5.18 and 6.5.20, TS 29.214 V7.12.0 clauses 5.3.16 and 5.3.18)"
    ),
    "comma-enum-labels": (
        "read a worded enumerated label whose words a comma separates,"
        " 'MM1 Message Submission, Profile based (0)', as the quoted name it"
        " is (TS 29.140 V7.0.0 clause 6.3.5)"
    ),
    "bracketed-enum-values": (
        "read '[n] label' enumerated values, the value bracketed before the"
        " label (TS 32.299 V11.20.0 clause 7.2.101)"
    ),
    "dotted-enum-values": (
        "read 'n. Label' enumerated values, the value followed by a full stop"
        " (TS 32.299 V11.20.0 clauses 7.2.207, 7.2.218)"
    ),
    "list-numbered-enum-values": (
        "read an enumerated value's number from the list numbering Word"
        " renders before its label (word/numbering.xml, replayed), '0"
        " Participating PoC Server' and '1. Moderator' in the PDF (TS 32.299"
        " V11.20.0 clauses 7.2.132, 7.2.145, 7.2.147, 7.2.151)"
    ),
    "value-last-enums": (
        "read 'Label<tab>n' enumerated values, the value last and set off by"
        " a tab or a run of spaces (TS 32.299 V11.20.0)"
    ),
    "prose-application-ids": (
        "read 'the Application-ID for the Gx Application ... is n', 'The"
        " Diameter application identifier assigned to the Sy interface"
        " application is n' and the retired documents' wordings into an"
        " application scope applying to the statement's interface clause (TS"
        " 29.212 clause 5.1, TS 29.219 clause 5.1.5)"
    ),
    "external-enum-values": (
        "read where an enumerated clause says its values are defined ('The"
        " possible values are those defined in TS 32.422 [23] ...') into"
        " `; Values:` (TS 29.061 clause 17.7.25, TS 29.212 clause 5.3.120,"
        " TS 29.272, TS 32.299)"
    ),
    "worded-enum-values": (
        "read 'Label In Words (n)' enumerated values, keeping the label's"
        " spaces (TS 29.368 clause 6.4.6)"
    ),
    "access-type-headings": (
        "read 'Name AVP (All access types)' clause headings, the parenthetical"
        " naming the access types the AVP applies to (TS 29.212 clause 5.3)"
    ),
    "dashed-enum-values": (
        "read '- NAME (n)' enumerated values, a list dash printed as text"
        " (TS 29.272 clause 7.3.128)"
    ),
    "hex-enum-values": (
        "read 'NAME (0xFFFFFFFF)' enumerated values (TS 29.214 clause 5.3.19)"
    ),
    "punctuated-enum-values": (
        "read 'NAME (n),' and 'NAME (n).' enumerated values, dropping the"
        " list's punctuation (TS 29.338 clause 5.3.3.5)"
    ),
    "described-enum-values": (
        "read 'NAME (n) Gloss' enumerated values, the rest of the line the"
        " value's description (TS 29.109 clause 6.3.1.8)"
    ),
    "label-after-enum-value": (
        "read '(n) Label.' enumerated values, labelled after the value (TS"
        " 29.109 clause 6.3.1.13)"
    ),
    "run-on-enum-values": (
        "read several 'NAME (n)' run together in one paragraph (TS 29.229"
        " clause 6.3.58)"
    ),
    "body-clause-headings": (
        "read a body paragraph 'n.n.n Name AVP' as a clause heading (TS 32.299"
        " clause 7.2.135C)"
    ),
    "message-only": (
        "retain commands and re-used AVPs without a local AVP table"
        " (TS 29.330 clause 6.3.1)"
    ),
    "procedure-commands": (
        "read command names and abbreviations from intros under procedure"
        " headings (TS 29.273 clauses 8.2.2.1-4)"
    ),
    "spaced-heading-numbers": (
        "read a heading printing a space before the tab after its number (TS"
        " 29.234 clause 4.5.2.2)"
    ),
    "rfc-command-rules": (
        "name a rule no intro names, under a procedure heading, by its command"
        " code as the RFC defining the command does: '<ASR> ::=', and"
        " '<Diameter-EAP-Request> ::=' (TS 29.234 clauses 4.4.2, 5.5, 8.4,"
        " 9.4, 11.4)"
    ),
    "physical-reused-columns": (
        "read physical cells in a re-used table with ragged grid spans (TS"
        " 29.273 table 8.2.3.0/2)"
    ),
    "independent-avp-tables": (
        "retain AVP and re-used tables independently instead of pairing"
        " them (TS 29.273 clauses 5-11)"
    ),
    "command-reference-only": (
        "accept command clauses containing only a clause reference, with"
        " no definition (TS 29.273)"
    ),
    "note-defined-in-rfc": (
        "derive re-used AVP rows from AVP-table notes reading 'The value of"
        " this attribute is defined in IETF RFC n' (TS 29.229, 29.329,"
        " 29.330)"
    ),
    "dotted-flags": (
        "read a space-less dotted flags cell ('M.V') with the period as the"
        " separator (TS 29.061, 29.212)"
    ),
    "vendor-id-sentence": (
        "read an AVP table's clause saying 'The Vendor-ID header of all AVPs"
        " defined in this specification shall be set to 3GPP (10415).' as V"
        " under Must for the rows whose flag cells are all blank (TS 29.389"
        " clause 6.3.1)"
    ),
    "access-type-column": (
        "read an 'Acc. Type' column's cells as the access types the row"
        " applies to, separated by commas or spaces (TS 29.212 table 5.3.0.1)"
    ),
    "applicability-column": (
        "read an 'Applicability' column's cells as the supported features"
        " (and in TS 29.212 the CC/PC functions) the row is marked with,"
        " separated by commas or spaces (TS 29.212 table 5.3.0.1 notes 3, 9)"
    ),
    "prose-enum-values": (
        "read 'NAME (value n)' in an enumerated clause's sentences as a value"
        " (oneM2M TS-0004 clause A.5.3)"
    ),
    "reference-cells": (
        "read an AVP table's 'Reference' column: a bracketed clause number"
        " ('[A.5.1]') as the row's defining clause, a document ('IETF RFC 6733"
        " [14]') as a re-used row citing it (oneM2M TS-0004 table A.4-1)"
    ),
    "document-clause-cells": (
        "read an AVP table's clause cell naming another document ('3GPP TS"
        " 29.061 [5]') as a re-used row citing it, no clause of the row's own"
        " (TS 29.561 table 12.4-1)"
    ),
    "reference-points-column": (
        "read an 'Applicable Reference Points' column's cells as reference"
        " points, separated by commas (TS 29.061 table 9a)"
    ),
    "worded-marks": (
        "read a mark column's cells as marks separated by commas only, a mark"
        " keeping its spaces (TS 29.468's 'V2X Localized User Plane')"
    ),
    "command-columns": (
        "read 'Used in' columns ACR, ACA, CCR and CCA as per-command use"
        " marks, '-' marking none (TS 32.299 clause 7.1.0)"
    ),
    "registry-tables": (
        "read tables allocating application ids, command codes, AVP codes"
        " and result codes, each row citing the documents defining it, as"
        " registries (TS 29.230 clauses 4.1, 5.1, 7.1, 8.1)"
    ),
    "unknown-type-tokens": (
        "keep a registry or AVP table Type cell naming no Diameter type as"
        " printed, quoted, rather than fail (TS 29.230 table 7.1 and TS 29.234"
        " table 10.1.1 code 314, 'Integer')"
    ),
    "reserved-range-notes": (
        "read full-width 'The AVP codes from a to b are reserved for ...'"
        " notes in a registry table as reserved ranges (TS 29.230 tables"
        " 7.1, 8.1.2-8.1.4)"
    ),
    "clause-parenthetical": (
        "strip a trailing parenthetical from a clause cell as prose —"
        " '16.4.7 (see Note)' (TS 29.061); clause numbers have no syntax"
        " for parentheses, so the tail is almost certainly prose, but"
        " dropping text is declared, not assumed"
    ),
}
