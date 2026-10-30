// Build the Word version of PROJECT_REPORT.md.
// Handles the Markdown subset the report actually uses: headings, paragraphs,
// pipe tables, bullet and numbered lists, fenced code, inline bold and code.

const fs = require("fs");
const path = require("path");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  TableOfContents, PageBreak, PageOrientation, LevelFormat, convertInchesToTwip,
} = require("docx");

const SRC = process.argv[2];
const OUT = process.argv[3];

const NAVY = "000048";      // CF midnight blue
const TEAL = "05819B";      // CF dark teal
const GREY = "53565A";
const HEADER_BG = "D2E8ED"; // the pale teal used on the maps

// A4 portrait with 1 inch margins, in DXA (1440 = 1 inch).
const PAGE = {
  size: { width: 11906, height: 16838, orientation: PageOrientation.PORTRAIT },
  margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
};
const CONTENT_WIDTH = 11906 - 1440 - 1440;

const lines = fs.readFileSync(SRC, "utf8").split(/\r?\n/);

// ---- inline formatting -----------------------------------------------------

function runs(text, base = {}) {
  // Splits on **bold** and `code`, keeping the delimiters' content.
  const out = [];
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
  let last = 0;
  let match;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > last) {
      out.push(new TextRun({ text: text.slice(last, match.index), ...base }));
    }
    const token = match[0];
    if (token.startsWith("**")) {
      out.push(new TextRun({ text: token.slice(2, -2), bold: true, ...base }));
    } else {
      out.push(new TextRun({
        text: token.slice(1, -1), font: "Consolas", size: 19,
        color: TEAL, ...base,
      }));
    }
    last = pattern.lastIndex;
  }
  if (last < text.length) {
    out.push(new TextRun({ text: text.slice(last), ...base }));
  }
  return out.length ? out : [new TextRun({ text: "", ...base })];
}

// ---- tables ----------------------------------------------------------------

function splitRow(line) {
  return line.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

function buildTable(rows) {
  const header = splitRow(rows[0]);
  const body = rows.slice(2).map(splitRow);           // row 1 is the ---|--- rule
  const columns = header.length;

  // Dual widths, both DXA, summing to the table width: percentages break in
  // Google Docs and unequal sums shift the right edge.
  const colWidth = Math.floor(CONTENT_WIDTH / columns);
  const columnWidths = Array(columns).fill(colWidth);
  columnWidths[columns - 1] = CONTENT_WIDTH - colWidth * (columns - 1);

  const cell = (text, isHeader, index) => new TableCell({
    width: { size: columnWidths[index], type: WidthType.DXA },
    shading: isHeader
      ? { type: ShadingType.CLEAR, fill: HEADER_BG, color: "auto" }
      : undefined,
    margins: { top: 60, bottom: 60, left: 110, right: 110 },
    children: [new Paragraph({
      spacing: { before: 0, after: 0 },
      children: runs(text || "", { size: 19, bold: isHeader || undefined,
        color: isHeader ? NAVY : undefined }),
    })],
  });

  const makeRow = (cells, isHeader) => new TableRow({
    tableHeader: isHeader || undefined,
    children: Array.from({ length: columns }, (_, i) =>
      cell(cells[i] ?? "", isHeader, i)),
  });

  // A key/value table is written with an empty header row in Markdown. Drawing
  // it would put a blank tinted band across the top, so it is dropped.
  const named = header.some((h) => h !== "");

  return new Table({
    columnWidths,
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 2, color: "C9C9C6" },
      bottom: { style: BorderStyle.SINGLE, size: 2, color: "C9C9C6" },
      left: { style: BorderStyle.SINGLE, size: 2, color: "C9C9C6" },
      right: { style: BorderStyle.SINGLE, size: 2, color: "C9C9C6" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 2, color: "DCDCDA" },
      insideVertical: { style: BorderStyle.SINGLE, size: 2, color: "DCDCDA" },
    },
    rows: named
      ? [makeRow(header, true), ...body.map((r) => makeRow(r, false))]
      : body.map((r) => makeRow(r, false)),
  });
}

// ---- walk the document -----------------------------------------------------

const children = [];
let i = 0;

// Numbered lists share one definition, so each list needs its own instance or
// the second one carries on counting from where the first stopped.
let listInstance = 0;
let inNumberedList = false;

// Skip the Markdown H1 and its lead-in; the title page below replaces them.
while (i < lines.length && !/^## /.test(lines[i])) i++;

while (i < lines.length) {
  const line = lines[i];

  if (/^\s*$/.test(line)) { i++; continue; }

  if (/^---+\s*$/.test(line)) { i++; continue; }        // section rules

  // Anything that is not a numbered item ends the current numbered list. This
  // has to run before the heading branches, which return early.
  if (!/^\d+\.\s/.test(line)) inNumberedList = false;

  if (/^## /.test(line)) {
    children.push(new Paragraph({
      heading: HeadingLevel.HEADING_1,
      spacing: { before: 360, after: 140 },
      children: runs(line.slice(3), { color: NAVY, bold: true, size: 30 }),
    }));
    i++; continue;
  }

  if (/^### /.test(line)) {
    children.push(new Paragraph({
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 260, after: 100 },
      children: runs(line.slice(4), { color: TEAL, bold: true, size: 24 }),
    }));
    i++; continue;
  }

  if (/^```/.test(line)) {
    i++;
    const code = [];
    while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
    i++;
    code.forEach((row) => children.push(new Paragraph({
      spacing: { before: 0, after: 0 },
      shading: { type: ShadingType.CLEAR, fill: "F4F4F2", color: "auto" },
      children: [new TextRun({ text: row || " ", font: "Consolas", size: 17 })],
    })));
    children.push(new Paragraph({ spacing: { after: 120 }, children: [] }));
    continue;
  }

  if (/^\|/.test(line)) {
    const rows = [];
    while (i < lines.length && /^\|/.test(lines[i])) rows.push(lines[i++]);
    if (rows.length >= 2) {
      children.push(buildTable(rows));
      children.push(new Paragraph({ spacing: { after: 180 }, children: [] }));
    }
    continue;
  }

  if (/^\d+\.\s/.test(line)) {
    if (!inNumberedList) { listInstance += 1; inNumberedList = true; }
    let text = line.replace(/^\d+\.\s/, "");
    while (i + 1 < lines.length && /^\s{3,}\S/.test(lines[i + 1])) {
      text += " " + lines[++i].trim();
    }
    children.push(new Paragraph({
      numbering: { reference: "report-numbers", level: 0, instance: listInstance },
      spacing: { after: 80 },
      children: runs(text),
    }));
    i++; continue;
  }

  if (/^[-*]\s/.test(line)) {
    let text = line.replace(/^[-*]\s/, "");
    while (i + 1 < lines.length && /^\s{2,}\S/.test(lines[i + 1])) {
      text += " " + lines[++i].trim();
    }
    children.push(new Paragraph({
      numbering: { reference: "report-bullets", level: 0 },
      spacing: { after: 80 },
      children: runs(text),
    }));
    i++; continue;
  }

  // Paragraph: gather until a blank line or a block starter.
  const parts = [];
  while (i < lines.length && !/^\s*$/.test(lines[i]) &&
         !/^(#{2,3} |\||```|---+\s*$|[-*]\s|\d+\.\s)/.test(lines[i])) {
    parts.push(lines[i++].trim());
  }
  if (parts.length) {
    children.push(new Paragraph({
      spacing: { after: 140, line: 276 },
      alignment: AlignmentType.JUSTIFIED,
      children: runs(parts.join(" ")),
    }));
  }
}

// ---- title page and contents ----------------------------------------------

const spacer = (after) => new Paragraph({ spacing: { after }, children: [] });

const front = [
  spacer(2600),
  new Paragraph({
    spacing: { after: 160 },
    children: [new TextRun({
      text: "Locator map generator", bold: true, size: 56, color: NAVY,
    })],
  }),
  new Paragraph({
    spacing: { after: 420 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 10, color: NAVY, space: 10 } },
    children: [new TextRun({ text: "Project report", size: 32, color: TEAL })],
  }),
  new Paragraph({
    spacing: { after: 100 },
    children: [new TextRun({
      text: "A geographic mapping automation for Cognizant Foundation India",
      size: 22, color: GREY,
    })],
  }),
  new Paragraph({
    spacing: { after: 100 },
    children: [new TextRun({
      text: "Built 22 September to 27 October 2026", size: 22, color: GREY,
    })],
  }),
  new Paragraph({
    spacing: { after: 100 },
    children: [new TextRun({ text: "Report prepared 30 October 2026", size: 22, color: GREY })],
  }),
  new Paragraph({ children: [new PageBreak()] }),
  // Styled by hand rather than as Heading 1, or the contents list itself
  // appears as its own first entry.
  new Paragraph({
    spacing: { after: 200 },
    children: [new TextRun({ text: "Contents", bold: true, size: 30, color: NAVY })],
  }),
  new TableOfContents("Contents", { hyperlink: true, headingStyleRange: "1-2" }),
  new Paragraph({ children: [new PageBreak()] }),
];

const doc = new Document({
  creator: "Cognizant Foundation India",
  title: "Locator map generator: project report",
  description: "Technical and process record of the locator map automation",
  styles: {
    default: {
      document: { run: { font: "Calibri", size: 21, color: "1A1A1A" } },
    },
  },
  numbering: {
    config: [
      {
        reference: "report-bullets",
        levels: [{
          level: 0, format: LevelFormat.BULLET, text: "•",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: convertInchesToTwip(0.3), hanging: 220 } } },
        }],
      },
      {
        reference: "report-numbers",
        levels: [{
          level: 0, format: LevelFormat.DECIMAL, text: "%1.",
          alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: convertInchesToTwip(0.35), hanging: 260 } } },
        }],
      },
    ],
  },
  sections: [{ properties: { page: PAGE }, children: [...front, ...children] }],
});

Packer.toBuffer(doc).then((buffer) => {
  fs.writeFileSync(OUT, buffer);
  console.log("written:", OUT, (buffer.length / 1024).toFixed(0) + " KB");
  console.log("blocks:", children.length);
});
