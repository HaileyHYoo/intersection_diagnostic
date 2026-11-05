const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, BorderStyle, LevelFormat, TableOfContents, ImageRun, PageBreak, Footer, Header, PageNumber,
  Tab, TabStopType, LeaderType,
} = require("docx");

const NAVY = "1F3864", GREY = "595959", FONT = "Calibri", MONO = "Courier New";
const PAGE_W = 11906, MARGIN = 1134, TEXT_W = PAGE_W - 2 * MARGIN;   // A4, 2 cm margins

// inline markup: **bold**, `code`, _italic_
function runs(text, opts = {}) {
  const out = [];
  const re = /(\*\*[^*]+\*\*|`[^`]+`|_[^_]+_)/g;
  let last = 0, m;
  while ((m = re.exec(text))) {
    if (m.index > last) out.push(new TextRun({ text: text.slice(last, m.index), ...opts }));
    const t = m[0];
    if (t.startsWith("**")) out.push(new TextRun({ text: t.slice(2, -2), bold: true, ...opts }));
    else if (t.startsWith("`")) out.push(new TextRun({ text: t.slice(1, -1), font: MONO, size: (opts.size || 20) - 2, ...opts, ...{ font: MONO } }));
    else out.push(new TextRun({ text: t.slice(1, -1), italics: true, ...opts }));
    last = m.index + t.length;
  }
  if (last < text.length) out.push(new TextRun({ text: text.slice(last), ...opts }));
  return out;
}
const P = (t, o = {}) => new Paragraph({ children: runs(t, o.run), spacing: { after: 120 }, ...o.para });
const H1 = t => new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(t)], pageBreakBefore: true });
const H2 = t => new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(t)] });
const H3 = t => new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(t)] });
const B = (items, level = 0) => items.map(t => new Paragraph({ children: runs(t), numbering: { reference: "bullets", level },
  spacing: { after: 60 } }));
const N = items => items.map(t => new Paragraph({ children: runs(t), numbering: { reference: "numbers", level: 0 }, spacing: { after: 60 } }));
const CAP = t => new Paragraph({ children: runs(t, { italics: true, size: 18, color: GREY }), spacing: { after: 200 } });

const border = { style: BorderStyle.SINGLE, size: 4, color: "BFBFBF" };
const borders = { top: border, bottom: border, left: border, right: border };
function T(headers, rows, fractions) {
  const total = fractions.reduce((a, b) => a + b, 0);
  const widths = fractions.map(f => Math.floor(TEXT_W * f / total));
  widths[widths.length - 1] += TEXT_W - widths.reduce((a, b) => a + b, 0);
  const cell = (text, w, head) => new TableCell({
    width: { size: w, type: WidthType.DXA }, borders,
    shading: head ? { fill: NAVY, type: ShadingType.CLEAR, color: "auto" } : undefined,
    margins: { top: 50, bottom: 50, left: 90, right: 90 },
    children: String(text).split("\n").map(line => new Paragraph({ children: runs(line, head ? { bold: true, color: "FFFFFF", size: 18 } : { size: 18 }) })),
  });
  return new Table({
    width: { size: TEXT_W, type: WidthType.DXA }, columnWidths: widths,
    rows: [new TableRow({ tableHeader: true, children: headers.map((h, i) => cell(h, widths[i], true)) }),
      ...rows.map(r => new TableRow({ cantSplit: true, children: r.map((c, i) => cell(c, widths[i], false)) }))],
  });
}
const SP = () => new Paragraph({ children: [], spacing: { after: 80 } });

const C = JSON.parse(fs.readFileSync(path.join(__dirname, "content.json"), "utf8"));
const body = [];
function add(block) {
  for (const b of block) {
    if (b.h1) body.push(H1(b.h1));
    else if (b.h2) body.push(H2(b.h2));
    else if (b.h3) body.push(H3(b.h3));
    else if (b.p) body.push(P(b.p));
    else if (b.bullets) body.push(...B(b.bullets));
    else if (b.numbers) body.push(...N(b.numbers));
    else if (b.table) { body.push(T(b.table.head, b.table.rows, b.table.widths)); if (b.table.caption) body.push(CAP(b.table.caption)); else body.push(SP()); }
    else if (b.image) {
      body.push(new Paragraph({ alignment: AlignmentType.CENTER, children: [new ImageRun({ type: "png",
        data: fs.readFileSync(path.join(__dirname, b.image)), transformation: { width: b.width, height: b.height },
        altText: { title: b.alt, description: b.alt, name: b.alt } })] }));
      body.push(CAP(b.caption));
    }
  }
}
add(C.body);

const title = [
  new Paragraph({ children: [], spacing: { before: 3000 } }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: C.title, bold: true, size: 48, color: NAVY })], spacing: { after: 200 } }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: C.subtitle, size: 28, color: "2E5496" })], spacing: { after: 160 } }),
  new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: C.tagline, italics: true, size: 20, color: "44546A" })], spacing: { after: 1400 } }),
  ...C.meta.map(t => new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: t, size: 20 })], spacing: { after: 60 } })),
  new Paragraph({ children: [new PageBreak()] }),
  new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun("Table of Contents")] }),
  ...tocEntries(),
];
function tocEntries() {
  const f = path.join(__dirname, "toc.json");
  if (!fs.existsSync(f)) return [new TableOfContents("Table of Contents", { hyperlink: true, headingStyleRange: "1-2" })];
  return JSON.parse(fs.readFileSync(f, "utf8")).map(e => new Paragraph({
    indent: { left: e.level === 1 ? 0 : 360 }, spacing: { after: 40 },
    tabStops: [{ type: TabStopType.RIGHT, position: TEXT_W, leader: LeaderType.DOT }],
    children: [new TextRun({ text: e.text, size: 19, bold: e.level === 1 }),
      new TextRun({ children: [new Tab(), String(e.page)], size: 19 })] }));
}

const doc = new Document({
  creator: "Intersections Diagnostics V1", title: C.title, description: C.subtitle,
  features: { updateFields: true },
  styles: {
    default: { document: { run: { font: FONT, size: 20 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 30, bold: true, color: NAVY }, paragraph: { spacing: { before: 240, after: 160 }, keepNext: true, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 24, bold: true, color: "2E5496" }, paragraph: { spacing: { before: 220, after: 100 }, keepNext: true, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { font: FONT, size: 21, bold: true, color: NAVY }, paragraph: { spacing: { before: 160, after: 80 }, keepNext: true, outlineLevel: 2 } },
    ],
  },
  numbering: { config: [
    { reference: "bullets", levels: [{ level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 270 } } } }, { level: 1, format: LevelFormat.BULLET, text: "–", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 1080, hanging: 270 } } } }] },
    { reference: "numbers", levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
      style: { paragraph: { indent: { left: 540, hanging: 300 } } } }] },
  ] },
  sections: [
    { properties: { page: { size: { width: PAGE_W, height: 16838 }, margin: { top: MARGIN, bottom: MARGIN, left: MARGIN, right: MARGIN } }, titlePage: true },
      headers: { default: new Header({ children: [new Paragraph({ alignment: AlignmentType.RIGHT,
        children: [new TextRun({ text: `${C.title} – ${C.subtitle}`, size: 16, color: GREY })] })] }) },
      footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER,
        children: [new TextRun({ children: ["Page ", PageNumber.CURRENT, " of ", PageNumber.TOTAL_PAGES], size: 16, color: GREY })] })] }) },
      children: [...title, ...body] },
  ],
});
Packer.toBuffer(doc).then(buf => { fs.writeFileSync(process.argv[2], buf); console.log("written", process.argv[2]); });
