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
--   result_codes[vendor][code], bits[identity][bit]
--   docs[n]         a document: reference, label, explorer id, URL, link kind
--   cites[n]        a place in one: document number, clause, page or false,
--                   the table's label or false, and true for a clause the
--                   corpus places nothing in, which the explorer cannot show
--   base[kind]      the RFC 6733 sections the header and format checks cite
--   explorer        the explorer site's address, or nil (`--rules-only`
--                   writes it; the plugin passes its preference instead)
-- A member is {id, name, presence, min, max}, max -1 for unbounded, and a
-- body carries `wildcard`, the `* [ AVP ]` line's {min, max}, where it has one.
-- A reading's `at`, a command's and an answer's `at`, and
-- `bits_at[identity]` are numbers into `cites`: where the rule is written. A
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
--   short     "TS 29.061 table 9a", for a finding's own line
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
    document = doc[1], text = text, short = short, clause = clause, page = page,
    table = table_label, url = link, explorer = site,
    place = label .. " " .. word .. " " .. clause, label = label, top = top,
  }
end

-- Splitting a run of AVPs. Offsets are 0-based into the PDU, as Wireshark's
-- ranges are; `first` and `last` bound the run, `last` exclusive.

local function parse_avps(pdu, first, last, findings, path)
  local avps = {}
  local at = first
  while at < last do
    if last - at < 8 then
      finding(findings, ERROR, "avp-truncated",
        string.format("%d octets left over, too few for an AVP header", last - at),
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
    if length < header then
      about(finding(findings, ERROR, "avp-length",
        string.format("AVP %d declares length %d, below its %d-octet header",
          code, length, header),
        at, math.min(8, last - at), path), nil, identity)
      break
    end
    if at + length > last then
      about(finding(findings, ERROR, "avp-length",
        string.format("AVP %d declares length %d, past the end of what holds it",
          code, length),
        at, last - at, path), nil, identity)
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
        string.format("reserved AVP flag bits set (0x%02x)", flags % 32),
        at + 4, 1, path), nil, identity)
    end
    if at + padded > last then
      if padded ~= length then
        about(finding(findings, ERROR, "avp-padding",
          "the AVP's padding runs past the end of what holds it",
          at, last - at, path), nil, identity)
      end
      break
    end
    for i = at + length, at + padded - 1 do
      if u8(pdu, i + 1) ~= 0 then
        about(finding(findings, WARN, "avp-padding", "nonzero padding octets",
          at + length, padded - length, path), nil, identity)
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
    return "is empty"
  end
  if #text > 255 then
    return "is longer than 255 octets"
  end
  if text:find("[^%w%.%-]") then
    return "holds characters no host name does"
  end
  local body = text:gsub("%.$", "")
  for label in (body .. "."):gmatch("([^%.]*)%.") do
    if label == "" then
      return "has an empty label"
    end
    if #label > 63 then
      return "has a label longer than 63 octets"
    end
    if label:sub(1, 1) == "-" or label:sub(-1) == "-" then
      return "has a label starting or ending in a hyphen"
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
    return "does not start with aaa:// or aaas://"
  end
  local host, tail = rest:match("^([^:;]*)(.*)$")
  local problem = identity_problem(host)
  if problem then
    return "names a host that " .. problem
  end
  local port, after = tail:match("^:(%d+)(.*)$")
  if port then
    if tonumber(port) > 65535 then
      return "names a port above 65535"
    end
    tail = after
  end
  for key, value in tail:gmatch(";([^=;]*)=([^;]*)") do
    if key == "transport" then
      if value ~= "tcp" and value ~= "sctp" and value ~= "udp" then
        return "names transport " .. value .. ", not tcp, sctp or udp"
      end
    elseif key == "protocol" then
      if value ~= "diameter" and value ~= "radius" and value ~= "tacacs+" then
        return "names protocol " .. value .. ", not diameter, radius or tacacs+"
      end
    else
      return "has a parameter " .. key .. " the syntax does not allow"
    end
  end
  if tail:gsub(";[^=;]*=[^;]*", "") ~= "" then
    return "has text the syntax does not allow after the host"
  end
  return nil
end

-- RFC 6733 section 4.3.1's IPFilterRule: action dir proto from src to dst.
local function filter_problem(text)
  local action, dir, proto, rest = text:match("^(%S+) +(%S+) +(%S+) +(.*)$")
  if action == nil then
    return "is not 'action dir proto from ... to ...'"
  end
  if action ~= "permit" and action ~= "deny" then
    return "has action " .. action .. ", not permit or deny"
  end
  if dir ~= "in" and dir ~= "out" then
    return "has direction " .. dir .. ", not in or out"
  end
  if proto ~= "ip" and not proto:match("^%d+$") then
    return "has protocol " .. proto .. ", not ip or a number"
  end
  if not rest:match("^from +.- +to +") then
    return "has no 'from ... to ...'"
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
-- `lo` and `hi`, exclude's `v`, an encoding's `codec`, a predicate's `c`,
-- conditions on siblings {avp=identity, t=text, v=value or b=bit}. Every
-- finding is a warning saying the rule is interpreted, citing its clause.

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
    return string.format("is %d octets, and a PLMN identity is 3", #s)
  end
  local a, b, c = string.byte(s, 1, 3)
  for _, digit in ipairs({ a % 16, math.floor(a / 16), b % 16, c % 16,
    math.floor(c / 16) }) do
    if digit > 9 then
      return "holds an MCC or MNC digit that is no decimal digit"
    end
  end
  local mnc3 = math.floor(b / 16)
  if mnc3 > 9 and mnc3 ~= 15 then
    return "holds an MNC digit 3 that is neither a digit nor the '1111' filler"
  end
  return nil
end

-- One or more non-empty labels separated by dots.
local function labels_ok(text)
  return text ~= "" and text:sub(1, 1) ~= "." and text:sub(-1) ~= "."
    and not text:find("..", 1, true)
end

local function codec_problem(codec, s)
  if codec == "e164-tbcd" then
    if #s < 1 or #s > 8 then
      return string.format("is %d octets, and a TBCD E.164 number 1 to 8", #s)
    end
    local digits = tbcd_digits(s)
    if not digits then
      return "is not a TBCD-string of decimal digits, '1111' filling only the"
        .. " last octet's bits 5-8"
    end
    if #digits > 15 then
      return string.format("holds %d digits, and an E.164 number at most 15", #digits)
    end
    return nil
  elseif codec == "plmn-id" then
    if #s ~= 3 then
      return string.format("is %d octets, and a PLMN identity is 3", #s)
    end
    return plmn_problem(s)
  elseif codec == "plmn-id-prefix" then
    return plmn_problem(s)
  elseif codec == "ip-address" then
    if #s < 2 then
      return "has no 2-octet address family"
    end
    local family, size = string.byte(s, 1) * 256 + string.byte(s, 2), #s - 2
    if not ((family == 1 and size == 4) or (family == 2 and size == 16)) then
      return string.format("is no IPv4 or IPv6 address (family %d, %d octets)",
        family, size)
    end
    return nil
  end
  if not valid_utf8(s, 1, #s) then
    return "is not UTF-8 text"
  end
  if codec == "digits" then
    if s == "" or s:find("[^0-9]") then
      return "is not decimal digits"
    end
  elseif codec == "labels" then
    if not labels_ok(s) then
      return "is not labels separated by dots"
    end
  elseif codec == "apn" then
    if s ~= "*" and not labels_ok(s) then
      return "is neither labels separated by dots nor the wild card *"
    end
  elseif codec == "plmn-domain" then
    if not s:lower():match("^mnc%d%d%d?%.mcc%d%d%d%.3gppnetwork%.org$") then
      return "is not mnc<MNC>.mcc<MCC>.3gppnetwork.org"
    end
  elseif codec == "epc-plmn-domain" then
    if not s:lower():match("^epc%.mnc%d%d%d?%.mcc%d%d%d%.3gppnetwork%.org$") then
      return "is not epc.mnc<MNC>.mcc<MCC>.3gppnetwork.org"
    end
  elseif codec == "time-zone" then
    if not s:match("^[+-]%d+$") then
      return "is not a sign and a number of 15 minutes"
    end
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

local function interpreted(ctx, cons, rule, message, offset, length, path, name)
  local where = M.reference(ctx.rules, cons.at)
  finding(ctx.findings, WARN, "constraint-" .. rule,
    string.format("%s (an interpreted rule, read in %s)", message,
      where and where.place or "the documents' prose"),
    offset, length, path, cons.at, name)
end

-- Checks one AVP's data against its reading's constraints and `scoped`,
-- those its command or grouped AVP holds for it.
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
        local problem
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
            problem = string.format("holds %d %s, not %s", count, rule.u,
              bounds(rule.lo, rule.hi))
          end
        elseif rule.k == "range" or rule.k == "exclude" then
          local value = integer_value(reading.type, data)
          if value and rule.k == "range" and not within(value, rule.lo, rule.hi) then
            problem = string.format("is %s, not %s", number(value),
              bounds(rule.lo, rule.hi))
          elseif value and rule.k == "exclude" then
            for _, excluded in ipairs(rule.v) do
              if value == excluded then
                problem = string.format("is %s, which the clause excludes",
                  number(value))
              end
            end
          end
        elseif rule.k == "encoding" then
          problem = codec_problem(rule.codec, data)
          if problem then
            problem = "is no " .. rule.codec .. ": it " .. problem
          end
        elseif rule.k == "bits" then
          local value = integer_value(reading.type, data)
          if value then
            local held = {}
            for _, each in ipairs(rule.b) do
              if has(value, 2 ^ each) then
                held[#held + 1] = tostring(each)
              end
            end
            if rule.r == "at-most-one" and #held > 1 then
              problem = string.format("sets bits %s, of which at most one may be",
                table.concat(held, " and "))
            elseif rule.r == "at-least-one" and #held == 0 then
              local named = {}
              for _, each in ipairs(rule.b) do
                named[#named + 1] = tostring(each)
              end
              problem = string.format("sets none of bits %s, one of which must be",
                table.concat(named, ", "))
            end
          end
        end
        if problem then
          interpreted(ctx, cons, rule.k, reading.name .. " " .. problem, avp.data,
            avp.size, path, reading.name)
        end
      end
    end
  end
end

-- Whether a predicate's condition holds of a run's AVPs: `held[identity]`
-- the first AVP of that identity.
local function condition_holds(ctx, held, condition)
  local avp = held[condition.avp]
  if not avp then
    return false
  end
  if condition.v == nil and condition.b == nil then
    return true
  end
  local reading = ctx.rules.avps[condition.avp]
  local value = reading and integer_value(reading.type, data_text(ctx.pdu, avp))
  if value == nil then
    return nil
  end
  if condition.v ~= nil then
    return value == condition.v
  end
  return has(value, 2 ^ condition.b)
end

local function conditions_text(conditions)
  local parts = {}
  for _, condition in ipairs(conditions) do
    parts[#parts + 1] = condition.t
  end
  return table.concat(parts, " or ")
end

-- Checks the predicates `scoped` (constraints by member name) states of a
-- run of AVPs: `identities` gives each name's identity in the body.
local function check_predicates(ctx, scoped, identities, avps, path, where)
  if not scoped then
    return
  end
  local held = {}
  for _, avp in ipairs(avps) do
    local identity = avp.vendor .. ":" .. avp.code
    held[identity] = held[identity] or avp
  end
  for name, list in pairs(scoped) do
    local identity = identities[name]
    local subject = identity and held[identity]
    for _, cons in ipairs(list) do
      for _, rule in ipairs(cons.rules) do
        if rule.c then
          local any, unknown = false, false
          for _, condition in ipairs(rule.c) do
            local holds = condition_holds(ctx, held, condition)
            if holds == nil then
              unknown = true
            elseif holds then
              any = true
            end
          end
          local problem
          local said = conditions_text(rule.c)
          if rule.k == "present-if" and any and not subject then
            problem = string.format("%s is missing from %s, which holds %s", name,
              where, said)
          elseif rule.k == "absent-if" and any and subject then
            problem = string.format("%s is in %s, which holds %s", name, where, said)
          elseif rule.k == "requires" and subject and not any and not unknown then
            problem = string.format("%s is in %s, which does not hold %s", name,
              where, said)
          elseif rule.k == "excludes" and subject and any then
            problem = string.format("%s is in %s with %s", name, where, said)
          end
          if problem then
            local at = subject or {}
            interpreted(ctx, cons, rule.k, problem, at.offset or ctx.anchor_offset,
              at.length or ctx.anchor_length, path, name)
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
        return ERROR, "was withdrawn (void)"
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
  return WARN, "is not a value the document defines"
end

-- Validation of a run of AVPs against a body.

local validate_body

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
    local where = M.reference(ctx.rules, cite)
    where = where and where.short or reading.read_through
    if rule == "must" and not set then
      finding(ctx.findings, ERROR, "flag-must",
        string.format("%s: the %s bit must be set (%s)", reading.name, letter, where),
        avp.offset + 4, 1, path, cite, reading.name)
    elseif rule == "must_not" and set then
      finding(ctx.findings, ERROR, "flag-must-not",
        string.format("%s: the %s bit must not be set (%s)", reading.name, letter,
          where),
        avp.offset + 4, 1, path, cite, reading.name)
    elseif rule == "should_not" and set then
      finding(ctx.findings, WARN, "flag-should-not",
        string.format("%s: the %s bit should not be set (%s)", reading.name, letter,
          where),
        avp.offset + 4, 1, path, cite, reading.name)
    elseif rule == nil and letter == "P" and set then
      -- RFC 6733 section 4.1: no end-to-end security is specified, "therefore,
      -- the P bit SHOULD be set to 0".
      about(finding(ctx.findings, WARN, "flag-p",
        string.format("%s: the P bit is set, which RFC 6733 section 4.1 says"
          .. " should be 0", reading.name),
        avp.offset + 4, 1, path), reading)
    end
  end
end

-- `path` is where the AVP sits, `inner` the AVP itself, for what it holds.
local function check_data(ctx, avp, reading, path, inner, depth)
  local kind = reading.type
  local findings = ctx.findings
  local pdu = ctx.pdu
  local size = FIXED_SIZE[kind]
  if size then
    if avp.size ~= size then
      about(finding(findings, ERROR, "data-length",
        string.format("%s is %s, %d octets, but holds %d", reading.name, kind, size,
          avp.size),
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
          string.format("%s: %d %s", reading.name, value, problem),
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
            string.format("Result-Code %d is not one any document defines", value),
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
            string.format("%s sets bit %s, which no document names", reading.name,
              table.concat(unknown, ", ")),
            avp.data, 4, path, ctx.rules.bits_at[identity] or reading.at, reading.name)
        end
      end
    end
    return
  end
  if kind == "UTF8String" then
    local ok, at = valid_utf8(pdu, avp.data + 1, avp.data + avp.size)
    if not ok then
      about(finding(findings, ERROR, "utf8",
        string.format("%s is not valid UTF-8 at octet %d", reading.name, at),
        avp.data + at, 1, path), reading)
    end
  elseif kind == "DiameterIdentity" then
    local problem = identity_problem(data_text(pdu, avp))
    if problem then
      about(finding(findings, ERROR, "diameter-identity",
        reading.name .. " " .. problem, avp.data, avp.size, path), reading)
    end
  elseif kind == "DiameterURI" then
    local problem = uri_problem(data_text(pdu, avp))
    if problem then
      about(finding(findings, ERROR, "diameter-uri", reading.name .. " " .. problem,
        avp.data, avp.size, path), reading)
    end
  elseif kind == "IPFilterRule" then
    local problem = filter_problem(data_text(pdu, avp))
    if problem then
      about(finding(findings, ERROR, "ip-filter-rule", reading.name .. " " .. problem,
        avp.data, avp.size, path), reading)
    end
  elseif kind == "Address" then
    if avp.size < 2 then
      about(finding(findings, ERROR, "address",
        reading.name .. " is shorter than its 2-octet address family",
        avp.offset, avp.length, path), reading)
      return
    end
    local family = string.byte(pdu, avp.data + 1) * 256 + string.byte(pdu, avp.data + 2)
    local expected = ({ [1] = 4, [2] = 16 })[family]
    if expected and avp.size - 2 ~= expected then
      about(finding(findings, ERROR, "address",
        string.format("%s is an IPv%d address of %d octets, not %d", reading.name,
          family == 1 and 4 or 6, avp.size - 2, expected),
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
          "Failed-AVP holds no AVP, and its rule requires at least one",
          avp.offset, avp.length, path, reading.at, reading.name)
      end
      return
    end
    local held = parse_avps(pdu, avp.data, avp.data + avp.size, findings, inner)
    if reading.members == nil then
      -- Typed Grouped by a table that prints no rule for it (TS 29.128's
      -- APN-Rate-Control-Status, OMA's charging AVPs): what it holds is
      -- framed, and no body says more of it.
      return
    end
    validate_body(ctx, reading.members, held, inner, depth + 1, reading)
  end
end

local function member_label(member)
  return member.name
end

-- Checks a run of AVPs against `body`: occurrences, positions, what the
-- wildcard admits, each AVP's flags and data, and grouped AVPs inside.
validate_body = function(ctx, body, avps, path, depth, owner)
  local rules = ctx.rules
  local findings = ctx.findings
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
  local unlisted = 0
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
      reading = rules.avps[slot.member.id]
      name = slot.member.name
    else
      reading = rules.avps[identity]
      name = avp_label(rules, avp)
      unlisted = unlisted + 1
      if not body.wildcard then
        local where = owner and owner.name or ctx.where
        finding(findings, ERROR, "avp-not-allowed",
          string.format("%s is not allowed in %s, whose ABNF has no * [ AVP ]",
            name, where),
          avp.offset, avp.length, path, cite, cite_name)
      elseif ctx.prefs.wildcard_notes then
        finding(findings, NOTE, "avp-by-wildcard",
          string.format("%s is not in the ABNF; * [ AVP ] admits it", name),
          avp.offset, avp.length, path, cite, cite_name)
      end
    end
    local inner_path = path and (path .. " > " .. name) or name
    if reading then
      check_flags(ctx, avp, reading, path)
      check_data(ctx, avp, reading, path, inner_path, depth)
      check_constraints(ctx, avp, reading, path, scoped and scoped[name])
    elseif has(avp.flags, AVP_M) then
      about(finding(findings, WARN, "unknown-mandatory",
        string.format("%s is defined by no document in the corpus and has the M"
          .. " bit set: a receiver that does not know it answers"
          .. " DIAMETER_AVP_UNSUPPORTED", name),
        avp.offset, avp.length, path), nil, identity)
    else
      finding(findings, NOTE, "unknown-avp",
        string.format("%s is defined by no document in the corpus", name),
        avp.offset, avp.length, path)
    end
  end
  -- Occurrences.
  local where = owner and owner.name or ctx.where
  check_predicates(ctx, scoped, identities, avps, path, where)
  local wildcard = body.wildcard
  if wildcard and unlisted < wildcard.min then
    finding(findings, ERROR, "avp-missing",
      string.format("%s requires %d AVP%s beyond those it lists, it holds %d",
        where, wildcard.min, wildcard.min == 1 and "" or "s", unlisted),
      ctx.anchor_offset, ctx.anchor_length, path, cite, cite_name)
  elseif wildcard and wildcard.max >= 0 and unlisted > wildcard.max then
    finding(findings, ERROR, "avp-occurrences",
      string.format("%s allows %d AVP%s beyond those it lists, it holds %d",
        where, wildcard.max, wildcard.max == 1 and "" or "s", unlisted),
      ctx.anchor_offset, ctx.anchor_length, path, cite, cite_name)
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
    if count < bound.min then
      finding(findings, ERROR, "avp-missing",
        string.format("%s requires %s%s, which is missing", where,
          bound.min > 1 and (bound.min .. " of ") or "", member_label(member)),
        ctx.anchor_offset, ctx.anchor_length, path, cite, cite_name)
    elseif bound.max >= 0 and count > bound.max then
      finding(findings, ERROR, "avp-occurrences",
        string.format("%s allows %s at most %d time%s, it occurs %d", where,
          member_label(member), bound.max, bound.max == 1 and "" or "s", count),
        ctx.anchor_offset, ctx.anchor_length, path, cite, cite_name)
    end
  end
  for _, member in ipairs(body) do
    if not member.id and (member.hole or member.placeholder) then
      finding(findings, NOTE, "unverifiable",
        string.format("%s names %s, which the corpus cannot complete (%s)", where,
          member.name, member.hole or "undefined"),
        ctx.anchor_offset, ctx.anchor_length, path, cite, cite_name)
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
          string.format("%s must be AVP %d of %s, it is AVP %d", member.name,
            expected, where, at),
          avp.offset, avp.length, path, cite, cite_name)
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
        string.format("%s must be among the last AVPs of %s", member.name, where),
        avp.offset, avp.length, path, cite, cite_name)
    end
    expected = expected + 1
  end
end

-- One candidate: validates the message's AVPs against `body`.
local function run(rules, prefs, pdu, avps, header_findings, form, anchor)
  local ctx = {
    rules = rules,
    prefs = prefs,
    pdu = pdu,
    findings = {},
    where = form.where,
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

local function score(findings)
  local errors, warnings = 0, 0
  for _, each in ipairs(findings) do
    if each.severity == ERROR then
      errors = errors + 1
    elseif each.severity == WARN then
      warnings = warnings + 1
    end
  end
  return errors, warnings
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

-- Validates one Diameter PDU, a string of its octets. Returns a table:
--   command     the chosen candidate {name, abbreviation, document, section}
--   reference   where the command is defined (`M.reference`), or nil
--   form        "command", "answer-message" or nil when nothing matched
--   findings    {severity, rule, message, offset, length, path, reference},
--               `reference` where the rule broken is written, or nil
--   others      the other candidates, each {candidate, errors, warnings}
--   header      code, flags, application, length
function M.validate(rules, pdu, prefs)
  prefs = prefs or {}
  local header_findings = {}
  local result = { findings = header_findings, others = {} }
  if #pdu < 20 then
    finding(header_findings, ERROR, "header-truncated",
      string.format("%d octets, too few for a Diameter header", #pdu), 0, #pdu)
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
      string.format("version %d, not 1", version), 0, 1)
  end
  if length ~= #pdu then
    finding(header_findings, ERROR, "header-length",
      string.format("the header declares %d octets, the message holds %d", length,
        #pdu), 1, 3)
  end
  if length % 4 ~= 0 then
    finding(header_findings, ERROR, "header-length",
      string.format("message length %d is not a multiple of 4", length), 1, 3)
  end
  if flags % 16 ~= 0 then
    finding(header_findings, WARN, "header-reserved-flags",
      string.format("reserved command flag bits set (0x%02x)", flags % 16), 4, 1)
  end
  if request and error_bit then
    finding(header_findings, ERROR, "header-e-bit",
      "the E bit is set on a request; RFC 6733 section 3 sets it on answers only", 4, 1)
  end
  if not request and has(flags, CMD_T) then
    finding(header_findings, ERROR, "header-t-bit",
      "the T bit is set on an answer; RFC 6733 section 3 sets it on requests only",
      4, 1)
  end
  local last = math.min(length, #pdu)
  local avps = parse_avps(pdu, 20, last, header_findings, nil)

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
            cite = answer.at,
          }
        end
      else
        forms[#forms + 1] = {
          candidate = candidate,
          body = candidate.members,
          form = "command",
          where = candidate.abbreviation,
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
      cite = answer.at,
    }
  end
  if #forms == 0 then
    finding(header_findings, NOTE, "unknown-command",
      string.format("no document in the corpus defines command %d %s in"
        .. " application %d", code, request and "request" or "answer", looked_up),
      5, 3)
    return M.cited(rules, result, prefs)
  end

  local best, best_ctx, best_errors, best_warnings
  local runs = {}
  for _, form in ipairs(forms) do
    local ctx = run(rules, prefs, pdu, avps, header_findings, form, { 5, 3 })
    local errors, warnings = score(ctx.findings)
    runs[#runs + 1] = { form = form, ctx = ctx, errors = errors, warnings = warnings }
    -- Fewest errors, then fewest warnings, then the body listing the most of
    -- the message's AVPs rather than leaving them to * [ AVP ]; on a tie the
    -- first, which the generator orders by what the registry allocates.
    if best == nil or errors < best_errors
      or (errors == best_errors and (warnings < best_warnings
        or (warnings == best_warnings and ctx.listed > best_ctx.listed))) then
      best, best_ctx, best_errors, best_warnings = form, ctx, errors, warnings
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
        string.format("Experimental-Result-Code %d is not one any document defines",
          each.value),
        each.offset, 4, each.path, each.cite, "Experimental-Result-Code")
    end
  end
  local result_code = best_ctx.result_code
  if result_code and not request then
    local protocol = result_code >= 3000 and result_code < 4000
    if protocol and not error_bit then
      finding(best_ctx.findings, WARN, "e-bit-missing",
        string.format("Result-Code %d is a protocol error, which RFC 6733 section"
          .. " 7.1.3 answers with the E bit set", result_code), 4, 1)
    elseif error_bit and not protocol then
      finding(best_ctx.findings, WARN, "e-bit-unexpected",
        string.format("the E bit is set but Result-Code %d is no protocol error"
          .. " (3xxx)", result_code), 4, 1)
    end
  end
  if best.candidate then
    if best.candidate.proxiable ~= nil
      and best.candidate.proxiable ~= has(flags, CMD_P) then
      finding(best_ctx.findings, ERROR, "header-p-bit",
        string.format("the P bit is %s, but %s's header %s PXY",
          has(flags, CMD_P) and "set" or "clear", best.candidate.abbreviation,
          best.candidate.proxiable and "prints" or "does not print"), 4, 1, nil,
        best.candidate.at, best.candidate.name)
    end
  end

  result.command = best.candidate
  result.form = best.form
  result.where = best.where
  result.findings = best_ctx.findings
  for _, each in ipairs(runs) do
    if each.form ~= best and each.form.candidate then
      result.others[#result.others + 1] = {
        candidate = each.form.candidate, errors = each.errors, warnings = each.warnings,
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

-- Gives each finding its `reference` (`M.reference`), a base check RFC 6733's
-- section, and the result the `reference` of its command's definition. The
-- explorer links start at `prefs.explorer`, else `rules.explorer`; an empty
-- address leaves them out. A finding with a reference has an explorer link
-- whenever there is an address: where its cited clause holds nothing the
-- explorer can show, `explore_instead`'s.
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
M.digit_count = digit_count
M.valid_utf8 = valid_utf8
M.identity_problem = identity_problem
M.uri_problem = uri_problem

return M
