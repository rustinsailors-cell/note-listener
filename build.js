// Builds the single-file page from page.src.html + pitchcore.js.
// Usage: node build.js   -> writes note-listener.html and docs/index.html
const fs = require('fs');
const path = require('path');
const dir = __dirname;
const src = fs.readFileSync(path.join(dir, 'page.src.html'), 'utf8');
const core = fs.readFileSync(path.join(dir, 'pitchcore.js'), 'utf8');
if (!src.includes('/*__PITCHCORE__*/')) throw new Error('page.src.html is missing the /*__PITCHCORE__*/ marker');
const head = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}[hidden]{display:none!important}img{max-width:100%}</style>
</head>
<body>
`;
const html = head + src.replace('/*__PITCHCORE__*/', () => core.trimEnd()) + '\n</body>\n</html>\n';
fs.writeFileSync(path.join(dir, 'note-listener.html'), html);
fs.mkdirSync(path.join(dir, 'docs'), { recursive: true });
fs.writeFileSync(path.join(dir, 'docs', 'index.html'), html);
console.log('Built note-listener.html and docs/index.html (' + html.length + ' bytes)');
