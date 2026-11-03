-- Project-local Neovim config, read when `exrc` is on: puts the `.dad`
-- filetype, syntax and table striping from editors/vim on the runtimepath.
local root = vim.fn.fnamemodify(vim.fn.resolve(debug.getinfo(1, "S").source:sub(2)), ":h")
vim.opt.runtimepath:prepend(root .. "/editors/vim")
