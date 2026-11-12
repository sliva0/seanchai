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
-- A reading's `at` and `flags_at`, a command's and an answer's `at`, and
-- `bits_at[identity]` are numbers into `cites`: where the rule is written.

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
-- written, and `name` what the explorer looks for there.
local function finding(list, severity, rule, message, offset, length, path, cite, name)
  list[#list + 1] = {
    severity = severity,
    rule = rule,
    message = message,
    offset = offset,
    length = length,
    path = path,
    cite = cite,
    cite_name = name,
  }
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
  local site
  if explorer and not at[5] then
    site = explorer .. "#" .. uri_component(id) .. "/" .. uri_component(clause)
    if name then
      site = site .. "?name=" .. form_value(name)
    end
  end
  return {
    document = doc[1], text = text, short = short, clause = clause, page = page,
    table = table_label, url = link, explorer = site,
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
    if length < header then
      finding(findings, ERROR, "avp-length",
        string.format("AVP %d declares length %d, below its %d-octet header",
          code, length, header),
        at, math.min(8, last - at), path)
      break
    end
    if at + length > last then
      finding(findings, ERROR, "avp-length",
        string.format("AVP %d declares length %d, past the end of what holds it",
          code, length),
        at, last - at, path)
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
      finding(findings, WARN, "avp-reserved-flags",
        string.format("reserved AVP flag bits set (0x%02x)", flags % 32),
        at + 4, 1, path)
    end
    if at + padded > last then
      if padded ~= length then
        finding(findings, ERROR, "avp-padding",
          "the AVP's padding runs past the end of what holds it",
          at, last - at, path)
      end
      break
    end
    for i = at + length, at + padded - 1 do
      if u8(pdu, i + 1) ~= 0 then
        finding(findings, WARN, "avp-padding", "nonzero padding octets",
          at + length, padded - length, path)
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

local function avp_label(rules, avp)
  local reading = rules.avps[avp.vendor .. ":" .. avp.code]
  if reading then
    return reading.name
  end
  return string.format("AVP %d (vendor %d)", avp.code, avp.vendor)
end

local function data_text(pdu, avp)
  return pdu:sub(avp.data + 1, avp.data + avp.size)
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
  if reading.values_open then
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
  -- The table row the flag rules are read from, which each finding names.
  local cite = reading.flags_at
  local where = M.reference(ctx.rules, cite)
  where = where and where.short or reading.read_through
  for _, letter in ipairs({ "M", "V", "P" }) do
    local set = has(avp.flags, bits[letter])
    local rule = rule_for(letter)
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
      finding(ctx.findings, WARN, "flag-p",
        string.format("%s: the P bit is set, which RFC 6733 section 4.1 says"
          .. " should be 0", reading.name),
        avp.offset + 4, 1, path)
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
      finding(findings, ERROR, "data-length",
        string.format("%s is %s, %d octets, but holds %d", reading.name, kind, size,
          avp.size),
        avp.offset, avp.length, path,
        -- Time and Enumerated are section 4.3.1's, the rest section 4.2's.
        ctx.rules.base and ctx.rules.base[(kind == "Time" or kind == "Enumerated")
          and "derived" or "basic"])
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
      finding(findings, ERROR, "utf8",
        string.format("%s is not valid UTF-8 at octet %d", reading.name, at),
        avp.data + at, 1, path)
    end
  elseif kind == "DiameterIdentity" then
    local problem = identity_problem(data_text(pdu, avp))
    if problem then
      finding(findings, ERROR, "diameter-identity",
        reading.name .. " " .. problem, avp.data, avp.size, path)
    end
  elseif kind == "DiameterURI" then
    local problem = uri_problem(data_text(pdu, avp))
    if problem then
      finding(findings, ERROR, "diameter-uri", reading.name .. " " .. problem,
        avp.data, avp.size, path)
    end
  elseif kind == "IPFilterRule" then
    local problem = filter_problem(data_text(pdu, avp))
    if problem then
      finding(findings, ERROR, "ip-filter-rule", reading.name .. " " .. problem,
        avp.data, avp.size, path)
    end
  elseif kind == "Address" then
    if avp.size < 2 then
      finding(findings, ERROR, "address",
        reading.name .. " is shorter than its 2-octet address family",
        avp.offset, avp.length, path)
      return
    end
    local family = string.byte(pdu, avp.data + 1) * 256 + string.byte(pdu, avp.data + 2)
    local expected = ({ [1] = 4, [2] = 16 })[family]
    if expected and avp.size - 2 ~= expected then
      finding(findings, ERROR, "address",
        string.format("%s is an IPv%d address of %d octets, not %d", reading.name,
          family == 1 and 4 or 6, avp.size - 2, expected),
        avp.data, avp.size, path)
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
  for index, member in ipairs(body) do
    if member.id then
      local identity = member.id:gsub("#%d+$", "")
      by_identity[identity] = by_identity[identity] or { member = member, index = index }
    end
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
    elseif has(avp.flags, AVP_M) then
      finding(findings, WARN, "unknown-mandatory",
        string.format("%s is defined by no document in the corpus and has the M"
          .. " bit set: a receiver that does not know it answers"
          .. " DIAMETER_AVP_UNSUPPORTED", name),
        avp.offset, avp.length, path)
    else
      finding(findings, NOTE, "unknown-avp",
        string.format("%s is defined by no document in the corpus", name),
        avp.offset, avp.length, path)
    end
  end
  -- Occurrences.
  local where = owner and owner.name or ctx.where
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
  for _, member in ipairs(body) do
    if member.id then
      local identity = member.id:gsub("#%d+$", "")
      local count = counts[identity] or 0
      if count < member.min then
        finding(findings, ERROR, "avp-missing",
          string.format("%s requires %s%s, which is missing", where,
            member.min > 1 and (member.min .. " of ") or "", member_label(member)),
          ctx.anchor_offset, ctx.anchor_length, path, cite, cite_name)
      elseif member.max >= 0 and count > member.max then
        finding(findings, ERROR, "avp-occurrences",
          string.format("%s allows %s at most %d time%s, it occurs %d", where,
            member_label(member), member.max, member.max == 1 and "" or "s", count),
          ctx.anchor_offset, ctx.anchor_length, path, cite, cite_name)
      end
    elseif member.hole or member.placeholder then
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
    local identity = member.id and member.id:gsub("#%d+$", "")
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
    local identity = member.id and member.id:gsub("#%d+$", "")
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

-- Gives each finding its `reference` (`M.reference`), a base check RFC 6733's
-- section, and the result the `reference` of its command's definition. The
-- explorer links start at `prefs.explorer`, else `rules.explorer`; an empty
-- address leaves them out.
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
  end
  if result.command then
    result.reference = M.reference(rules, result.command.at, result.command.name,
      explorer)
  end
  return result
end

M.parse_avps = parse_avps
M.valid_utf8 = valid_utf8
M.identity_problem = identity_problem
M.uri_problem = uri_problem

return M
