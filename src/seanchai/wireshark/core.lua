-- Seanchaí Diameter validation: the checks, over one PDU's bytes.
--
-- Plain Lua that runs on 5.1 through 5.4, and nothing of Wireshark's: no
-- bitwise operators, no `string.unpack`, no `utf8` library, no `goto`, since
-- Wireshark 4.2 (Ubuntu 24.04) embeds Lua 5.2 and 4.4 onwards 5.4. The plugin
-- glue hands `validate` a PDU as a string and draws what comes back.
--
-- `rules` is the table `seanchai wireshark-plugin` writes from the corpus:
--   avps[id]        one reading: name, type, flags, members, values
--   commands[key]   candidates for "app:code:R", "*:code:R" for id-less ones
--   answers[id]     an `<answer-message>` body
--   result_codes[vendor][code], bits[identity][bit], values[identity][value]
--   docs[n]         a document: reference, label, explorer id, URL, link kind
--   cites[n]        a place in one: document number, clause, page or false,
--                   the table's label or false, and true for a clause the
--                   corpus places nothing in, which the explorer cannot show
--   requests[key]   for a request's "app:code", the paths its answer's rules
--                   read, identities joined by "/" (`M.request_values`)
--   base[kind]      the RFC 6733 sections the header and format checks cite
--   explorer        the explorer site's address, or nil (`--rules-only`
--                   writes it; the plugin passes its preference instead)
-- A member is {id, name, presence, min, max}, max -1 for unbounded, and a
-- body carries `wildcard`, the `* [ AVP ]` line's {min, max}, where it has one.
-- A reading's `at`, a command's and an answer's `at`, and
-- `bits_at[identity]` and `values_at[identity]` are numbers into `cites`:
-- where the rule is written. A
-- reading's `flags_at` is one, where every flag rule a finding can report is
-- written at one place, or else one per letter, as {M=n, V=n}.

local M = {}

local ERROR, WARN, NOTE = "error", "warn", "note"
M.ERROR, M.WARN, M.NOTE = ERROR, WARN, NOTE

local RELAY = 4294967295
local FAILED_AVP = 279
local BASE_VENDOR = 0
local MAX_DEPTH = 32

-- Reading big-endian numbers off a string, 1-based offsets.

local function u8(s, i)
  return string.byte(s, i)
end

local function u24(s, i)
  local a, b, c = string.byte(s, i, i + 2)
  return (a * 256 + b) * 256 + c
end

local function u32(s, i)
  local a, b, c, d = string.byte(s, i, i + 3)
  return ((a * 256 + b) * 256 + c) * 256 + d
end

-- Whether the bit of `value` that `mask`, a power of two, selects is set.
local function has(value, mask)
  return math.floor(value / mask) % 2 == 1
end

-- RFC 6733 section 4.1: V is 0x80, M 0x40, P 0x20; the rest are reserved.
local AVP_V, AVP_M, AVP_P = 128, 64, 32
-- Section 3: R 0x80, P 0x40, E 0x20, T 0x10; the rest are reserved.
local CMD_R, CMD_P, CMD_E, CMD_T = 128, 64, 32, 16

-- `message` says what is wrong, without naming what it is wrong of: `path`
-- does, the AVP the finding is about, or for one about what a body holds the
-- body, as "Subscription-Data > APN-Configuration-Profile", from the
-- message's top; "Header" for the message header, and nil for the
-- message's own run of AVPs, named once the command is known (`M.cited`).
-- `cite` is a number into `rules.cites`, the place the rule broken is
-- written, and `name` what the explorer looks for there. Returns the finding,
-- for `about`.
local function finding(list, severity, rule, message, offset, length, path, cite, name)
  local found = {
    severity = severity,
    rule = rule,
    message = message,
    offset = offset,
    length = length,
    path = path,
    cite = cite,
    cite_name = name,
  }
  list[#list + 1] = found
  return found
end

-- Marks a finding citing a general section of RFC 6733 as about one AVP:
-- `reading`, or the AVP whose identity is "vendor:code". The explorer link
-- goes to where that AVP is defined, since the cited section is no clause
-- the corpus places anything in (`M.cited`).
local function about(found, reading, identity)
  if reading then
    found.explore, found.explore_name = reading.at, reading.name
  end
  found.identity = identity
end

-- What the checks that read RFC 6733 alone cite, by rule: `rules.base`'s
-- sections 3 (the header), 4.1 (the AVP header), 4.3.1 (the derived data
-- formats), 7.1.3 (protocol errors) and 7.2 (the E bit).
local BASE_RULES = {
  ["header-truncated"] = "header", ["header-version"] = "header",
  ["header-length"] = "header", ["header-reserved-flags"] = "header",
  ["header-e-bit"] = "header", ["header-t-bit"] = "header",
  ["avp-truncated"] = "avp", ["avp-length"] = "avp",
  ["avp-reserved-flags"] = "avp", ["avp-padding"] = "avp", ["flag-p"] = "avp",
  ["unknown-mandatory"] = "avp",
  utf8 = "derived", ["diameter-identity"] = "derived",
  ["diameter-uri"] = "derived", ["ip-filter-rule"] = "derived",
  address = "derived",
  ["e-bit-missing"] = "protocol_errors", ["e-bit-unexpected"] = "error_bit",
}

-- The rules about the message header or its E bit, whose explorer link goes to
-- the command's definition.
local HEADER_RULES = {
  ["header-truncated"] = true, ["header-version"] = true,
  ["header-length"] = true, ["header-reserved-flags"] = true,
  ["header-e-bit"] = true, ["header-t-bit"] = true,
  ["e-bit-missing"] = true, ["e-bit-unexpected"] = true,
}

-- Where `name` sits inside `path`.
local function join(path, name)
  if path then
    return path .. " > " .. name
  end
  return name
end

local HEADER = "Header"

-- References: a citation as text and links.

-- JavaScript's encodeURIComponent, which the explorer's routes decode.
local function uri_component(text)
  return (text:gsub("[^%w%-_%.!~%*'%(%)]", function(char)
    return string.format("%%%02X", string.byte(char))
  end))
end

-- A query value as URLSearchParams writes it: a space as "+".
local function form_value(text)
  return (text:gsub("[^%w%-_%.%* ]", function(char)
    return string.format("%%%02X", string.byte(char))
  end):gsub(" ", "+"))
end

-- What `cite` (a number into `rules.cites`) says, or nil:
--   document  the reference, as TS29.061
--   text      "TS 29.061 clause 16a.5, table 9a, page 129"
--   short     "TS 29.061 table 9a", for a flag rule's line
--   brief     "TS 29.061 16a.5", for any other finding's line
--   clause, page, table
--   url       the publisher's copy at the place: a PDF's `#page=N`, an RFC's
--             `#section-X.Y`; the document alone where neither reaches it
--   explorer  the explorer site at the clause, nil where `explorer`, the
--             site's address, is nil or the corpus places nothing there
--   place     "TS 29.061 clause 16a.5", label the document's, as "TS 29.061"
--   top       the explorer site at the document, nil without `explorer`
function M.reference(rules, cite, name, explorer)
  local at = cite and rules.cites and rules.cites[cite]
  if not at then
    return nil
  end
  local doc = rules.docs[at[1]]
  local label, id, url, kind = doc[2], doc[3], doc[4], doc[5]
  local clause, page, table_label = at[2], at[3] or nil, at[4] or nil
  local word = kind == "rfc" and "section" or "clause"
  local text = label .. " " .. word .. " " .. clause
  local short = text
  if table_label then
    text = text .. ", table " .. table_label
    short = label .. " table " .. table_label
  end
  if page then
    text = text .. (kind == "printed" and ", printed page " or ", page ") .. page
  end
  local link = url ~= "" and url or nil
  if link and kind == "rfc" then
    -- rfc-editor.org anchors an appendix as `#appendix-A.1`.
    link = link .. (clause:find("^%u") and "#appendix-" or "#section-") .. clause
  elseif link and kind == "pdf" and page then
    link = link .. "#page=" .. page
  end
  local site, top
  if explorer then
    top = explorer .. "#" .. uri_component(id)
  end
  if explorer and not at[5] then
    site = top .. "/" .. uri_component(clause)
    if name then
      site = site .. "?name=" .. form_value(name)
    end
  end
  return {
    document = doc[1], text = text, short = short, brief = label .. " " .. clause,
    clause = clause, page = page,
    table = table_label, url = link, explorer = site,
    place = label .. " " .. word .. " " .. clause, label = label, top = top,
  }
end

-- Splitting a run of AVPs. Offsets are 0-based into the PDU, as Wireshark's
-- ranges are; `first` and `last` bound the run, `last` exclusive.

-- `path` is what holds the run, nil for the message's own; `rules`, where
-- given, names each AVP its framing findings are about.
local function parse_avps(pdu, first, last, findings, path, rules)
  local avps = {}
  local at = first
  while at < last do
    if last - at < 8 then
      finding(findings, ERROR, "avp-truncated",
        string.format("%d octets left over, too few for an AVP", last - at),
        at, last - at, path)
      break
    end
    local code = u32(pdu, at + 1)
    local flags = u8(pdu, at + 5)
    local length = u24(pdu, at + 6)
    local vendor = BASE_VENDOR
    local header = 8
    if has(flags, AVP_V) then
      header = 12
      if length >= 12 and at + 12 <= last then
        vendor = u32(pdu, at + 9)
      end
    end
    local identity = vendor .. ":" .. code
    local known = rules and rules.avps[identity]
    local place = join(path, known and known.name or ("AVP " .. code))
    if length < header then
      about(finding(findings, ERROR, "avp-length",
        string.format("length %d, under its %d-octet header", length, header),
        at, math.min(8, last - at), place), nil, identity)
      break
    end
    if at + length > last then
      about(finding(findings, ERROR, "avp-length",
        string.format("length %d, past the end of what holds it", length),
        at, last - at, place), nil, identity)
      break
    end
    local padded = length + (4 - length % 4) % 4
    local avp = {
      code = code,
      vendor = vendor,
      flags = flags,
      offset = at,
      length = length,
      data = at + header,
      size = length - header,
    }
    avps[#avps + 1] = avp
    if flags % 32 ~= 0 then
      about(finding(findings, WARN, "avp-reserved-flags",
        string.format("reserved flags set (0x%02x)", flags % 32),
        at + 4, 1, place), nil, identity)
    end
    if at + padded > last then
      if padded ~= length then
        about(finding(findings, ERROR, "avp-padding",
          "padding past the end of what holds it",
          at, last - at, place), nil, identity)
      end
      break
    end
    for i = at + length, at + padded - 1 do
      if u8(pdu, i + 1) ~= 0 then
        about(finding(findings, WARN, "avp-padding", "nonzero padding",
          at + length, padded - length, place), nil, identity)
        break
      end
    end
    at = at + padded
  end
  return avps
end

-- Data formats, RFC 6733 section 4.2 and 4.3.

local FIXED_SIZE = {
  Integer32 = 4, Unsigned32 = 4, Float32 = 4, Time = 4, Enumerated = 4,
  Integer64 = 8, Unsigned64 = 8, Float64 = 8,
}

-- RFC 3629 section 4, overlong forms and surrogates refused.
local function valid_utf8(s, first, last)
  local i = first
  while i <= last do
    local c = string.byte(s, i)
    local need, low, high = 0, 128, 191
    if c < 128 then
      need = 0
    elseif c >= 194 and c <= 223 then
      need = 1
    elseif c == 224 then
      need, low = 2, 160
    elseif (c >= 225 and c <= 236) or c == 238 or c == 239 then
      need = 2
    elseif c == 237 then
      need, high = 2, 159
    elseif c == 240 then
      need, low = 3, 144
    elseif c >= 241 and c <= 243 then
      need = 3
    elseif c == 244 then
      need, high = 3, 143
    else
      return false, i - first
    end
    if i + need > last then
      return false, i - first
    end
    for k = 1, need do
      local b = string.byte(s, i + k)
      if k == 1 then
        if b < low or b > high then
          return false, i - first
        end
      elseif b < 128 or b > 191 then
        return false, i - first
      end
    end
    i = i + need + 1
  end
  return true
end

-- RFC 6733 section 4.3.1: a DiameterIdentity is an FQDN or realm, in ASCII,
-- an IDN by its A-labels.
local function identity_problem(text)
  if text == "" then
    return "empty"
  end
  if #text > 255 then
    return "over 255 octets"
  end
  if text:find("[^%w%.%-]") then
    return "a character no host name holds"
  end
  local body = text:gsub("%.$", "")
  for label in (body .. "."):gmatch("([^%.]*)%.") do
    if label == "" then
      return "an empty label"
    end
    if #label > 63 then
      return "a label over 63 octets"
    end
    if label:sub(1, 1) == "-" or label:sub(-1) == "-" then
      return "a label starting or ending in a hyphen"
    end
  end
  return nil
end

-- RFC 6733 section 4.3.1: "aaa://" or "aaas://" FQDN [ port ] [ transport ]
-- [ protocol ]. Its quoted strings are case-insensitive (RFC 5234 section
-- 2.3), so `AAA://` and `transport=TCP` are as good, as is any host name case.
local function uri_problem(text)
  local rest = text:lower():match("^aaas?://(.*)$")
  if rest == nil then
    return "not aaa:// or aaas://"
  end
  local host, tail = rest:match("^([^:;]*)(.*)$")
  local problem = identity_problem(host)
  if problem then
    return "host: " .. problem
  end
  local port, after = tail:match("^:(%d+)(.*)$")
  if port then
    if tonumber(port) > 65535 then
      return "port above 65535"
    end
    tail = after
  end
  for key, value in tail:gmatch(";([^=;]*)=([^;]*)") do
    if key == "transport" then
      if value ~= "tcp" and value ~= "sctp" and value ~= "udp" then
        return "transport " .. value .. ", not tcp, sctp or udp"
      end
    elseif key == "protocol" then
      if value ~= "diameter" and value ~= "radius" and value ~= "tacacs+" then
        return "protocol " .. value .. ", not diameter, radius or tacacs+"
      end
    else
      return "parameter " .. key .. ", which the syntax lacks"
    end
  end
  if tail:gsub(";[^=;]*=[^;]*", "") ~= "" then
    return "text after the host the syntax does not allow"
  end
  return nil
end

-- RFC 6733 section 4.3.1's IPFilterRule: action dir proto from src to dst.
local function filter_problem(text)
  local action, dir, proto, rest = text:match("^(%S+) +(%S+) +(%S+) +(.*)$")
  if action == nil then
    return "not 'action dir proto from ... to ...'"
  end
  if action ~= "permit" and action ~= "deny" then
    return "action " .. action .. ", not permit or deny"
  end
  if dir ~= "in" and dir ~= "out" then
    return "direction " .. dir .. ", not in or out"
  end
  if proto ~= "ip" and not proto:match("^%d+$") then
    return "protocol " .. proto .. ", not ip or a number"
  end
  if not rest:match("^from +.- +to +") then
    return "no 'from ... to ...'"
  end
  return nil
end

local function int32(value)
  if value >= 2147483648 then
    return value - 4294967296
  end
  return value
end

local function data_text(pdu, avp)
  return pdu:sub(avp.data + 1, avp.data + avp.size)
end

-- Interpreted constraints (docs/consumers.md#interpreted-constraints): what a
-- person read in a clause's prose of an AVP's value or presence. A reading
-- carries `cons`, its own; a grouped reading `member_cons[name]`, its
-- members'; a command candidate `cons[name]`, its members'. Each is {at=n,
-- rules={...}}, a rule {k=kind, ...}: a length's `u`, `lo` and `hi`, a range's
-- `lo` and `hi`, exclude's `v`, an encoding's `codec`, an element's `e`, its
-- entry's number in the rules' `elements` (`element_problem`), a bits rule's
-- relation `r` and bits `b`, a members rule's `r` and member identities `m`,
-- a unique rule's member identity `i`, a predicate's `c`, conditions on
-- siblings {avp=identity, t=text, v=value or b=bit or r=another AVP, n=true
-- where negated}, alternatives of conditions `and` joins, and a
-- values rule's `v` and `c`, an equals rule's `r` and words `t`. A term has
-- `q=true` where it names an AVP of the request the answer answers, and so
-- does a rule reading one. An absent rule's AVP is never present; a scoped
-- constraint's `s` is its AVP's identity where the body admits it only
-- through `* [ AVP ]`. Every finding is a note marked `interpreted`,
-- citing its clause.

-- A TBCD-string's decimal digits (TS 29.002 clause 17.7.8: the first digit in
-- bits 1-4, "1111" filling the last octet's bits 5-8 after an odd count), or
-- nil for anything else.
local function tbcd_digits(s)
  local digits = {}
  for i = 1, #s do
    local octet = string.byte(s, i)
    local low, high = octet % 16, math.floor(octet / 16)
    if low > 9 then
      return nil
    end
    digits[#digits + 1] = string.char(48 + low)
    if not (high == 15 and i == #s) then
      if high > 9 then
        return nil
      end
      digits[#digits + 1] = string.char(48 + high)
    end
  end
  return table.concat(digits)
end

-- TS 29.272 table 7.3.9/1, after TS 24.008 clause 10.5.1.13: MCC digits 2
-- and 1, MNC digit 3 ("1111" for a 2-digit MNC) and MCC digit 3, MNC digits 2
-- and 1.
local function plmn_problem(s)
  if #s < 3 then
    return string.format("%d octets, a PLMN identity is 3", #s)
  end
  local a, b, c = string.byte(s, 1, 3)
  for _, digit in ipairs({ a % 16, math.floor(a / 16), b % 16, c % 16,
    math.floor(c / 16) }) do
    if digit > 9 then
      return "an MCC or MNC digit is no decimal digit"
    end
  end
  local mnc3 = math.floor(b / 16)
  if mnc3 > 9 and mnc3 ~= 15 then
    return "MNC digit 3 is neither a digit nor the '1111' filler"
  end
  return nil
end

-- One or more non-empty labels separated by dots.
local function labels_ok(text)
  return text ~= "" and text:sub(1, 1) ~= "." and text:sub(-1) ~= "."
    and not text:find("..", 1, true)
end

-- An IPv4 number in dotted-quad form.
local function ipv4_ok(text)
  local parts = { text:match("^(%d+)%.(%d+)%.(%d+)%.(%d+)$") }
  if #parts ~= 4 then
    return false
  end
  for _, part in ipairs(parts) do
    if #part > 3 or (#part > 1 and part:sub(1, 1) == "0") or tonumber(part) > 255 then
      return false
    end
  end
  return true
end

-- How many 16-bit groups a run of IPv6 groups holds, a dotted IPv4 number
-- ending it counting two; nil for no such run.
local function ipv6_groups(run, last)
  if run == "" then
    return 0
  end
  local count = 0
  local groups = {}
  for group in (run .. ":"):gmatch("([^:]*):") do
    groups[#groups + 1] = group
  end
  for index, group in ipairs(groups) do
    if last and index == #groups and group:find(".", 1, true) then
      if not ipv4_ok(group) then
        return nil
      end
      count = count + 2
    elseif group:match("^%x%x?%x?%x?$") then
      count = count + 1
    else
      return nil
    end
  end
  return count
end

-- An IPv6 number in canonical form: eight groups, or fewer around one "::".
local function ipv6_ok(text)
  local head, tail = text:match("^(.-)::(.*)$")
  if head then
    if tail:find("::", 1, true) then
      return false
    end
    local before, after = ipv6_groups(head, false), ipv6_groups(tail, true)
    return before ~= nil and after ~= nil and before + after <= 7
  end
  return ipv6_groups(text, true) == 8
end

-- Why `token` is no IPFilterRule address: "any", "assigned", or an IPv4 or
-- IPv6 number with an optional mask width valid for its version.
local function ip_filter_address(token)
  if token == "any" or token == "assigned" then
    return nil
  end
  local number, bits = token:match("^([^/]*)/(.*)$")
  number = number or token
  local width
  if ipv4_ok(number) then
    width = 32
  elseif ipv6_ok(number) then
    width = 128
  else
    return string.format("'%s' is no address, 'any' or 'assigned'", token)
  end
  if bits and not (bits:match("^%d+$") and tonumber(bits) <= width) then
    return string.format("'%s' has no mask width 0 to %d", token, width)
  end
  return nil
end

-- Whether `token` is a list of ports and port ranges, 0 to 65535.
local function ip_filter_ports(token)
  for part in (token .. ","):gmatch("([^,]*),") do
    local low, high = part:match("^(%d+)%-(%d+)$")
    if low then
      if tonumber(low) > tonumber(high) or tonumber(high) > 65535 then
        return false
      end
    elseif not (part:match("^%d+$") and tonumber(part) <= 65535) then
      return false
    end
  end
  return true
end

-- Why `text` is no IPFilterRule (RFC 6733 clause 4.3.1) as the documents
-- restrict it: "permit", a direction ("out" where `out_only`), a protocol
-- number or "ip", "from" a source and "to" a destination, each an address
-- and optional ports, no options and no "!".
local function ip_filter_problem(text, out_only)
  if text:find("!", 1, true) then
    return "the invert modifier '!' is used"
  end
  local tokens = {}
  for token in text:gmatch("%S+") do
    tokens[#tokens + 1] = token
  end
  if tokens[1] ~= "permit" then
    return "the action is not 'permit'"
  end
  if not (tokens[2] == "out" or (tokens[2] == "in" and not out_only)) then
    return out_only and "the direction is not 'out'" or "no direction 'in' or 'out'"
  end
  local protocol = tokens[3]
  if not (protocol == "ip" or (protocol and protocol:match("^%d+$")
    and tonumber(protocol) <= 255)) then
    return "no protocol number or 'ip'"
  end
  local position = 4
  for _, keyword in ipairs({ "from", "to" }) do
    if tokens[position] ~= keyword then
      return string.format("no '%s'", keyword)
    end
    if not tokens[position + 1] then
      return string.format("no address after '%s'", keyword)
    end
    local problem = ip_filter_address(tokens[position + 1])
    if problem then
      return problem
    end
    position = position + 2
    if tokens[position] and tokens[position] ~= "to" then
      if not ip_filter_ports(tokens[position]) then
        if keyword == "to" then
          return "options are used"
        end
        return string.format("'%s' are no ports", tokens[position])
      end
      position = position + 1
    end
  end
  if tokens[position] then
    return "options are used"
  end
  return nil
end

local function codec_problem(codec, s)
  if codec == "e164-tbcd" then
    if #s < 1 or #s > 8 then
      return string.format("%d octets, a TBCD E.164 number is 1 to 8", #s)
    end
    local digits = tbcd_digits(s)
    if not digits then
      return "not TBCD digits, '1111' filling only the end"
    end
    if #digits > 15 then
      return string.format("%d digits, an E.164 number is at most 15", #digits)
    end
    return nil
  elseif codec == "plmn-id" then
    if #s ~= 3 then
      return string.format("%d octets, a PLMN identity is 3", #s)
    end
    return plmn_problem(s)
  elseif codec == "plmn-id-prefix" then
    return plmn_problem(s)
  elseif codec == "ip-address" then
    if #s < 2 then
      return "no 2-octet address family"
    end
    local family, size = string.byte(s, 1) * 256 + string.byte(s, 2), #s - 2
    if not ((family == 1 and size == 4) or (family == 2 and size == 16)) then
      return string.format("no IPv4 or IPv6 address (family %d, %d octets)",
        family, size)
    end
    return nil
  end
  if not valid_utf8(s, 1, #s) then
    return "not UTF-8"
  end
  if codec == "digits" then
    if s == "" or s:find("[^0-9]") then
      return "not decimal digits"
    end
  elseif codec == "labels" then
    if not labels_ok(s) then
      return "not dot-separated labels"
    end
  elseif codec == "apn" then
    if s ~= "*" and not labels_ok(s) then
      return "neither dot-separated labels nor *"
    end
  elseif codec == "plmn-domain" then
    if not s:lower():match("^mnc%d%d%d?%.mcc%d%d%d%.3gppnetwork%.org$") then
      return "not mnc<MNC>.mcc<MCC>.3gppnetwork.org"
    end
  elseif codec == "epc-plmn-domain" then
    if not s:lower():match("^epc%.mnc%d%d%d?%.mcc%d%d%d%.3gppnetwork%.org$") then
      return "not epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org"
    end
  elseif codec == "time-zone" then
    if not s:match("^[+-]%d+$") then
      return "not a sign and a number of 15 minutes"
    end
  elseif codec == "mac-address" then
    local octet = "[0-9A-F][0-9A-F]"
    if not s:match("^" .. octet .. ("%-" .. octet):rep(5) .. "$") then
      return "not six upper-case hexadecimal octets joined by '-'"
    end
  elseif codec == "ip-filter" or codec == "ip-filter-out" then
    return ip_filter_problem(s, codec == "ip-filter-out")
  end
  return nil
end

local function digit_count(codec, s)
  if codec == "e164-tbcd" then
    local digits = tbcd_digits(s)
    return digits and #digits
  end
  if codec == "digits" and codec_problem(codec, s) == nil then
    return #s
  end
  return nil
end

local function character_count(s)
  if not valid_utf8(s, 1, #s) then
    return nil
  end
  local _, continuations = s:gsub("[\128-\191]", "")
  return #s - continuations
end

-- An integer-typed payload's value, an Enumerated being an Integer32; a
-- 64-bit one as a float beyond 2^53.
local function integer_value(kind, s)
  if #s == 4 and (kind == "Integer32" or kind == "Enumerated") then
    return int32(u32(s, 1))
  elseif #s == 4 and kind == "Unsigned32" then
    return u32(s, 1)
  elseif #s == 8 and (kind == "Unsigned64" or kind == "Integer64") then
    local high = u32(s, 1)
    if kind == "Integer64" and high >= 2147483648 then
      high = high - 4294967296
    end
    return high * 4294967296 + u32(s, 5)
  end
  return nil
end

local function number(value)
  return string.format("%.0f", value)
end

local function within(count, low, high)
  return (low == nil or count >= low) and (high == nil or count <= high)
end

local function bounds(low, high)
  if low == high then
    return number(low)
  elseif high == nil then
    return "at least " .. number(low)
  elseif low == nil then
    return "at most " .. number(high)
  end
  return number(low) .. " to " .. number(high)
end

-- Whether bit `bit` of a bits rule's number is set: an integer payload's
-- value, or an OctetString's octets read as one big-endian number, bit 0 the
-- last octet's least significant. nil where the payload has no such number.
local function bit_reader(kind, s)
  if kind == "OctetString" then
    return function(bit)
      local octet = #s - math.floor(bit / 8)
      return octet >= 1 and has(string.byte(s, octet), 2 ^ (bit % 8))
    end, #s * 8
  end
  local value = integer_value(kind, s)
  if value == nil then
    return nil
  end
  return function(bit)
    return has(value, 2 ^ bit)
  end, #s * 8
end

-- "bit 3" or "bits 3, 5".
local function bits_text(list, joiner)
  return (#list == 1 and "bit " or "bits ") .. table.concat(list, joiner or ", ")
end

local function bits_problem(rule, set, width)
  local named, held, unset = {}, {}, {}
  local listed = {}
  for _, each in ipairs(rule.b) do
    named[#named + 1] = tostring(each)
    listed[each] = true
    if set(each) then
      held[#held + 1] = tostring(each)
    else
      unset[#unset + 1] = tostring(each)
    end
  end
  if rule.r == "at-most-one" and #held > 1 then
    return string.format("%s set, at most one may be", bits_text(held, " and "))
  elseif rule.r == "at-least-one" and #held == 0 then
    return string.format("none of bits %s set, one must be",
      table.concat(named, ", "))
  elseif rule.r == "set" and #unset > 0 then
    return string.format("%s clear, must be set", bits_text(unset))
  elseif rule.r == "clear" and #held > 0 then
    return string.format("%s set, must be clear", bits_text(held))
  elseif rule.r == "only" then
    local others = {}
    for bit = 0, width - 1 do
      if not listed[bit] and set(bit) then
        others[#others + 1] = tostring(bit)
      end
    end
    if #others > 0 then
      return string.format("%s set, only %s may be", bits_text(others),
        table.concat(named, ", "))
    end
  end
  return nil
end

-- A field's value as the documents print it: in binary up to 8 bits, else
-- in hexadecimal.
local function field_text(value, width)
  if width > 8 then
    return string.format("0x%0" .. math.ceil(width / 4) .. "x", value)
  end
  local digits = {}
  for bit = width - 1, 0, -1 do
    digits[#digits + 1] = has(value, 2 ^ bit) and "1" or "0"
  end
  return table.concat(digits)
end

-- Why `s`, an AVP's data of `kind`, is not laid out as the element registry's
-- entry `entry` says (seanchai.elements), or nil: the first check broken.
-- Each check is {s=shape, ...}: `octets` (`lo`, `hi`, `t` the bounds in
-- words), `plmn` (a PLMN identity at octet `o`), `field` (bits `hi` of octet
-- `o` to bit `lo` of octet `l`, `w` bits wide, a value in one of the ranges
-- `a`; `p` its place and `t` the values in words), `onebit` (at most one bit
-- of octet `o`), `integer` (`lo`, `hi`, `t`), `tbcd` (TBCD digits from octet
-- `o`) and `fqdn` (text matching one of the patterns `p`, lowercased; `t`
-- what it is not).
local function element_problem(entry, s, kind)
  for _, check in ipairs(entry.c) do
    local shape = check.s
    if shape == "octets" then
      if #s < check.lo or (check.hi and #s > check.hi) then
        return string.format("%d octets, not %s", #s, check.t)
      end
    elseif shape == "plmn" then
      local part = s:sub(check.o, check.o + 2)
      if #part < 3 then
        return string.format("no PLMN identity in octets %d to %d", check.o,
          check.o + 2)
      end
      local problem = plmn_problem(part)
      if problem then
        return "PLMN identity: " .. problem
      end
    elseif shape == "field" then
      if #s >= check.l then
        local number = 0
        for i = check.o, check.l do
          number = number * 256 + string.byte(s, i)
        end
        local value = math.floor(number / 2 ^ (check.lo - 1)) % 2 ^ check.w
        local ok = false
        for _, range in ipairs(check.a) do
          ok = ok or (value >= range[1] and value <= range[2])
        end
        if not ok then
          return string.format("%s %s, not %s", check.p, field_text(value, check.w),
            check.t)
        end
      end
    elseif shape == "onebit" then
      if #s >= check.o then
        local octet, held = string.byte(s, check.o), {}
        for bit = 8, 1, -1 do
          if has(octet, 2 ^ (bit - 1)) then
            held[#held + 1] = tostring(bit)
          end
        end
        if #held > 1 then
          return string.format("bits %s of octet %d set, at most one may be",
            table.concat(held, " and "), check.o)
        end
      end
    elseif shape == "integer" then
      local value = integer_value(kind, s)
      if value and not within(value, check.lo, check.hi) then
        return string.format("%s, not %s", number(value), check.t)
      end
    elseif shape == "tbcd" then
      for i = check.o, #s do
        local octet = string.byte(s, i)
        if octet % 16 == 15 or (math.floor(octet / 16) == 15 and i < #s) then
          return string.format("octet %d: '1111' filler before the last digit", i)
        end
      end
    elseif shape == "fqdn" then
      if not valid_utf8(s, 1, #s) then
        return "not UTF-8 text"
      end
      local text, ok = s:lower(), false
      for _, pattern in ipairs(check.p) do
        ok = ok or text:match(pattern) ~= nil
      end
      if not ok then
        return check.t
      end
    end
  end
  return nil
end

local function interpreted(ctx, cons, rule, message, offset, length, path, name)
  local found = finding(ctx.findings, NOTE, "constraint-" .. rule, message, offset,
    length, path, cons.at, name)
  found.interpreted = true
  return found
end

-- The names a grouped reading's body gives the member identities `ids`: up
-- to three, then the first two and how many more, and all of them.
local function members_text(reading, ids)
  local named = {}
  for _, identity in ipairs(ids) do
    local name = identity
    for _, member in ipairs(reading.members or {}) do
      if member.id and member.id:match("^[^@]+") == identity then
        name = member.name
        break
      end
    end
    named[#named + 1] = name
  end
  local all = table.concat(named, ", ")
  if #named <= 3 then
    return all, all
  end
  return string.format("%s, %s and %d more", named[1], named[2], #named - 2), all
end

-- The data of the AVPs a term names: every AVP of the run of its identity
-- (`held[identity]`), and on through the members of the identities `p`
-- lists, one a level; with `q`, every one of the request's at its path
-- (`ctx.request`, `M.request_values`).
local function term_data(ctx, held, term)
  if term.q then
    return ctx.request and ctx.request[term.avp] or {}
  end
  local found = held[term.avp] or {}
  for _, identity in ipairs(term.p or {}) do
    local inner = {}
    for _, avp in ipairs(found) do
      for _, member in ipairs(parse_avps(ctx.pdu, avp.data, avp.data + avp.size,
        {})) do
        if member.vendor .. ":" .. member.code == identity then
          inner[#inner + 1] = member
        end
      end
    end
    found = inner
  end
  local data = {}
  for _, avp in ipairs(found) do
    data[#data + 1] = data_text(ctx.pdu, avp)
  end
  return data
end

-- Whether a predicate's condition holds of a run's AVPs: true, false, or nil
-- where a value it tests cannot be read. A value read from another AVP (`r`)
-- holds where the two have the same octets.
local function condition_holds(ctx, held, condition)
  local list = term_data(ctx, held, condition)
  if #list == 0 then
    return false
  end
  if condition.r then
    for _, other in ipairs(term_data(ctx, held, condition.r)) do
      for _, data in ipairs(list) do
        if data == other then
          return true
        end
      end
    end
    return false
  end
  if condition.v == nil and condition.b == nil then
    return true
  end
  local reading = ctx.rules.avps[condition.l or condition.avp]
  local unknown = false
  for _, data in ipairs(list) do
    local value = reading and integer_value(reading.type, data)
    if value == nil then
      unknown = true
    elseif condition.v ~= nil then
      if value == condition.v then
        return true
      end
    elseif has(value, 2 ^ condition.b) then
      return true
    end
  end
  if unknown then
    return nil
  end
  return false
end

-- The alternatives joined by "or", each its conditions joined by "and", a
-- bit of the AVP the one before names by its name alone: `DSR-Flags bit "A"
-- or "B"`.
local function conditions_text(alternatives)
  local parts, prefix = {}, nil
  for _, conjunction in ipairs(alternatives) do
    local terms = {}
    for _, condition in ipairs(conjunction) do
      terms[#terms + 1] = condition.t
    end
    local text = table.concat(terms, " and ")
    local own = #conjunction == 1 and text:match('^(.- bit )"') or nil
    if own and own == prefix then
      text = text:sub(#own + 1)
    end
    prefix = own
    parts[#parts + 1] = text
  end
  return table.concat(parts, " or ")
end

-- Whether one of a rule's alternatives holds, each when every condition of
-- it does, a negated one (`n`) when it does not: true, false, or nil where
-- that rests on a value not read.
local function alternatives_hold(ctx, held, alternatives)
  local unknown = false
  for _, conjunction in ipairs(alternatives) do
    local met = true
    for _, condition in ipairs(conjunction) do
      local holds = condition_holds(ctx, held, condition)
      if holds ~= nil and condition.n then
        holds = not holds
      end
      if holds == false then
        met = false
        break
      elseif holds == nil then
        met = nil
      end
    end
    if met then
      return true
    end
    unknown = unknown or met == nil
  end
  if unknown then
    return nil
  end
  return false
end

-- What breaks an equals rule, a predicate or a values rule on the AVP
-- `subject` (nil where absent), named `name` with identity `identity`, of
-- the run whose AVPs by identity are `held`: the problem's words, or nil.
local function predicate_problem(ctx, rule, held, subject, name, identity)
  if rule.k == "equals" then
    local others = term_data(ctx, held, rule.r)
    if subject and #others > 0 then
      local mine, same = data_text(ctx.pdu, subject), false
      for _, other in ipairs(others) do
        same = same or other == mine
      end
      if not same then
        return "not the value of " .. rule.t
      end
    end
    return nil
  end
  if not rule.c then
    return nil
  end
  local holds = alternatives_hold(ctx, held, rule.c)
  local any, unknown = holds == true, holds == nil
  local said = conditions_text(rule.c)
  if rule.k == "present-if" and any and not subject then
    return string.format("missing %s, required with %s", name, said)
  elseif rule.k == "absent-if" and any and subject then
    return "not allowed with " .. said
  elseif rule.k == "requires" and subject and not any and not unknown then
    return "not allowed without " .. said
  elseif rule.k == "excludes" and subject and any then
    return "not allowed with " .. said
  elseif rule.k == "values" and subject and any then
    local reading = ctx.rules.avps[identity]
    local value = reading
      and integer_value(reading.type, data_text(ctx.pdu, subject))
    if value then
      local allowed, listed = false, {}
      for _, each in ipairs(rule.v) do
        allowed = allowed or value == each
        listed[#listed + 1] = number(each)
      end
      if not allowed then
        return string.format("%s, but only %s with %s", number(value),
          table.concat(listed, ", "), said)
      end
    end
  end
  return nil
end

-- Checks one AVP's data against its reading's constraints and `scoped`,
-- those its command or grouped AVP holds for it. `path` names the AVP.
local function check_constraints(ctx, avp, reading, path, scoped)
  local lists = { reading.cons or {}, scoped or {} }
  local data = data_text(ctx.pdu, avp)
  local codec
  for _, list in ipairs(lists) do
    for _, cons in ipairs(list) do
      for _, rule in ipairs(cons.rules) do
        if rule.k == "encoding" and codec == nil then
          codec = rule.codec
        end
      end
    end
  end
  for _, list in ipairs(lists) do
    for _, cons in ipairs(list) do
      for _, rule in ipairs(cons.rules) do
        local problem, detail, element
        if rule.k == "length" then
          local count
          if rule.u == "octets" then
            count = #data
          elseif rule.u == "characters" then
            count = character_count(data)
          elseif codec then
            count = digit_count(codec, data)
          end
          if count and not within(count, rule.lo, rule.hi) then
            problem = string.format("%d %s, not %s", count, rule.u,
              bounds(rule.lo, rule.hi))
          end
        elseif rule.k == "range" or rule.k == "exclude" then
          local value = integer_value(reading.type, data)
          if value and rule.k == "range" and not within(value, rule.lo, rule.hi) then
            problem = string.format("%s, not %s", number(value),
              bounds(rule.lo, rule.hi))
          elseif value and rule.k == "exclude" then
            for _, excluded in ipairs(rule.v) do
              if value == excluded then
                problem = string.format("%s is excluded", number(value))
              end
            end
          end
        elseif rule.k == "encoding" then
          problem = codec_problem(rule.codec, data)
        elseif rule.k == "element" then
          element = ctx.rules.elements[rule.e]
          problem = element and element_problem(element, data, reading.type)
        elseif rule.k == "bits" then
          local set, width = bit_reader(reading.type, data)
          if set then
            problem = bits_problem(rule, set, width)
          end
        elseif rule.k == "absent" and list == lists[1] then
          -- Wherever the document reads it; a scope's own, the predicates'.
          problem = "not allowed"
        elseif (rule.c or rule.k == "equals") and list == lists[1] then
          -- A block with no scope: its paths start at the AVP itself.
          local identity = avp.vendor .. ":" .. avp.code
          problem = predicate_problem(ctx, rule, { [identity] = { avp } }, avp,
            reading.name, identity)
        elseif rule.k == "members" and reading.type == "Grouped" then
          local held = {}
          for _, each in ipairs(parse_avps(ctx.pdu, avp.data, avp.data + avp.size,
            {}, path)) do
            held[each.vendor .. ":" .. each.code] = true
          end
          local listed, any = {}, false
          for _, identity in ipairs(rule.m) do
            listed[identity] = true
            any = any or held[identity] == true
          end
          local short, all = members_text(reading, rule.m)
          if rule.r == "at-least-one" and not any and #rule.m == 1 then
            problem = "missing " .. all
          elseif rule.r == "at-least-one" and not any then
            problem = string.format("none of %s, one must be held", short)
            detail = string.format("none of %s, one must be held", all)
          elseif rule.r == "only" then
            for identity in pairs(held) do
              if not listed[identity] then
                problem = string.format("holds a member besides %s", short)
                detail = string.format("holds a member besides %s", all)
                break
              end
            end
          end
        end
        if problem then
          local found = interpreted(ctx, cons, rule.k, problem, avp.data, avp.size,
            path, reading.name)
          found.detail = detail
          if rule.k == "element" then
            -- Beneath the line, the element and where its layout is read.
            found.element = string.format("%s (%s): %s", element.said,
              element.read, element.check)
          end
        end
      end
    end
  end
end

-- Checks the predicates `scoped` (constraints by member name) states of a
-- run of AVPs: `identities` gives each name's identity in the body. `path`
-- names what holds the run, nil for the message, `here` names it either way,
-- and `anchor` is its octets, for a member missing from it.
local function check_predicates(ctx, scoped, identities, avps, path, here, anchor)
  if not scoped then
    return
  end
  local held = {}
  for _, avp in ipairs(avps) do
    local identity = avp.vendor .. ":" .. avp.code
    held[identity] = held[identity] or {}
    held[identity][#held[identity] + 1] = avp
  end
  for name, list in pairs(scoped) do
    for _, cons in ipairs(list) do
      -- A member the body names, or one only its `* [ AVP ]` admits.
      local identity = identities[name] or cons.s
      local subject = identity and held[identity] and held[identity][1]
      for _, rule in ipairs(cons.rules) do
        local problem
        if rule.k == "absent" then
          problem = subject and "not allowed"
        elseif rule.q and not ctx.request then
          -- Reads the request, which is not at hand: unchecked, said once
          -- for the answer (`result.request_unchecked`).
          ctx.request_unchecked = ctx.request_unchecked + 1
        else
          problem = predicate_problem(ctx, rule, held, subject, name, identity)
        end
        local found
        if problem and subject then
          found = interpreted(ctx, cons, rule.k, problem, subject.offset,
            subject.length, join(path, name), name)
        elseif problem then
          found = interpreted(ctx, cons, rule.k, problem, anchor[1], anchor[2], here,
            name)
        end
        if found and rule.q then
          -- Read against the request: the plugin links it.
          found.request = true
        end
      end
    end
  end
end

-- Checks the unique rules the grouped readings of a run hold for their
-- members: `grouped` lists each grouped AVP of the run with its reading and
-- its path. No two AVPs of one reading hold the member with the same octets.
local function check_unique(ctx, grouped)
  local seen = {}
  for _, entry in ipairs(grouped) do
    local reading = entry.reading
    for name, list in pairs(reading.member_cons or {}) do
      for _, cons in ipairs(list) do
        for _, rule in ipairs(cons.rules) do
          if rule.k == "unique" then
            local key = tostring(reading) .. "\0" .. name
            seen[key] = seen[key] or {}
            for _, member in ipairs(parse_avps(ctx.pdu, entry.avp.data,
              entry.avp.data + entry.avp.size, {})) do
              if member.vendor .. ":" .. member.code == rule.i then
                local text = data_text(ctx.pdu, member)
                if seen[key][text] then
                  interpreted(ctx, cons, "unique", string.format(
                    "same as in another %s beside it", reading.name),
                    member.offset, member.length, join(entry.path, name), name)
                end
                seen[key][text] = true
                break
              end
            end
          end
        end
      end
    end
  end
end

local function avp_label(rules, avp)
  local reading = rules.avps[avp.vendor .. ":" .. avp.code]
  if reading then
    return reading.name
  end
  return string.format("AVP %d (vendor %d)", avp.code, avp.vendor)
end

-- What one value table says of a number: its name, or nil.
local function enum_problem(reading, value)
  for _, entry in ipairs(reading.ranges or {}) do
    if value >= entry[2] and value <= entry[3] then
      if entry[1] == "reserved" then
        return ERROR, "is reserved"
      elseif entry[1] == "void" then
        return ERROR, "is void, withdrawn"
      else
        return nil
      end
    end
  end
  if reading.values and reading.values[value] then
    return nil
  end
  -- No values: an Enumerated the clause leaves to another document
  -- (`values_open`), or a type a table prints for an AVP the corpus holds
  -- no values of (RFC 5777's Treatment-Action): nothing to hold it to.
  if reading.values_open or reading.values == nil then
    return nil
  end
  return WARN, "is no value the document defines"
end

-- Validation of a run of AVPs against a body.

local validate_body

-- `path` names the AVP.
local function check_flags(ctx, avp, reading, path)
  local flags = reading.flags
  if not flags then
    return
  end
  local function rule_for(letter)
    if flags.must:find(letter, 1, true) then return "must" end
    if flags.must_not:find(letter, 1, true) then return "must_not" end
    if flags.should_not:find(letter, 1, true) then return "should_not" end
    if flags.may:find(letter, 1, true) then return "may" end
    if flags.application:find(letter, 1, true) then return "application" end
    return nil
  end
  local bits = { M = AVP_M, V = AVP_V, P = AVP_P }
  for _, letter in ipairs({ "M", "V", "P" }) do
    local set = has(avp.flags, bits[letter])
    local rule = rule_for(letter)
    -- Where this bit's rule is written, which its finding names: one place
    -- for every bit, or one per letter.
    local cite = reading.flags_at
    if type(cite) == "table" then
      cite = cite[letter]
    end
    -- With no place to cite, the line names the document read.
    local source = not M.reference(ctx.rules, cite) and reading.read_through or nil
    local found
    if rule == "must" and not set then
      found = finding(ctx.findings, ERROR, "flag-must",
        string.format("%s bit clear, must be set", letter),
        avp.offset + 4, 1, path, cite, reading.name)
    elseif rule == "must_not" and set then
      found = finding(ctx.findings, ERROR, "flag-must-not",
        string.format("%s bit set, must not be", letter),
        avp.offset + 4, 1, path, cite, reading.name)
    elseif rule == "should_not" and set then
      found = finding(ctx.findings, WARN, "flag-should-not",
        string.format("%s bit set, should not be", letter),
        avp.offset + 4, 1, path, cite, reading.name)
    elseif rule == nil and letter == "P" and set then
      -- RFC 6733 section 4.1: no end-to-end security is specified, "therefore,
      -- the P bit SHOULD be set to 0".
      about(finding(ctx.findings, WARN, "flag-p", "P bit set, should be 0",
        avp.offset + 4, 1, path), reading)
    end
    if found then
      found.source = source
    end
  end
end

-- `path` names the AVP.
local function check_data(ctx, avp, reading, path, depth)
  local kind = reading.type
  local findings = ctx.findings
  local pdu = ctx.pdu
  local size = FIXED_SIZE[kind]
  if size then
    if avp.size ~= size then
      about(finding(findings, ERROR, "data-length",
        string.format("%d octets, %s is %d", avp.size, kind, size),
        avp.offset, avp.length, path,
        -- Time and Enumerated are section 4.3.1's, the rest section 4.2's.
        ctx.rules.base and ctx.rules.base[(kind == "Time" or kind == "Enumerated")
          and "derived" or "basic"]), reading)
      return
    end
    if kind == "Enumerated" then
      local value = int32(u32(pdu, avp.data + 1))
      local severity, problem = enum_problem(reading, value)
      if severity then
        finding(findings, severity, "enum-value",
          string.format("%d %s", value, problem),
          avp.data, 4, path, reading.at, reading.name)
      end
    elseif kind == "Unsigned32" then
      local value = u32(pdu, avp.data + 1)
      local identity = avp.vendor .. ":" .. avp.code
      if reading.name == "Result-Code" then
        ctx.result_code = value
        local names = ctx.rules.result_codes[BASE_VENDOR] or {}
        if not names[value] then
          finding(findings, WARN, "result-code",
            string.format("%d is no code a document defines", value),
            avp.data, 4, path, reading.at, reading.name)
        end
      elseif reading.name == "Experimental-Result-Code" then
        ctx.experimental_codes[#ctx.experimental_codes + 1] = {
          value = value, offset = avp.data, path = path, cite = reading.at,
        }
      elseif ctx.rules.bits[identity] then
        local known = ctx.rules.bits[identity]
        local unknown = {}
        local mask = 1
        for bit = 0, 31 do
          if has(value, mask) and not known[bit] then
            unknown[#unknown + 1] = tostring(bit)
          end
          mask = mask * 2
        end
        if #unknown > 0 then
          finding(findings, NOTE, "bits",
            string.format("%s set, which no document names", bits_text(unknown)),
            avp.data, 4, path, ctx.rules.bits_at[identity] or reading.at, reading.name)
        end
      elseif ctx.rules.values and ctx.rules.values[identity] then
        -- A value of an integer AVP no table names: as a bit, a note, since
        -- no table says it is all there is.
        if not ctx.rules.values[identity][value] then
          finding(findings, NOTE, "values",
            string.format("%d is no value a document names", value),
            avp.data, 4, path, ctx.rules.values_at[identity] or reading.at,
            reading.name)
        end
      end
    end
    return
  end
  if kind == "UTF8String" then
    local ok, at = valid_utf8(pdu, avp.data + 1, avp.data + avp.size)
    if not ok then
      about(finding(findings, ERROR, "utf8",
        string.format("invalid UTF-8 at octet %d", at),
        avp.data + at, 1, path), reading)
    end
  elseif kind == "DiameterIdentity" then
    local problem = identity_problem(data_text(pdu, avp))
    if problem then
      about(finding(findings, ERROR, "diameter-identity",
        problem, avp.data, avp.size, path), reading)
    end
  elseif kind == "DiameterURI" then
    local problem = uri_problem(data_text(pdu, avp))
    if problem then
      about(finding(findings, ERROR, "diameter-uri", problem,
        avp.data, avp.size, path), reading)
    end
  elseif kind == "IPFilterRule" then
    local problem = filter_problem(data_text(pdu, avp))
    if problem then
      about(finding(findings, ERROR, "ip-filter-rule", problem,
        avp.data, avp.size, path), reading)
    end
  elseif kind == "Address" then
    if avp.size < 2 then
      about(finding(findings, ERROR, "address",
        "shorter than its 2-octet address family",
        avp.offset, avp.length, path), reading)
      return
    end
    local family = string.byte(pdu, avp.data + 1) * 256 + string.byte(pdu, avp.data + 2)
    local expected = ({ [1] = 4, [2] = 16 })[family]
    if expected and avp.size - 2 ~= expected then
      about(finding(findings, ERROR, "address",
        string.format("IPv%d address of %d octets, not %d", family == 1 and 4 or 6,
          avp.size - 2, expected),
        avp.data, avp.size, path), reading)
    end
  elseif kind == "Grouped" then
    if depth >= MAX_DEPTH then
      return
    end
    if avp.vendor == BASE_VENDOR and avp.code == FAILED_AVP then
      -- RFC 6733 section 7.5: what it holds is the AVP that could not be
      -- processed, as received, or a zero-filled stand-in for a missing one,
      -- so nothing inside is held to its own definition, nor read as this
      -- answer's (a copied Result-Code). Only `1* { AVP }` applies.
      if avp.size < 8 then
        finding(findings, ERROR, "avp-missing",
          "holds no AVP, 1* { AVP } requires one",
          avp.offset, avp.length, path, reading.at, reading.name)
      end
      return
    end
    local held = parse_avps(pdu, avp.data, avp.data + avp.size, findings, path,
      ctx.rules)
    if reading.members == nil then
      -- Typed Grouped by a table that prints no rule for it (TS 29.128's
      -- APN-Rate-Control-Status, OMA's charging AVPs): what it holds is
      -- framed, and no body says more of it.
      return
    end
    validate_body(ctx, reading.members, held, path, depth + 1, reading,
      { avp.offset, avp.length })
  end
end

local function times(count)
  return count == 1 and "1 time" or (count .. " times")
end

-- Checks a run of AVPs against `body`: occurrences, positions, what the
-- wildcard admits, each AVP's flags and data, and grouped AVPs inside.
-- `path` names the grouped AVP holding the run, nil for the message's own,
-- and `anchor` is its octets, {offset, length}, where a finding about what
-- the run lacks goes.
validate_body = function(ctx, body, avps, path, depth, owner, anchor)
  local rules = ctx.rules
  local findings = ctx.findings
  anchor = anchor or { ctx.anchor_offset, ctx.anchor_length }
  -- What holds the run, as a finding about the run names it.
  local here = path or ctx.label
  -- The rule the body is: the Grouped AVP's, else the command's ABNF.
  local cite, cite_name = ctx.cite, ctx.cite_name
  if owner then
    cite, cite_name = owner.at, owner.name
  end
  local by_identity = {}
  -- Each member's identity by name, for the predicates' subjects.
  local identities = {}
  for index, member in ipairs(body) do
    if member.id then
      local identity = member.id:match("^[^@]+")
      by_identity[identity] = by_identity[identity] or { member = member, index = index }
      identities[member.name] = identities[member.name] or identity
    end
  end
  -- The constraints the grouped AVP, or at the top the command, holds for
  -- its members.
  local scoped
  if owner then
    scoped = owner.member_cons
  elseif depth == 0 then
    scoped = ctx.cons
  end
  local counts = {}
  local positions = {}
  -- Each identity's AVPs in order, for the first beyond what is allowed.
  local held = {}
  local unlisted = 0
  local grouped = {}
  for position, avp in ipairs(avps) do
    local identity = avp.vendor .. ":" .. avp.code
    local slot = by_identity[identity]
    local reading
    local name
    if slot then
      if depth == 0 then
        ctx.listed = ctx.listed + 1
      end
      counts[identity] = (counts[identity] or 0) + 1
      positions[identity] = positions[identity] or position
      held[identity] = held[identity] or {}
      held[identity][#held[identity] + 1] = avp
      reading = rules.avps[slot.member.id]
      name = slot.member.name
    else
      reading = rules.avps[identity]
      name = avp_label(rules, avp)
      unlisted = unlisted + 1
      if not body.wildcard then
        finding(findings, ERROR, "avp-not-allowed",
          "not allowed, unlisted and no * [ AVP ]",
          avp.offset, avp.length, join(path, name), cite, cite_name)
      elseif ctx.prefs.wildcard_notes then
        finding(findings, NOTE, "avp-by-wildcard", "unlisted, * [ AVP ] admits it",
          avp.offset, avp.length, join(path, name), cite, cite_name)
      end
    end
    local place = join(path, name)
    if reading then
      check_flags(ctx, avp, reading, place)
      check_data(ctx, avp, reading, place, depth)
      check_constraints(ctx, avp, reading, place, scoped and scoped[name])
      if reading.member_cons then
        grouped[#grouped + 1] = { avp = avp, reading = reading, path = place }
      end
    elseif has(avp.flags, AVP_M) then
      about(finding(findings, WARN, "unknown-mandatory",
        "no document defines it, M bit set (DIAMETER_AVP_UNSUPPORTED)",
        avp.offset, avp.length, place), nil, identity)
    else
      finding(findings, NOTE, "unknown-avp", "no document defines it",
        avp.offset, avp.length, place)
    end
  end
  -- Occurrences.
  check_predicates(ctx, scoped, identities, avps, path, here, anchor)
  check_unique(ctx, grouped)
  local wildcard = body.wildcard
  if wildcard and unlisted < wildcard.min then
    finding(findings, ERROR, "avp-missing",
      string.format("%d unlisted AVP%s, * [ AVP ] needs %d", unlisted,
        unlisted == 1 and "" or "s", wildcard.min),
      anchor[1], anchor[2], here, cite, cite_name)
  elseif wildcard and wildcard.max >= 0 and unlisted > wildcard.max then
    finding(findings, ERROR, "avp-occurrences",
      string.format("%d unlisted AVPs, * [ AVP ] allows %d", unlisted, wildcard.max),
      anchor[1], anchor[2], here, cite, cite_name)
  end
  -- A body listing one AVP on several lines (TS 29.234's RAR, `{
  -- Destination-Host }` and `[ Destination-Host ]`) admits as many as the
  -- lines together do.
  local allowed, order = {}, {}
  for _, member in ipairs(body) do
    if member.id then
      local identity = member.id:match("^[^@]+")
      local bound = allowed[identity]
      if not bound then
        bound = { member = member, min = 0, max = 0 }
        allowed[identity] = bound
        order[#order + 1] = identity
      end
      bound.min = bound.min + member.min
      if bound.max >= 0 then
        bound.max = member.max < 0 and -1 or bound.max + member.max
      end
    end
  end
  for _, identity in ipairs(order) do
    local bound = allowed[identity]
    local member = bound.member
    local count = counts[identity] or 0
    if count == 0 and bound.min > 0 then
      finding(findings, ERROR, "avp-missing",
        string.format("missing %s%s", member.name,
          bound.min > 1 and (", required " .. times(bound.min)) or ""),
        anchor[1], anchor[2], here, cite, cite_name)
    elseif count < bound.min then
      finding(findings, ERROR, "avp-missing",
        string.format("%s occurs %s, at least %d", member.name, times(count),
          bound.min),
        anchor[1], anchor[2], here, cite, cite_name)
    elseif bound.max >= 0 and count > bound.max then
      -- On the first beyond the bound.
      local extra = held[identity][bound.max + 1]
      finding(findings, ERROR, "avp-occurrences",
        string.format("occurs %s, at most %d", times(count), bound.max),
        extra.offset, extra.length, join(path, member.name), cite, cite_name)
    end
  end
  for _, member in ipairs(body) do
    if not member.id and (member.hole or member.placeholder) then
      finding(findings, NOTE, "unverifiable",
        string.format("%s unchecked, the corpus cannot complete it (%s)", member.name,
          member.hole or "undefined"),
        anchor[1], anchor[2], here, cite, cite_name)
    end
  end
  -- Fixed positions: the fixed members the body lists before any other must
  -- lead the run, in that order, and those after every other must end it.
  local leading = {}
  for _, member in ipairs(body) do
    if member.presence ~= "fixed" then
      break
    end
    leading[#leading + 1] = member
  end
  local expected = 1
  for _, member in ipairs(leading) do
    local identity = member.id and member.id:match("^[^@]+")
    local at = identity and positions[identity]
    if at then
      if at ~= expected then
        local avp = avps[at]
        finding(findings, ERROR, "avp-position",
          string.format("AVP %d, must be AVP %d", at, expected),
          avp.offset, avp.length, join(path, member.name), cite, cite_name)
      end
      expected = expected + 1
    end
  end
  local trailing = {}
  for index = #body, 1, -1 do
    local member = body[index]
    if member.presence ~= "fixed" or index <= #leading then
      break
    end
    table.insert(trailing, 1, member)
  end
  expected = #avps - #trailing + 1
  for _, member in ipairs(trailing) do
    local identity = member.id and member.id:match("^[^@]+")
    local at = identity and positions[identity]
    if at and at ~= expected then
      local avp = avps[at]
      finding(findings, ERROR, "avp-position",
        string.format("AVP %d of %d, must be among the last", at, #avps),
        avp.offset, avp.length, join(path, member.name), cite, cite_name)
    end
    expected = expected + 1
  end
end

-- One candidate: validates the message's AVPs against `body`.
local function run(rules, prefs, pdu, avps, header_findings, form, anchor, request)
  local ctx = {
    request = request,
    request_unchecked = 0,
    rules = rules,
    prefs = prefs,
    pdu = pdu,
    findings = {},
    label = form.label,
    cite = form.cite,
    cite_name = form.cite_name,
    anchor_offset = anchor[1],
    anchor_length = anchor[2],
    experimental_codes = {},
    listed = 0,
    cons = form.cons,
  }
  for _, each in ipairs(header_findings) do
    ctx.findings[#ctx.findings + 1] = each
  end
  validate_body(ctx, form.body, avps, nil, 0, nil)
  return ctx
end

-- How many findings are errors, warnings and notes, and how many of the
-- notes are of interpreted rules.
local function score(findings)
  local errors, warnings, notes, interpreted = 0, 0, 0, 0
  for _, each in ipairs(findings) do
    if each.severity == ERROR then
      errors = errors + 1
    elseif each.severity == WARN then
      warnings = warnings + 1
    else
      notes = notes + 1
      if each.interpreted then
        interpreted = interpreted + 1
      end
    end
  end
  return errors, warnings, notes, interpreted
end

-- The application a relayed message (id 0xffffffff) belongs to, from the
-- application-id AVPs it carries.
local function relayed_application(pdu, avps)
  for _, avp in ipairs(avps) do
    if avp.vendor == 0 and (avp.code == 258 or avp.code == 259) and avp.size == 4 then
      return u32(pdu, avp.data + 1)
    end
    if avp.vendor == 0 and avp.code == 260 then
      local inner = parse_avps(pdu, avp.data, avp.data + avp.size, {}, nil)
      for _, each in ipairs(inner) do
        if each.vendor == 0 and (each.code == 258 or each.code == 259) and each.size == 4 then
          return u32(pdu, each.data + 1)
        end
      end
    end
  end
  return nil
end

local function pinned(prefs, candidates)
  if not prefs.pin or prefs.pin == "" then
    return candidates
  end
  local wanted = {}
  for reference in prefs.pin:gmatch("[^,%s]+") do
    wanted[reference] = true
  end
  local kept = {}
  for _, candidate in ipairs(candidates) do
    if wanted[candidate.document] then
      kept[#kept + 1] = candidate
    end
  end
  if #kept == 0 then
    return candidates
  end
  return kept
end

local function find_candidates(rules, application, code, request)
  local flag = request and "1" or "0"
  local exact = rules.commands[application .. ":" .. code .. ":" .. flag]
  if exact then
    return exact, "exact"
  end
  local any = rules.commands["*:" .. code .. ":" .. flag]
  if any then
    return any, "any-application"
  end
  return nil, nil
end

-- What an answer's rules read of a request, kept from the request until its
-- answer comes: the data of every AVP at a path `rules.requests` lists for
-- the request's "app:code" (or "*:code" for a command printed with no
-- application), identities joined by "/", as {[path]={data, ...}}, an empty
-- list for one it lacks.
-- Nil for an answer, a header too short, or a request no rule reads.
function M.request_values(rules, pdu)
  if #pdu < 20 or not rules.requests or not has(u8(pdu, 5), CMD_R) then
    return nil
  end
  local code = u24(pdu, 6)
  local application = u32(pdu, 9)
  local avps = parse_avps(pdu, 20, math.min(u24(pdu, 2), #pdu), {}, nil, rules)
  if application == RELAY then
    application = relayed_application(pdu, avps) or application
  end
  local kept, any = {}, false
  for _, key in ipairs({ application .. ":" .. code, "*:" .. code }) do
    for _, identity in ipairs(rules.requests[key] or {}) do
      kept[identity], any = {}, true
    end
  end
  if not any then
    return nil
  end
  for key, list in pairs(kept) do
    -- A path's identities, joined by "/": the AVPs at its end.
    local found = avps
    local depth = 0
    for identity in key:gmatch("[^/]+") do
      if depth > 0 then
        local inner = {}
        for _, avp in ipairs(found) do
          for _, member in ipairs(parse_avps(pdu, avp.data, avp.data + avp.size, {})) do
            inner[#inner + 1] = member
          end
        end
        found = inner
      end
      local named = {}
      for _, avp in ipairs(found) do
        if avp.vendor .. ":" .. avp.code == identity then
          named[#named + 1] = avp
        end
      end
      found, depth = named, depth + 1
    end
    for _, avp in ipairs(found) do
      list[#list + 1] = data_text(pdu, avp)
    end
  end
  return kept
end

-- Validates one Diameter PDU, a string of its octets, and for an answer
-- `asked`, what `M.request_values` kept of the request it answers, nil where
-- that is not at hand. Returns a table:
--   command     the chosen candidate {name, abbreviation, document, section}
--   reference   where the command is defined (`M.reference`), or nil
--   form        "command", "answer-message" or nil when nothing matched
--   findings    {severity, rule, message, offset, length, path, reference,
--               interpreted, where, line, full}: `path` the AVP or body the
--               finding is about, from the message's top; `reference` where
--               the rule broken is written, or nil; `interpreted` true for a
--               rule read in prose, a note; `where`, `line` and `full` from
--               `M.cited`
--   label       what the message's own AVPs are named by: the command's
--               abbreviation, "answer-message" or nil
--   others      the other candidates, each {candidate, errors, warnings, notes}
--   header      code, flags, application, length
--   request_unchecked  how many rules reading the request were left unchecked
--               for want of it; a finding of one that was checked has
--               `request` true
function M.validate(rules, pdu, prefs, asked)
  prefs = prefs or {}
  local header_findings = {}
  local result = { findings = header_findings, others = {} }
  if #pdu < 20 then
    finding(header_findings, ERROR, "header-truncated",
      string.format("%d octets, too few for a header", #pdu), 0, #pdu, HEADER)
    return M.cited(rules, result, prefs)
  end
  local version = u8(pdu, 1)
  local length = u24(pdu, 2)
  local flags = u8(pdu, 5)
  local code = u24(pdu, 6)
  local application = u32(pdu, 9)
  local request = has(flags, CMD_R)
  local error_bit = has(flags, CMD_E)
  result.header = {
    version = version, length = length, flags = flags, code = code,
    application = application, request = request, error_bit = error_bit,
  }
  if version ~= 1 then
    finding(header_findings, ERROR, "header-version",
      string.format("version %d, not 1", version), 0, 1, HEADER)
  end
  if length ~= #pdu then
    finding(header_findings, ERROR, "header-length",
      string.format("length %d, the message holds %d", length, #pdu), 1, 3, HEADER)
  end
  if length % 4 ~= 0 then
    finding(header_findings, ERROR, "header-length",
      string.format("length %d, not a multiple of 4", length), 1, 3, HEADER)
  end
  if flags % 16 ~= 0 then
    finding(header_findings, WARN, "header-reserved-flags",
      string.format("reserved flags set (0x%02x)", flags % 16), 4, 1, HEADER)
  end
  if request and error_bit then
    finding(header_findings, ERROR, "header-e-bit", "E bit set on a request", 4, 1,
      HEADER)
  end
  if not request and has(flags, CMD_T) then
    finding(header_findings, ERROR, "header-t-bit", "T bit set on an answer", 4, 1,
      HEADER)
  end
  local last = math.min(length, #pdu)
  local avps = parse_avps(pdu, 20, last, header_findings, nil, rules)

  local looked_up = application
  if application == RELAY then
    looked_up = relayed_application(pdu, avps) or application
  end
  local candidates, tier = find_candidates(rules, looked_up, code, request)
  result.tier = tier
  local forms = {}
  if candidates then
    candidates = pinned(prefs, candidates)
    for _, candidate in ipairs(candidates) do
      if error_bit and not request then
        local answer = rules.answers[candidate.answer or ""] or rules.answers[rules.base_answer]
        if answer then
          forms[#forms + 1] = {
            candidate = candidate,
            body = answer.members,
            form = "answer-message",
            where = "the answer-message of " .. answer.defined_in .. " section "
              .. answer.section,
            label = "answer-message",
            cite = answer.at,
          }
        end
      else
        forms[#forms + 1] = {
          candidate = candidate,
          body = candidate.members,
          form = "command",
          where = candidate.abbreviation,
          label = candidate.abbreviation,
          cite = candidate.at,
          cite_name = candidate.name,
          cons = candidate.cons,
        }
      end
    end
  elseif error_bit and not request and rules.answers[rules.base_answer] then
    local answer = rules.answers[rules.base_answer]
    forms[1] = {
      body = answer.members,
      form = "answer-message",
      where = "the answer-message of " .. answer.defined_in .. " section "
        .. answer.section,
      label = "answer-message",
      cite = answer.at,
    }
  end
  if #forms == 0 then
    finding(header_findings, NOTE, "unknown-command",
      string.format("no document defines command %d %s, application %d", code,
        request and "request" or "answer", looked_up),
      5, 3, HEADER)
    return M.cited(rules, result, prefs)
  end

  local best, best_ctx, best_score
  local runs = {}
  for _, form in ipairs(forms) do
    local ctx = run(rules, prefs, pdu, avps, header_findings, form, { 5, 3 }, asked)
    local errors, warnings, notes, interpreted = score(ctx.findings)
    runs[#runs + 1] = {
      form = form, ctx = ctx, errors = errors, warnings = warnings, notes = notes,
    }
    -- Fewest errors, then fewest warnings, then fewest breaches of interpreted
    -- rules, then the body listing the most of the message's AVPs rather than
    -- leaving them to * [ AVP ]; on a tie the first, which the generator
    -- orders by what the registry allocates.
    local this = { errors, warnings, interpreted, -ctx.listed }
    local better = best == nil
    if not better then
      for index = 1, #this do
        if this[index] ~= best_score[index] then
          better = this[index] < best_score[index]
          break
        end
      end
    end
    if better then
      best, best_ctx, best_score = form, ctx, this
    end
  end

  -- What the answer's codes say, against the chosen reading.
  for _, each in ipairs(best_ctx.experimental_codes) do
    local vendor_codes = nil
    for vendor, names in pairs(rules.result_codes) do
      if vendor ~= BASE_VENDOR and names[each.value] then
        vendor_codes = names
      end
    end
    if not vendor_codes then
      finding(best_ctx.findings, NOTE, "experimental-result-code",
        string.format("%d is no code a document defines", each.value),
        each.offset, 4, each.path, each.cite, "Experimental-Result-Code")
    end
  end
  local result_code = best_ctx.result_code
  if result_code and not request then
    local protocol = result_code >= 3000 and result_code < 4000
    if protocol and not error_bit then
      finding(best_ctx.findings, WARN, "e-bit-missing",
        string.format("E bit clear, Result-Code %d is a protocol error",
          result_code), 4, 1, HEADER)
    elseif error_bit and not protocol then
      finding(best_ctx.findings, WARN, "e-bit-unexpected",
        string.format("E bit set, Result-Code %d is no protocol error (3xxx)",
          result_code), 4, 1, HEADER)
    end
  end
  if best.candidate then
    if best.candidate.proxiable ~= nil
      and best.candidate.proxiable ~= has(flags, CMD_P) then
      finding(best_ctx.findings, ERROR, "header-p-bit",
        string.format("P bit %s, %s's header %s PXY",
          has(flags, CMD_P) and "set" or "clear", best.candidate.abbreviation,
          best.candidate.proxiable and "prints" or "lacks"), 4, 1, HEADER,
        best.candidate.at, best.candidate.name)
    end
  end

  result.command = best.candidate
  result.request_unchecked = best_ctx.request_unchecked
  result.form = best.form
  result.where = best.where
  result.label = best.label
  result.findings = best_ctx.findings
  for _, each in ipairs(runs) do
    if each.form ~= best and each.form.candidate then
      result.others[#result.others + 1] = {
        candidate = each.form.candidate, errors = each.errors, warnings = each.warnings,
        notes = each.notes,
      }
    end
  end
  return M.cited(rules, result, prefs)
end

-- Where the explorer shows a finding whose cited clause it cannot: the AVP the
-- finding is about, at its defining clause, for a check of RFC 6733's data
-- formats or AVP framing; the command's definition for one of the header or
-- the E bit; else the cited document. Gives `reference` its `explorer` and,
-- as `explorer_place`, what that link shows, as "Destination-Host, RFC 6733
-- section 6.5".
local function explore_instead(rules, each, result, reference, explorer)
  local cite, name = each.explore, each.explore_name
  if not cite and each.identity and rules.avps[each.identity] then
    local reading = rules.avps[each.identity]
    cite, name = reading.at, reading.name
  end
  if not cite and HEADER_RULES[each.rule] and result.command then
    cite, name = result.command.at, result.command.name
  end
  local instead = M.reference(rules, cite, name, explorer)
  if instead and instead.explorer then
    reference.explorer = instead.explorer
    reference.explorer_place = (name and name .. ", " or "") .. instead.place
  else
    reference.explorer, reference.explorer_place = reference.top, reference.label
  end
end

local FLAG_RULES = {
  ["flag-must"] = true, ["flag-must-not"] = true, ["flag-should-not"] = true,
}

-- A path cut to its last two names, "… > MIP-Home-Agent-Host >
-- Destination-Realm", which is enough to find the AVP in the message's tree.
local function shortened(path)
  local names = {}
  for name in (path .. " > "):gmatch("(.-) > ") do
    names[#names + 1] = name
  end
  if #names <= 2 then
    return path
  end
  return "\226\128\166 > " .. names[#names - 1] .. " > " .. names[#names]
end

-- What a finding's line ends in: where its rule is written, as
-- "[TS 29.272 7.3.43, interpreted]" or "[TS 29.061 table 9a]" for a flag
-- rule, which a row of the table states; "" with nothing to say.
local function source_text(each)
  local said = each.source
  local reference = each.reference
  if reference then
    said = FLAG_RULES[each.rule] and reference.table and reference.short
      or reference.brief
  end
  if each.interpreted then
    said = said and (said .. ", interpreted") or "interpreted"
  end
  return said and (" [" .. said .. "]") or ""
end

-- Gives each finding its `reference` (`M.reference`), a base check RFC 6733's
-- section, and the result the `reference` of its command's definition. The
-- explorer links start at `prefs.explorer`, else `rules.explorer`; an empty
-- address leaves them out. A finding with a reference has an explorer link
-- whenever there is an address: where its cited clause holds nothing the
-- explorer can show, `explore_instead`'s. Gives each its `path` where it had
-- none, the message's AVPs being named by the command, its `where`, the path
-- shortened, and its `line`, as "… > MIP-Home-Agent-Host > Destination-Realm:
-- not epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org [TS 29.272 7.3.43, interpreted]",
-- and its `full`, the line with what it cuts short (`detail`), a list of
-- more than three members, in full.
function M.cited(rules, result, prefs)
  local base = rules.base or {}
  local explorer = prefs and prefs.explorer
  if explorer == nil then
    explorer = rules.explorer
  end
  if explorer == "" then
    explorer = nil
  end
  for _, each in ipairs(result.findings) do
    if each.cite == nil and BASE_RULES[each.rule] then
      each.cite = base[BASE_RULES[each.rule]]
    end
    each.reference = M.reference(rules, each.cite, each.cite_name, explorer)
    if explorer and each.reference and not each.reference.explorer then
      explore_instead(rules, each, result, each.reference, explorer)
    end
    each.path = each.path or result.label or "Message"
    each.where = shortened(each.path)
    local source = source_text(each)
    each.line = each.where .. ": " .. (each.message or each.rule) .. source
    each.full = each.detail and (each.where .. ": " .. each.detail .. source)
      or each.line
  end
  if result.command then
    result.reference = M.reference(rules, result.command.at, result.command.name,
      explorer)
    if result.reference and not result.reference.explorer then
      result.reference.explorer = result.reference.top
    end
  end
  return result
end

M.parse_avps = parse_avps
M.codec_problem = codec_problem
M.element_problem = element_problem
M.digit_count = digit_count

-- Why a bits rule {r=relation, b={bits}} does not hold of an AVP's data of
-- `kind`, or nil where it holds or the data is no such number.
function M.bits_problem(rule, kind, s)
  local set, width = bit_reader(kind, s)
  return set and bits_problem(rule, set, width)
end
M.valid_utf8 = valid_utf8
M.identity_problem = identity_problem
M.uri_problem = uri_problem

return M
