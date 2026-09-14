" Filetype plugin for .dad files.
" Zebra-stripes table rows (the lines after a `; Columns:` directive) so wide
" rows are easier to follow. Neovim gets the extmark version in dad.lua.

if exists('b:did_dad_ftplugin')
  finish
endif
let b:did_dad_ftplugin = 1

setlocal comments=:;;
setlocal commentstring=;;\ %s

if has('nvim')
  finish
endif

" A subtle background of its own, so stripes stay distinguishable from the
" cursor line. Override DadTableStripe to taste.
if &background ==# 'light'
  highlight default DadTableStripe ctermbg=255 guibg=#efefef
else
  highlight default DadTableStripe ctermbg=236 guibg=#2b2b2b
endif

function! s:Restripe() abort
  for id in get(w:, 'dad_stripe_ids', [])
    silent! call matchdelete(id)
  endfor
  let w:dad_stripe_ids = []

  let stripes = []
  let in_table = 0
  let row = 0
  for lnum in range(1, line('$'))
    let text = getline(lnum)
    if text =~# '^; Columns:'
      let in_table = 1
      let row = 0
    elseif in_table
      if text ==# ''
        let in_table = 0
      elseif text[0:1] !=# ';;'
        let row += 1
        if row % 2 == 0
          call add(stripes, lnum)
        endif
      endif
    endif
  endfor

  " matchaddpos() takes at most 8 positions per call
  for i in range(0, len(stripes) - 1, 8)
    call add(w:dad_stripe_ids, matchaddpos('DadTableStripe', stripes[i : i + 7], -5))
  endfor
endfunction

call s:Restripe()
augroup DadTableStripes
  autocmd! * <buffer>
  autocmd TextChanged,InsertLeave,BufWinEnter <buffer> call s:Restripe()
augroup END
