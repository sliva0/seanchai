-- Seanchaí Diameter validation: the Wireshark side.
--
-- A post-dissector: after Wireshark's own Diameter dissector has reassembled
-- and dissected a frame, every `diameter` PDU in it is handed, as its bytes,
-- to `core.validate`, which reads them on its own rather than through
-- Wireshark's dictionary. What it finds becomes a `seanchai` subtree, expert
-- info on the octets concerned and fields a display filter can use:
--
--   seanchai.errors > 0          messages breaking a rule of their document
--   seanchai.rule == "avp-missing"
--   seanchai.document == "TS29.272"
--
-- generate.py puts `RULES` and `core` in scope ahead of this file.

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
  candidate = ProtoField.string("seanchai.candidate", "Other definition"),
  corpus = ProtoField.string("seanchai.corpus", "Corpus"),
}
proto.fields = {
  fields.command, fields.document, fields.section, fields.form, fields.errors,
  fields.warnings, fields.notes, fields.finding, fields.rule, fields.candidate,
  fields.corpus,
}

local experts = {
  error = ProtoExpert.new("seanchai.violation", "Breaks its specification",
    expert.group.MALFORMED, expert.severity.ERROR),
  warn = ProtoExpert.new("seanchai.warning", "Departs from its specification",
    expert.group.PROTOCOL, expert.severity.WARN),
  note = ProtoExpert.new("seanchai.note", "Specification note",
    expert.group.PROTOCOL, expert.severity.NOTE),
}
proto.experts = { experts.error, experts.warn, experts.note }

proto.prefs.pin = Pref.string("Pinned documents", "",
  "Comma-separated references (TS29.229, RFC8506) to check a command against"
  .. " alone where they define it, instead of the best match among every"
  .. " document defining it")
proto.prefs.wildcard_notes = Pref.bool("Note AVPs only * [ AVP ] admits", false,
  "Add a note for every AVP the command's ABNF does not list and its"
  .. " * [ AVP ] admits")

local diameter = Field.new("diameter")

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

local function describe(candidate)
  return string.format("%s (%s) in %s section %s", candidate.name,
    candidate.abbreviation, candidate.document, candidate.section)
end

function proto.dissector(tvb, pinfo, tree)
  local pdus = { diameter() }
  if #pdus == 0 then
    return
  end
  local prefs = {
    pin = proto.prefs.pin,
    wildcard_notes = proto.prefs.wildcard_notes,
  }
  local total_errors = 0
  for _, info in ipairs(pdus) do
    local range = info.range
    local result = core.validate(RULES, range:bytes():raw(), prefs)
    local subtree = tree:add(proto, range)
    local counts = { error = 0, warn = 0, note = 0 }
    for _, each in ipairs(result.findings) do
      counts[each.severity] = counts[each.severity] + 1
    end
    total_errors = total_errors + counts.error
    local candidate = result.command
    if candidate then
      subtree:append_text(string.format(": %s, %d error%s, %d warning%s",
        candidate.abbreviation, counts.error, counts.error == 1 and "" or "s",
        counts.warn, counts.warn == 1 and "" or "s"))
      subtree:add(fields.command, clamp(range, 5, 3), describe(candidate))
      subtree:add(fields.document, clamp(range, 5, 3), candidate.document)
      subtree:add(fields.section, clamp(range, 5, 3), candidate.section)
    else
      subtree:append_text(string.format(": %d error%s, %d warning%s",
        counts.error, counts.error == 1 and "" or "s", counts.warn,
        counts.warn == 1 and "" or "s"))
    end
    if result.where then
      subtree:add(fields.form, clamp(range, 0, 0), result.where)
    end
    subtree:add(fields.errors, clamp(range, 0, 0), counts.error)
    subtree:add(fields.warnings, clamp(range, 0, 0), counts.warn)
    subtree:add(fields.notes, clamp(range, 0, 0), counts.note)
    for _, each in ipairs(result.findings) do
      local text = each.message
      if each.path then
        text = each.path .. ": " .. text
      end
      local item = subtree:add(fields.finding, clamp(range, each.offset, each.length),
        LABELS[each.severity] .. ": " .. text)
      item:add(fields.rule, clamp(range, each.offset, each.length), each.rule)
      item:add_proto_expert_info(experts[each.severity], text)
    end
    for _, other in ipairs(result.others) do
      subtree:add(fields.candidate, clamp(range, 0, 0),
        string.format("%s: %d error%s, %d warning%s", describe(other.candidate),
          other.errors, other.errors == 1 and "" or "s", other.warnings,
          other.warnings == 1 and "" or "s"))
    end
    subtree:add(fields.corpus, clamp(range, 0, 0), RULES.corpus)
  end
  if total_errors > 0 then
    pinfo.cols.info:append(string.format(" [%d spec error%s]", total_errors,
      total_errors == 1 and "" or "s"))
  end
end

register_postdissector(proto)
