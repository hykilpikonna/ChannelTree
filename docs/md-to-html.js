// Fisrt run: npx --yes marked -i README.md -o public/readme.html

const fs = require('fs');
let html = fs.readFileSync('public/readme.html', 'utf8');

// replace public/banner.png with banner.png
html = html.replace(/public\/banner\.png/g, 'banner.png');

const finalHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>TGCN 频道树 - README</title>
  <style>
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      line-height: 1.6;
      color: #333;
      max-width: 800px;
      margin: 0 auto;
      padding: 2rem 1rem;
    }
    img { max-width: 100%; height: auto; }
    code { background: #f4f4f4; padding: 2px 5px; border-radius: 4px; }
    pre { background: #f4f4f4; padding: 1rem; border-radius: 8px; overflow-x: auto; }
    a { color: #0366d6; text-decoration: none; }
    a:hover { text-decoration: underline; }
    h1, h2, h3 { border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }
    blockquote { border-left: 0.25em solid #dfe2e5; margin: 0; padding: 0 1em; color: #6a737d; }
  </style>
</head>
<body>
${html}
</body>
</html>`;

fs.writeFileSync('public/readme.html', finalHtml);
console.log('Modified public/readme.html');
