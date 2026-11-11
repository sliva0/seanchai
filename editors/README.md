# Editor support for `.dad` files

Syntax highlighting for the format in [docs/grammar.md](../docs/grammar.md).
Table rows are zebra-striped: every second row after a `; Columns:` directive
gets a faint background.

Table cells are highlighted token by token (data types, `MUST`/`MUST-NOT`,
spec-refs, flag cells, numbers, `-` for an empty cell). A regex highlighter
cannot track which column a cell is in, but the vocabularies rarely collide.

The TextMate grammar's source is `src/seanchai/dad/syntax/dad.tmLanguage.json`,
which `seanchai export` copies out for the site.
`editors/vscode/syntaxes/dad.tmLanguage.json` is an identical copy. Edit the
source and copy it over; `tests/test_export.py` checks that the two match.

## VS Code

VS Code loads grammars only from installed extensions, so link the extension
in once:

```sh
ln -s "$(pwd)/editors/vscode" ~/.vscode/extensions/seanchai.dad-syntax
```

Reload the window to pick up grammar changes.

## Neovim

`editors/vim/` is a plugin: `ftdetect/` sets the filetype for `*.dad`, and
`ftplugin/` and `syntax/` do the rest. Load it from a checkout with lazy.nvim:

```lua
{ dir = "/path/to/seanchai/editors/vim", name = "seanchai-dad", lazy = false }
```

or add it to the runtimepath before startup finishes, so `ftdetect/` is read:

```lua
vim.opt.runtimepath:prepend("/path/to/seanchai/editors/vim")
```

With `vim.o.exrc = true`, the repository's `.nvim.lua` does the same when
Neovim starts from the repository root, after you trust the file once.

Striping uses the `DadTableStripe` highlight group, by default a background
slightly off the normal one; override it with `vim.api.nvim_set_hl`.

## Vim

Vim's `exrc` is not safe to enable, so add this line to your vimrc, or point
your plugin manager at the directory:

```vim
set runtimepath+=/path/to/seanchai/editors/vim
```

Striping uses `matchaddpos()` with the same `DadTableStripe` group.
