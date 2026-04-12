#!/usr/bin/env node
/**
 * SpecKit Audit PDF Generator
 * Converts any markdown audit report into a professionally styled PDF
 * using Puppeteer (Chromium print-to-PDF).
 *
 * Auto-detects report type: full-spectrum, SEO, or individual sub-audit.
 *
 * Usage: node audit-pdf-generator.mjs <input.md> [output.pdf] [brand-color]
 */

import puppeteer from 'puppeteer';
import { readFileSync } from 'fs';

// ---------------------------------------------------------------------------
// Markdown → HTML
// ---------------------------------------------------------------------------
function markdownToHtml(md) {
  let html = md;

  // Escape bare HTML tags in running text
  html = html.replace(/<(?!\/?(?:strong|em|code|pre|table|thead|tbody|tr|th|td|ul|ol|li|h[1-6]|p|hr|div|span|br|a)\b)([a-zA-Z][a-zA-Z0-9]*)\s*\/?>/g, '&lt;$1&gt;');

  // Escape HTML entities in code blocks
  html = html.replace(/```[\s\S]*?```/g, (match) => {
    return match.replace(/</g, '&lt;').replace(/>/g, '&gt;');
  });

  // Horizontal rules
  html = html.replace(/^---+$/gm, '<hr>');

  // Headers
  html = html.replace(/^###### (.+)$/gm, '<h6>$1</h6>');
  html = html.replace(/^##### (.+)$/gm, '<h5>$1</h5>');
  html = html.replace(/^#### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
  html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');

  // Bold and italic
  html = html.replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');

  // Inline code — escape angle brackets
  html = html.replace(/`([^`]+)`/g, (match, content) => {
    const escaped = content.replace(/</g, '&lt;').replace(/>/g, '&gt;');
    return `<code>${escaped}</code>`;
  });

  // Code blocks
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, '<pre><code>$2</code></pre>');

  // Tables
  html = html.replace(/^(\|.+\|)\n(\|[-| :]+\|)\n((?:\|.+\|\n?)*)/gm, (match, header, sep, body) => {
    const headerCells = header.split('|').filter(c => c.trim()).map(c => `<th>${c.trim()}</th>`).join('');
    const rows = body.trim().split('\n').map(row => {
      const cells = row.split('|').filter(c => c.trim()).map(c => `<td>${c.trim()}</td>`).join('');
      return `<tr>${cells}</tr>`;
    }).join('');
    return `<table><thead><tr>${headerCells}</tr></thead><tbody>${rows}</tbody></table>`;
  });

  // Unordered lists
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*<\/li>\n?)+/g, '<ul>$&</ul>');

  // Numbered lists
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');

  // Paragraphs
  html = html.replace(/^(?!<[a-z]|<\/|$)(.+)$/gm, '<p>$1</p>');

  // Clean up empty paragraphs
  html = html.replace(/<p>\s*<\/p>/g, '');

  return html;
}

// ---------------------------------------------------------------------------
// Score color helpers
// ---------------------------------------------------------------------------
function scoreColorClass(score) {
  const n = parseInt(score, 10);
  if (isNaN(n)) return 'orange';
  if (n < 50) return 'red';
  if (n <= 70) return 'orange';
  if (n <= 90) return 'yellow';
  return 'green';
}

// ---------------------------------------------------------------------------
// CSS Theme
// ---------------------------------------------------------------------------
function buildCSS(brandColor) {
  return `
  @page {
    size: A4;
    margin: 20mm 18mm 25mm 18mm;
  }

  * { box-sizing: border-box; }

  body {
    font-family: 'Inter', 'Segoe UI', -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
    font-size: 11px;
    line-height: 1.6;
    color: #1a1a2e;
    margin: 0;
    padding: 0;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
  }

  /* Cover page */
  .cover {
    page-break-after: always;
    display: flex;
    flex-direction: column;
    justify-content: center;
    align-items: center;
    min-height: 85vh;
    text-align: center;
    padding: 40px;
  }
  .cover .logo {
    font-size: 14px;
    letter-spacing: 4px;
    text-transform: uppercase;
    color: ${brandColor};
    font-weight: 700;
    margin-bottom: 60px;
  }
  .cover h1 {
    font-size: 32px;
    font-weight: 800;
    color: #1a1a2e;
    margin: 0 0 12px 0;
    line-height: 1.2;
    border-bottom: 3px solid ${brandColor};
    display: inline-block;
    padding-bottom: 8px;
  }
  .cover .meta-info {
    font-size: 12px;
    color: #888;
    line-height: 2;
    margin-top: 30px;
  }
  .cover .meta-info strong { color: #555; }

  /* Domain/overall score with colored indicator */
  .domain-score-section {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 20px 0 10px 0;
    padding-bottom: 6px;
    border-bottom: 3px solid ${brandColor};
  }
  .domain-score-section h1 {
    border-bottom: none;
    margin: 0;
    padding-bottom: 0;
  }
  .score-dot {
    display: inline-block;
    width: 20px;
    height: 20px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .score-dot.red { background: #e74c3c; }
  .score-dot.orange { background: #f39c12; }
  .score-dot.yellow { background: #f1c40f; }
  .score-dot.green { background: #27ae60; }

  /* Metadata block */
  .report-meta {
    margin: 0 0 16px 0;
    line-height: 1.9;
  }
  .report-meta .meta-line {
    display: block;
  }

  /* Section headers */
  h1 {
    font-size: 22px;
    font-weight: 800;
    color: #1a1a2e;
    margin: 30px 0 10px 0;
    padding-bottom: 6px;
    border-bottom: 3px solid ${brandColor};
    page-break-after: avoid;
  }
  h2 {
    font-size: 17px;
    font-weight: 700;
    color: #2d2d5e;
    margin: 24px 0 8px 0;
    padding-bottom: 4px;
    border-bottom: 1.5px solid #e0e0e0;
    page-break-after: avoid;
  }
  h3 {
    font-size: 14px;
    font-weight: 700;
    color: #3d3d7e;
    margin: 18px 0 6px 0;
    page-break-after: avoid;
  }
  h4 {
    font-size: 12px;
    font-weight: 700;
    color: #4a4a8a;
    margin: 14px 0 4px 0;
    page-break-after: avoid;
  }

  p {
    margin: 4px 0 8px 0;
    orphans: 3;
    widows: 3;
  }

  /* Tables */
  table {
    width: 100%;
    border-collapse: collapse;
    margin: 10px 0 16px 0;
    font-size: 10px;
    page-break-inside: auto;
  }
  thead { display: table-header-group; }
  tr { page-break-inside: avoid; }
  th {
    background: #2d2d5e;
    color: white;
    font-weight: 600;
    text-align: left;
    padding: 7px 10px;
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    white-space: nowrap;
  }
  td {
    padding: 6px 10px;
    border-bottom: 1px solid #e8e8e8;
    vertical-align: top;
    word-break: break-word;
    overflow-wrap: break-word;
  }
  tr:nth-child(even) td { background: #f8f9fc; }

  /* Lists */
  ul, ol { margin: 4px 0 10px 0; padding-left: 20px; }
  li { margin: 2px 0; }

  /* Code */
  code {
    background: #f0f0f5;
    padding: 1px 5px;
    border-radius: 3px;
    font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
    font-size: 9.5px;
    color: #d63384;
  }
  pre {
    background: #1e1e2e;
    color: #cdd6f4;
    padding: 12px 16px;
    border-radius: 6px;
    overflow-x: auto;
    font-size: 9px;
    line-height: 1.5;
    margin: 8px 0 14px 0;
  }
  pre code { background: none; color: inherit; padding: 0; }

  hr {
    border: none;
    border-top: 1.5px solid #e0e0e0;
    margin: 20px 0;
  }

  strong { font-weight: 700; }
  td:first-child { font-weight: 600; }

  h1, h2, h3 { page-break-after: avoid; }
  table, pre, ul, ol { page-break-inside: auto; }

  .report-footer {
    margin-top: 40px;
    padding-top: 12px;
    border-top: 1px solid #ddd;
    font-size: 9px;
    color: #999;
    text-align: center;
  }
`;
}

// ---------------------------------------------------------------------------
// Report type detection and metadata extraction
// ---------------------------------------------------------------------------
function extractReportMeta(md) {
  const meta = {};

  // Detect report type from H1
  const h1Match = md.match(/^# (.+)$/m);
  const h1 = h1Match ? h1Match[1] : '';

  if (h1.includes('Action Plan')) {
    meta.type = 'action-plan';
    meta.coverTitle = 'ACTION PLAN';
    const subjectMatch = h1.match(/:\s*(.+)/);
    meta.subject = subjectMatch ? subjectMatch[1].trim() : 'Unknown Project';
  } else if (h1.includes('SEO Audit')) {
    meta.type = 'seo';
    meta.coverTitle = 'SEO AUDIT';
    const domainMatch = h1.match(/:\s*(.+)/);
    meta.subject = domainMatch ? domainMatch[1].trim() : 'Unknown Domain';
  } else if (h1.includes('Full-Spectrum')) {
    meta.type = 'full-spectrum';
    meta.coverTitle = 'FULL-SPECTRUM AUDIT';
    const subjectMatch = h1.match(/:\s*(.+)/);
    meta.subject = subjectMatch ? subjectMatch[1].trim() : 'Unknown Project';
  } else {
    meta.type = 'audit';
    meta.coverTitle = 'AUDIT REPORT';
    const subjectMatch = h1.match(/:\s*(.+)/);
    meta.subject = subjectMatch ? subjectMatch[1].trim() : h1;
  }

  // Extract metadata fields
  meta.date = (md.match(/\*\*Date\*\*:\s*(.+)/) || [])[1] || new Date().toISOString().split('T')[0];
  meta.platform = (md.match(/\*\*Platform\*\*:\s*(.+)/) || [])[1] || null;
  meta.pagesAudited = (md.match(/\*\*Pages Audited\*\*:\s*(\d+)/) || [])[1] || null;
  meta.themesAudited = (md.match(/\*\*Themes Audited\*\*:\s*(.+)/) || [])[1] || null;

  // Extract overall score — try multiple patterns
  const overallMatch = md.match(/\*\*Overall\*\*.*?(\d+)\/100/) || md.match(/Domain Score:\s*(\d+)\/100/);
  meta.score = overallMatch ? overallMatch[1] : null;

  // Action plan specific
  meta.totalItems = (md.match(/\*\*Total Items\*\*:\s*(.+)/) || [])[1] || null;
  meta.basedOn = (md.match(/\*\*Based on\*\*:\s*(.+)/) || [])[1] || null;

  return meta;
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
const inputPath = process.argv[2];
if (!inputPath) {
  console.error('Usage: node audit-pdf-generator.mjs <input.md> [output.pdf] [brand-color]');
  process.exit(1);
}

const outputPath = process.argv[3] || inputPath.replace(/\.md$/, '.pdf');
const BRAND_COLOR = process.argv[4] || '#3f4cf3';
const md = readFileSync(inputPath, 'utf-8');
const meta = extractReportMeta(md);
const CSS = buildCSS(BRAND_COLOR);

// Build cover page
const coverLines = [`<strong>Date:</strong> ${meta.date}`];
if (meta.platform) coverLines.push(`<strong>Platform:</strong> ${meta.platform}`);
if (meta.pagesAudited) coverLines.push(`<strong>Pages Audited:</strong> ${meta.pagesAudited}`);
if (meta.themesAudited) coverLines.push(`<strong>Themes Audited:</strong> ${meta.themesAudited}`);
if (meta.totalItems) coverLines.push(`<strong>Total Items:</strong> ${meta.totalItems}`);
if (meta.basedOn) coverLines.push(`<strong>Based on:</strong> ${meta.basedOn}`);
coverLines.push(`<strong>Generated by:</strong> ATTCK`);

const coverHtml = `
<div class="cover">
  <div class="logo">${meta.coverTitle}</div>
  <h1>${meta.subject}</h1>
  <div class="meta-info">
    ${coverLines.join('<br>')}
  </div>
</div>
`;

// Pre-process markdown: strip H1 (goes on cover) and structure metadata
let mdBody = md.replace(/^# .+$/m, '');

// Convert consecutive **Key**: value lines into structured HTML block
mdBody = mdBody.replace(
  /(\*\*Date\*\*:.+\n)(\*\*\w[\w\s/]*\*\*:.+\n)+/,
  (match) => {
    const lines = match.trim().split('\n').map(line => {
      const htmlLine = line.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
      return `<span class="meta-line">${htmlLine}</span>`;
    }).join('\n');
    const fixed = lines
      .replace(/Claude Code\s*\([^)]*\)/g, 'ATTCK')
      .replace(/Claude Code/g, 'ATTCK');
    return `<div class="report-meta">\n${fixed}\n</div>\n`;
  }
);

let bodyHtml = markdownToHtml(mdBody);

// Add score dot to score headings
if (meta.score) {
  const colorClass = scoreColorClass(meta.score);
  // Match H2 format for Domain Score or any "Score: XX/100" heading
  bodyHtml = bodyHtml.replace(
    /<h2>((?:Domain |Overall )?Score:?\s*\d+\/100)<\/h2>/i,
    `<div class="domain-score-section"><h1>$1</h1><span class="score-dot ${colorClass}"></span></div>`
  );
}

// Replace generator attribution
bodyHtml = bodyHtml.replace(
  /Generated by Claude Code[^<]*/gi,
  'Generated by ATTCK'
);

const footerLabel = `${meta.coverTitle} — ${meta.subject}`;

const fullHtml = `<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>${footerLabel}</title>
  <style>${CSS}</style>
</head>
<body>
  ${coverHtml}
  ${bodyHtml}
  <div class="report-footer">
    This report was generated by ATTCK using automated analysis tools.
    Confidential — prepared for client use.
  </div>
</body>
</html>`;

// Launch Puppeteer and generate PDF
const browser = await puppeteer.launch({
  headless: true,
  args: ['--no-sandbox', '--disable-setuid-sandbox']
});
const page = await browser.newPage();
await page.setContent(fullHtml, { waitUntil: 'networkidle0' });

await page.pdf({
  path: outputPath,
  format: 'A4',
  printBackground: true,
  displayHeaderFooter: true,
  headerTemplate: '<span></span>',
  footerTemplate: `
    <div style="width: 100%; font-size: 8px; padding: 0 20mm; display: flex; justify-content: space-between; color: #999; font-family: system-ui, sans-serif;">
      <span>${footerLabel}</span>
      <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
    </div>
  `,
  margin: {
    top: '20mm',
    bottom: '22mm',
    left: '18mm',
    right: '18mm'
  }
});

await browser.close();
console.log(`PDF generated: ${outputPath}`);
