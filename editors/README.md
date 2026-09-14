# Editor support for `.dad` files

Syntax highlighting for the format described in
[docs/grammar.md](../docs/grammar.md), plus zebra-striping of table rows
(every second row after a `; Columns:` directive gets a faint background).

Table cells are highlighted token-by-token (data types, `MUST`/`MUST-NOT`,
spec-refs, flag cells, numbers, `-` empty cells) rather than column-aware:
which vocabulary a cell uses depends on the `; Columns:` declaration, which
regex-based highlighters cannot track. In practice the vocabularies barely
collide.

The grammar is not stable yet (see the warning in docs/grammar.md); these
definitions follow it and get updated with it, which is why they live in-repo.

## VS Code

VS Code only loads grammars from installed extensions — there is no
per-workspace mechanism — so symlink the extension in once:

```sh
ln -s "$(pwd)/editors/vscode" ~/.vscode/extensions/seanchai.dad-syntax
```

After that the repo copy is the live extension; reload the window to pick up
grammar changes.

## Neovim

`.nvim.lua` at the repo root adds `editors/vim/` to the runtimepath, so if you
have `exrc` enabled (`vim.o.exrc = true`; off by default), opening Neovim from
the repo root is enough — you will be prompted once to trust the file.

Without `exrc`, add the directory yourself:

```lua
vim.opt.runtimepath:prepend("/path/to/seanchai/editors/vim")
```

Striping uses the `DadTableStripe` highlight group (defaults to `CursorLine`);
override it with `vim.api.nvim_set_hl` to taste.

## Vim

Vim's own `exrc` mechanism is the legacy insecure kind, so instead add one
line to your vimrc (or point your plugin manager at the directory):

```vim
set runtimepath+=/path/to/seanchai/editors/vim
```

Striping uses `matchaddpos()` with the same `DadTableStripe` group.
