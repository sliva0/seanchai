-- Seanchaí Diameter validation: the Wireshark side.
--
-- A post-dissector: after Wireshark's own Diameter dissector has reassembled
-- and dissected a frame, every `diameter` PDU in it is handed, as its bytes,
-- to `core.validate`, which reads them on its own rather than through
-- Wireshark's dictionary. What it finds becomes a `seanchai` subtree, expert
-- info on the octets concerned and fields a display filter can use:
--
--   seanchai.errors > 0          messages breaking a rule of their document
--   seanchai.warnings > 0, seanchai.notes > 0
--   seanchai.interpreted         breaches of rules read in prose, notes
--   seanchai.rule == "avp-missing"
--   seanchai.document == "TS29.272"
--   seanchai.cited == "TS29.061"  findings citing a document
--   seanchai.request_missing     answers whose rules on the request went
--                                unchecked, the request not in the capture
--   seanchai.request_frame       the request an answer's findings were read
--                                against
--
-- A post-dissector cannot add to the items Wireshark's Diameter dissector
-- drew, so the findings are listed in the subtree, each on its AVP's octets
-- and named by the AVP's place shortened ("… > Parent > AVP"); the whole
-- path is beneath it.
--
-- Each finding, and the command it was held to, has the place its rule is
-- written beneath it: a reference ("TS 29.061 clause 16a.5, table 9a, page
-- 129"), the publisher's copy at that place and the explorer site's. They are
-- string fields: Wireshark's Lua API has no way to mark a field as a URL (C
-- dissectors' proto_item_set_url), so they are copied (Copy, Value) rather
-- than clicked.
--
-- `seanchai wireshark-plugin` puts `EXPLORER`, `RULES` and `core` in scope
-- ahead of this file. `EXPLORER` is the explorer preference's default, on the
-- file's one line marked seanchai:explorer.

local proto = Proto("seanchai", "Seanchaí Diameter validation")

local fields = {
  command = ProtoField.string("seanchai.command", "Command"),
  document = ProtoField.string("seanchai.document", "Document"),
  section = ProtoField.string("seanchai.section", "Section"),
  form = ProtoField.string("seanchai.form", "Checked against"),
  errors = ProtoField.uint32("seanchai.errors", "Errors"),
  warnings = ProtoField.uint32("seanchai.warnings", "Warnings"),
  notes = ProtoField.uint32("seanchai.notes", "Notes"),
  finding = ProtoField.string("seanchai.finding", "Finding"),
  rule = ProtoField.string("seanchai.rule", "Rule"),
  path = ProtoField.string("seanchai.path", "Path"),
  element = ProtoField.string("seanchai.element", "Element"),
  candidate = ProtoField.string("seanchai.candidate", "Other definition"),
  corpus = ProtoField.string("seanchai.corpus", "Corpus"),
  reference = ProtoField.string("seanchai.reference", "Reference"),
  cited = ProtoField.string("seanchai.cited", "Cited document"),
  url = ProtoField.string("seanchai.url", "Specification"),
  explorer = ProtoField.string("seanchai.explorer", "Explorer"),
  request_missing = ProtoField.uint32("seanchai.request_missing",
    "Rules on the request unchecked"),
  request_frame = ProtoField.framenum("seanchai.request_frame", "Request",
    base.NONE, frametype and frametype.REQUEST or nil),
}
proto.fields = {
  fields.command, fields.document, fields.section, fields.form, fields.errors,
  fields.warnings, fields.notes, fields.finding, fields.rule, fields.path,
  fields.element, fields.candidate,
  fields.corpus, fields.reference, fields.cited, fields.url, fields.explorer,
  fields.request_missing, fields.request_frame,
}

local experts = {
  error = ProtoExpert.new("seanchai.violation", "Breaks its specification",
    expert.group.MALFORMED, expert.severity.ERROR),
  warn = ProtoExpert.new("seanchai.warning", "Departs from its specification",
    expert.group.PROTOCOL, expert.severity.WARN),
  note = ProtoExpert.new("seanchai.note", "Specification note",
    expert.group.PROTOCOL, expert.severity.NOTE),
  -- A rule a person read in a clause's prose: a note, however the
  -- specification words it, since the reading is ours.
  interpreted = ProtoExpert.new("seanchai.interpreted", "Breaks an interpreted rule",
    expert.group.PROTOCOL, expert.severity.NOTE),
}
proto.experts = { experts.error, experts.warn, experts.note, experts.interpreted }

proto.prefs.pin = Pref.string("Pinned documents", "",
  "Comma-separated references (TS29.229, RFC8506) to check a command against"
  .. " alone where they define it, instead of the best match among every"
  .. " document defining it")
proto.prefs.wildcard_notes = Pref.bool("Note AVPs only * [ AVP ] admits", false,
  "Add a note for every AVP the command's ABNF does not list and its"
  .. " * [ AVP ] admits")
proto.prefs.explorer_url = Pref.string("Explorer address", EXPLORER,
  "The explorer site each reference links to at its clause; empty for no"
  .. " such links")

local diameter = Field.new("diameter")
-- The request frame Wireshark's own Diameter dissector pairs an answer with,
-- by conversation, Hop-by-Hop and End-to-End identifiers.
local answer_to = Field.new("diameter.answer_to")

-- What the rules read of each request met (`core.request_values`), until
-- its answer comes: by the request's frame and identifiers, as Wireshark
-- pairs them, and by its endpoints and identifiers, for an answer Wireshark
-- did not pair. Kept from the first pass, so a frame dissected again finds
-- the request whatever the order; at most MAX_KEPT requests, the oldest
-- dropped first, and cleared with each capture.
local MAX_KEPT = 100000
local kept_by_frame, kept_by_peer, kept_order, kept_first = {}, {}, {}, 1

function proto.init()
  kept_by_frame, kept_by_peer, kept_order, kept_first = {}, {}, {}, 1
end

-- The two endpoints, either way round, and the identifiers: an answer
-- travels back the way its request came, or, captured at a relay, on.
local function peer_key(pinfo, ids)
  local one = tostring(pinfo.src) .. "/" .. tostring(pinfo.src_port)
  local other = tostring(pinfo.dst) .. "/" .. tostring(pinfo.dst_port)
  if other < one then
    one, other = other, one
  end
  return one .. "|" .. other .. "|" .. ids
end

local function keep(pinfo, ids, values)
  local frame = pinfo.number
  local entry = { frame = frame, values = values }
  kept_by_frame[frame] = kept_by_frame[frame] or {}
  kept_by_frame[frame][ids] = entry
  local peer = peer_key(pinfo, ids)
  kept_by_peer[peer] = entry
  kept_order[#kept_order + 1] = { frame = frame, ids = ids, peer = peer }
  if #kept_order - kept_first + 1 > MAX_KEPT then
    local oldest = kept_order[kept_first]
    kept_order[kept_first] = nil
    kept_first = kept_first + 1
    local frames = kept_by_frame[oldest.frame]
    if frames then
      frames[oldest.ids] = nil
    end
    if kept_by_peer[oldest.peer] and kept_by_peer[oldest.peer].frame == oldest.frame then
      kept_by_peer[oldest.peer] = nil
    end
  end
end

-- The request kept for an answer: the frame Wireshark pairs it with, else
-- the last request between the same endpoints with its identifiers.
local function kept_for(pinfo, ids, paired)
  for _, frame in ipairs(paired) do
    local frames = kept_by_frame[frame]
    if frames and frames[ids] then
      return frames[ids]
    end
  end
  local entry = kept_by_peer[peer_key(pinfo, ids)]
  if entry and entry.frame < pinfo.number then
    return entry
  end
  return nil
end

local LABELS = { error = "Error", warn = "Warning", note = "Note" }

local function clamp(range, offset, length)
  local total = range:len()
  if offset >= total then
    offset, length = 0, 0
  end
  if offset + length > total then
    length = total - offset
  end
  return range:range(offset, length)
end

-- The reference beneath `item`: its text, with the document, and both links.
local function cite(item, range, reference)
  if not reference then
    return
  end
  local text = item:add(fields.reference, range, reference.text)
  text:set_generated()
  text:add(fields.cited, range, reference.document):set_generated()
  if reference.url then
    item:add(fields.url, range, reference.url):set_generated()
  end
  if reference.explorer then
    -- The link may go elsewhere than the reference, to where the AVP or the
    -- command is defined: the label says where, the value stays the URL.
    local link
    if reference.explorer_place then
      link = item:add(fields.explorer, range, reference.explorer,
        string.format("Explorer: %s: %s", reference.explorer_place,
          reference.explorer))
    else
      link = item:add(fields.explorer, range, reference.explorer)
    end
    link:set_generated()
  end
end

local function describe(candidate)
  return string.format("%s (%s) in %s section %s", candidate.name,
    candidate.abbreviation, candidate.document, candidate.section)
end

local function counted(count, word)
  return string.format("%d %s%s", count, word, count == 1 and "" or "s")
end

-- "1 error, 0 warnings, 2 notes".
local function tally(errors, warnings, notes)
  return counted(errors, "error") .. ", " .. counted(warnings, "warning") .. ", "
    .. counted(notes, "note")
end

function proto.dissector(tvb, pinfo, tree)
  local pdus = { diameter() }
  if #pdus == 0 then
    return
  end
  local prefs = {
    pin = proto.prefs.pin,
    wildcard_notes = proto.prefs.wildcard_notes,
    explorer = proto.prefs.explorer_url,
  }
  local paired = {}
  for _, each in ipairs({ answer_to() }) do
    paired[#paired + 1] = each.value
  end
  local total_errors = 0
  for _, info in ipairs(pdus) do
    local range = info.range
    local bytes = range:bytes():raw()
    -- The Hop-by-Hop and End-to-End identifiers, octets 13 to 20.
    local ids = bytes:sub(13, 20)
    local values = core.request_values(RULES, bytes)
    if values and not pinfo.visited then
      keep(pinfo, ids, values)
    end
    local request
    if #bytes >= 20 and range:range(4, 1):uint() < 128 then
      request = kept_for(pinfo, ids, paired)
    end
    local result = core.validate(RULES, bytes, prefs, request and request.values)
    local subtree = tree:add(proto, range)
    local counts = { error = 0, warn = 0, note = 0 }
    for _, each in ipairs(result.findings) do
      counts[each.severity] = counts[each.severity] + 1
    end
    total_errors = total_errors + counts.error
    local candidate = result.command
    local said = tally(counts.error, counts.warn, counts.note)
    if candidate then
      subtree:append_text(": " .. candidate.abbreviation .. ", " .. said)
      local command = subtree:add(fields.command, clamp(range, 5, 3), describe(candidate))
      cite(command, clamp(range, 5, 3), result.reference)
      subtree:add(fields.document, clamp(range, 5, 3), candidate.document)
      subtree:add(fields.section, clamp(range, 5, 3), candidate.section)
    else
      subtree:append_text(": " .. said)
    end
    if result.where then
      subtree:add(fields.form, clamp(range, 0, 0), result.where)
    end
    if request then
      subtree:add(fields.request_frame, clamp(range, 0, 0), request.frame)
        :set_generated()
    elseif result.request_unchecked and result.request_unchecked > 0 then
      subtree:add(fields.request_missing, clamp(range, 0, 0), result.request_unchecked)
        :set_generated()
    end
    subtree:add(fields.errors, clamp(range, 0, 0), counts.error)
    subtree:add(fields.warnings, clamp(range, 0, 0), counts.warn)
    subtree:add(fields.notes, clamp(range, 0, 0), counts.note)
    for _, each in ipairs(result.findings) do
      local at = clamp(range, each.offset, each.length)
      -- The line alone, without the field's name before it.
      local line = LABELS[each.severity] .. ": " .. each.line
      local item = subtree:add(fields.finding, at, line, line)
      item:add(fields.rule, at, each.rule)
      item:add(fields.path, at, each.path):set_generated()
      if each.element then
        -- The element another document defines, and where it was read.
        item:add(fields.element, at, each.element):set_generated()
      end
      if each.request and request then
        item:add(fields.request_frame, at, request.frame):set_generated()
      end
      cite(item, at, each.reference)
      item:add_proto_expert_info(
        each.interpreted and experts.interpreted or experts[each.severity], each.full)
    end
    for _, other in ipairs(result.others) do
      subtree:add(fields.candidate, clamp(range, 0, 0),
        describe(other.candidate) .. ": "
          .. tally(other.errors, other.warnings, other.notes))
    end
    subtree:add(fields.corpus, clamp(range, 0, 0), RULES.corpus)
  end
  if total_errors > 0 then
    pinfo.cols.info:append(string.format(" [%d spec error%s]", total_errors,
      total_errors == 1 and "" or "s"))
  end
end

register_postdissector(proto)
