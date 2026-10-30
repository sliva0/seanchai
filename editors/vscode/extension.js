const vscode = require('vscode');

// Every second row of a table block gets a faint whole-line background so
// long rows are easier to follow. A table block is the run of non-blank
// lines after a `; Columns:` directive; `;;` comment lines inside it do not
// advance the stripe parity.
const stripe = vscode.window.createTextEditorDecorationType({
  isWholeLine: true,
  light: { backgroundColor: 'rgba(0, 0, 0, 0.045)' },
  dark: { backgroundColor: 'rgba(255, 255, 255, 0.045)' },
});

// `; bold` rule lines mirror the source document's bold AVPs; render them bold.
const bold = vscode.window.createTextEditorDecorationType({
  fontWeight: 'bold',
});

// `; strikethrough` rule lines mirror its struck AVPs. Commented-out ones are
// comments and stay as such.
const struck = vscode.window.createTextEditorDecorationType({
  textDecoration: 'line-through',
});

function decorationRanges(doc) {
  const stripes = [];
  const bolds = [];
  const strikes = [];
  let inTable = false;
  let row = 0;
  for (let i = 0; i < doc.lineCount; i++) {
    const text = doc.lineAt(i).text;
    if (/^; Columns:/.test(text)) {
      inTable = true;
      row = 0;
    } else if (inTable) {
      if (text.trim() === '') {
        inTable = false;
      } else if (!text.startsWith(';;')) {
        row += 1;
        if (row % 2 === 0) stripes.push(doc.lineAt(i).range);
      }
    }
    const rule = text.replace(/;;.*$/, '');
    if (/; bold(\s*; strikethrough)?\s*$/.test(rule)) {
      bolds.push(doc.lineAt(i).range);
    }
    if (/; strikethrough\s*$/.test(rule)) {
      strikes.push(doc.lineAt(i).range);
    }
  }
  return { stripes, bolds, strikes };
}

function refresh(editor) {
  if (!editor || editor.document.languageId !== 'dad') return;
  const { stripes, bolds, strikes } = decorationRanges(editor.document);
  editor.setDecorations(stripe, stripes);
  editor.setDecorations(bold, bolds);
  editor.setDecorations(struck, strikes);
}

function activate(context) {
  vscode.window.visibleTextEditors.forEach(refresh);
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(refresh),
    vscode.window.onDidChangeVisibleTextEditors((editors) => editors.forEach(refresh)),
    vscode.workspace.onDidChangeTextDocument((event) => {
      vscode.window.visibleTextEditors
        .filter((editor) => editor.document === event.document)
        .forEach(refresh);
    })
  );
}

module.exports = { activate };
