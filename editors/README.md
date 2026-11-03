# Editor support for `.dad` files

Syntax highlighting for the format in [docs/grammar.md](../docs/grammar.md),
plus zebra striping of table rows (every second row after a `; Columns:`
directive gets a faint background).

Table cells are highlighted token by token (data types, `MUST`/`MUST-NOT`,
spec-refs, flag cells, numbers, `-` empty cells) rather than by column:
which vocabulary a cell uses depends on the `; Columns:` declaration,
which regex-based highlighters cannot track. In practice the vocabularies
barely collide.

The TextMate grammar's source is `src/seanchai/dad/syntax/dad.tmLanguage.json`,
package data that `seanchai export` copies out for the site.
`editors/vscode/syntaxes/dad.tmLanguage.json` is a byte-identical copy: edit the
source, copy it over, and `tests/test_export.py` holds the two together.

## VS Code

VS Code only loads grammars from installed extensions, so symlink the
extension in once:

```sh
ln -s "$(pwd)/editors/vscode" ~/.vscode/extensions/seanchai.dad-syntax
```

After that the repo copy is the live extension; reload the window to pick
up grammar changes.

## Neovim

`.nvim.lua` at the repo root adds `editors/vim/` to the runtimepath, so with
`exrc` enabled (`vim.o.exrc = true`; off by default) opening Neovim from the
repo root is enough; you will be prompted once to trust the file.

Without `exrc`, add the directory yourself:

```lua
vim.opt.runtimepath:prepend("/path/to/seanchai/editors/vim")
```

Striping uses the `DadTableStripe` highlight group (defaults to
`CursorLine`); override it with `vim.api.nvim_set_hl`.

## Vim

Vim's own `exrc` is the legacy insecure kind, so add one line to your vimrc
instead, or point your plugin manager at the directory:

```vim
set runtimepath+=/path/to/seanchai/editors/vim
```

Striping uses `matchaddpos()` with the same `DadTableStripe` group.
