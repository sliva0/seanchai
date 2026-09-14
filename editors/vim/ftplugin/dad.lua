-- Zebra-stripes table rows (the lines after a `; Columns:` directive) with
-- extmarks so wide rows are easier to follow, and renders `; bold` rule
-- lines in bold (additively — syntax colors stay). Neovim-only; classic Vim
-- uses the fallbacks in dad.vim and syntax/dad.vim.

if vim.b.did_dad_stripes then
  return
end
vim.b.did_dad_stripes = true

local ns = vim.api.nvim_create_namespace('dad_table_stripes')

-- Derive the stripe background from Normal, shifted slightly, so it stays
-- subtle in any colorscheme without colliding with CursorLine. Both groups
-- are `default`, so user overrides win.
local function define_highlights()
  local normal = vim.api.nvim_get_hl(0, { name = 'Normal', link = false })
  local bg = normal.bg
  local stripe
  if bg then
    local r = math.floor(bg / 65536) % 256
    local g = math.floor(bg / 256) % 256
    local b = bg % 256
    local delta = (r + g + b) / 3 > 127 and -12 or 14
    local function shift(x)
      return math.min(255, math.max(0, x + delta))
    end
    stripe = shift(r) * 65536 + shift(g) * 256 + shift(b)
  else
    stripe = vim.o.background == 'light' and 0xefefef or 0x2b2b2b
  end
  vim.api.nvim_set_hl(0, 'DadTableStripe', { default = true, bg = stripe })
  vim.api.nvim_set_hl(0, 'DadBoldRule', { default = true, bold = true })
end

local function restripe(buf)
  vim.api.nvim_buf_clear_namespace(buf, ns, 0, -1)
  local in_table, row = false, 0
  for i, line in ipairs(vim.api.nvim_buf_get_lines(buf, 0, -1, false)) do
    if line:match('^; Columns:') then
      in_table, row = true, 0
    elseif in_table then
      if line == '' then
        in_table = false
      elseif line:sub(1, 2) ~= ';;' then
        row = row + 1
        if row % 2 == 0 then
          vim.api.nvim_buf_set_extmark(buf, ns, i - 1, 0, {
            line_hl_group = 'DadTableStripe',
            priority = 90,
          })
        end
      end
    end
    if line:gsub(';;.*$', ''):match('; bold%s*$') then
      vim.api.nvim_buf_set_extmark(buf, ns, i - 1, 0, {
        end_col = #line,
        hl_group = 'DadBoldRule',
        priority = 110,
      })
    end
  end
end

define_highlights()

local buf = vim.api.nvim_get_current_buf()
restripe(buf)
vim.api.nvim_create_autocmd({ 'TextChanged', 'TextChangedI' }, {
  buffer = buf,
  callback = function()
    restripe(buf)
  end,
})
if not vim.g.did_dad_stripe_colors then
  vim.g.did_dad_stripe_colors = true
  vim.api.nvim_create_autocmd('ColorScheme', { callback = define_highlights })
end
