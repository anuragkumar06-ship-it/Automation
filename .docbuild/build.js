const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Table, TableRow, TableCell, WidthType, ShadingType, BorderStyle,
  ImageRun, LevelFormat, convertInchesToTwip,
} = require("docx");

// Cognizant brand palette, from the visual identity guidelines (January 2025).
const MIDNIGHT = "000048";
const DARK_GRAY = "53565A";
const MED_GRAY = "97999B";
const LIGHT_GRAY = "D0D0CE";
const TEAL = "05819B";

const FONT = "Arial"; // the brand's everyday font
const CONTENT_W = 9360; // 6.5 inches in DXA

const p = (text, opts = {}) =>
  new Paragraph({
    spacing: { after: opts.after ?? 160, line: 276 },
    alignment: opts.align,
    children: [
      new TextRun({
        text,
        font: FONT,
        size: opts.size ?? 21, // half-points: 21 = 10.5pt
        bold: opts.bold,
        italics: opts.italics,
        color: opts.color ?? MIDNIGHT,
      }),
    ],
  });

// A paragraph whose runs mix bold and plain, e.g. a lead-in phrase.
const rich = (runs, opts = {}) =>
  new Paragraph({
    spacing: { after: opts.after ?? 160, line: 276 },
    children: runs.map(
      (r) =>
        new TextRun({
          text: r.t,
          font: FONT,
          size: 21,
          bold: r.b,
          italics: r.i,
          color: r.c ?? MIDNIGHT,
        })
    ),
  });

const h1 = (text) =>
  new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 360, after: 200 },
    children: [
      new TextRun({ text, font: FONT, size: 30, bold: true, color: MIDNIGHT }),
    ],
  });

const rule = () =>
  new Paragraph({
    spacing: { before: 40, after: 240 },
    border: { bottom: { style: BorderStyle.SINGLE, size: 12, color: MIDNIGHT } },
    children: [new TextRun({ text: "", font: FONT, size: 2 })],
  });

const image = (file, widthIn) => {
  const data = fs.readFileSync(file);
  // Both figures are rendered at 300 dpi; scale to the printed width.
  const dims = { "fig_pipeline.png": [2229, 898], "fig_memory.png": [2144, 1158] };
  const key = file.split("/").pop();
  const [pw, ph] = dims[key];
  const w = widthIn * 96;
  return new Paragraph({
    spacing: { before: 120, after: 240 },
    alignment: AlignmentType.CENTER,
    children: [
      new ImageRun({
        type: "png",
        data,
        transformation: { width: Math.round(w), height: Math.round((w * ph) / pw) },
      }),
    ],
  });
};

const caption = (text) =>
  new Paragraph({
    spacing: { after: 280 },
    alignment: AlignmentType.CENTER,
    children: [
      new TextRun({ text, font: FONT, size: 17, italics: true, color: MED_GRAY }),
    ],
  });

const cell = (text, { header = false, width, bold = false } = {}) =>
  new TableCell({
    width: { size: width, type: WidthType.DXA },
    shading: header
      ? { type: ShadingType.CLEAR, fill: "F2F2F0", color: "auto" }
      : undefined,
    margins: { top: 90, bottom: 90, left: 140, right: 140 },
    children: [
      new Paragraph({
        spacing: { after: 0, line: 252 },
        children: [
          new TextRun({
            text,
            font: FONT,
            size: 19,
            bold: header || bold,
            color: header ? MIDNIGHT : DARK_GRAY,
          }),
        ],
      }),
    ],
  });

const table = (headers, rows, widths) =>
  new Table({
    columnWidths: widths,
    width: { size: CONTENT_W, type: WidthType.DXA },
    borders: {
      top: { style: BorderStyle.SINGLE, size: 4, color: LIGHT_GRAY },
      bottom: { style: BorderStyle.SINGLE, size: 4, color: LIGHT_GRAY },
      left: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      right: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
      insideHorizontal: { style: BorderStyle.SINGLE, size: 4, color: LIGHT_GRAY },
      insideVertical: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
    },
    rows: [
      new TableRow({
        tableHeader: true,
        children: headers.map((t, i) => cell(t, { header: true, width: widths[i] })),
      }),
      ...rows.map(
        (r) =>
          new TableRow({
            children: r.map((t, i) =>
              cell(t, { width: widths[i], bold: i === 0 && headers.length > 2 })
            ),
          })
      ),
    ],
  });

const bullets = (items) =>
  items.map(
    (t) =>
      new Paragraph({
        numbering: { reference: "dash", level: 0 },
        spacing: { after: 110, line: 276 },
        children: [new TextRun({ text: t, font: FONT, size: 21, color: MIDNIGHT })],
      })
  );

const numbered = (items) =>
  items.map((r) =>
    new Paragraph({
      numbering: { reference: "steps", level: 0 },
      spacing: { after: 130, line: 276 },
      children: [
        new TextRun({ text: r.b, font: FONT, size: 21, bold: true, color: MIDNIGHT }),
        new TextRun({ text: r.t, font: FONT, size: 21, color: MIDNIGHT }),
      ],
    })
  );

const doc = new Document({
  creator: "Cognizant Foundation India",
  title: "Locator map generator: how it works",
  description: "Technical overview of the locator map generator",
  numbering: {
    config: [
      {
        reference: "dash",
        levels: [
          {
            level: 0,
            format: LevelFormat.BULLET,
            text: "–",
            alignment: AlignmentType.LEFT,
            style: {
              paragraph: { indent: { left: convertInchesToTwip(0.3), hanging: 220 } },
              run: { font: FONT, color: TEAL },
            },
          },
        ],
      },
      {
        reference: "steps",
        levels: [
          {
            level: 0,
            format: LevelFormat.DECIMAL,
            text: "%1.",
            alignment: AlignmentType.LEFT,
            style: {
              paragraph: { indent: { left: convertInchesToTwip(0.35), hanging: 280 } },
              run: { font: FONT, bold: true, color: TEAL },
            },
          },
        ],
      },
    ],
  },
  sections: [
    {
      properties: {
        page: {
          size: { width: 12240, height: 15840 }, // US Letter
          margin: { top: 1080, right: 1440, bottom: 1080, left: 1440 },
        },
      },
      children: [
        // ---- title block ----------------------------------------------
        new Paragraph({
          spacing: { after: 60 },
          children: [
            new TextRun({
              text: "Locator map generator: how it works",
              font: FONT,
              size: 40,
              bold: true,
              color: MIDNIGHT,
            }),
          ],
        }),
        new Paragraph({
          spacing: { after: 100 },
          children: [
            new TextRun({
              text: "Technical overview  ·  26 September 2026",
              font: FONT,
              size: 19,
              color: MED_GRAY,
            }),
          ],
        }),
        rule(),

        p(
          "This tool draws the three-panel location map that goes into a Cognizant Foundation funding proposal. Every boundary on it comes from a published government dataset, and no part of it uses AI. It replaces a manual process that produced maps with invented places on them.",
          { after: 240 }
        ),

        // ---- 1 ---------------------------------------------------------
        h1("What it replaces"),
        p("These maps used to be made with AI image tools. The maps looked right and were not."),
        p(
          "One earlier map of Madurai district showed eight blocks that do not exist anywhere in India: Kallandiri, Othakadai, Ayilangudi, Keela Kallandiri, Sakkimangalam, Vellikundram, Kadakinaru and Mathur. The same map left out four real Tamil Nadu districts, including Tiruppur and Chengalpattu, and misspelled Dindigul."
        ),
        p(
          "Nobody noticed, because an invented place name on a map looks exactly like a real one. That is the problem worth understanding: a map is trusted on sight. A funder reading a proposal has no way to tell a real block from an invented one, and neither does the person who made the map."
        ),
        p(
          "The new tool cannot make that mistake, because it cannot draw anything. It can only copy shapes out of government datasets. If a place is not in the data, no shape exists to copy, and the tool stops and says so rather than filling the gap."
        ),

        // ---- 2 ---------------------------------------------------------
        h1("How a map gets made"),
        image(".docbuild/fig_pipeline.png", 6.5),
        p(
          "The person picks a state, a district and a block from dropdown lists, and adds any sites. The lists are built from the boundary data itself, so a misspelt name is not something anyone can type. The tool then runs five checks. If any of them fails, it stops and explains what is wrong; it never draws a partial or approximate map. If they all pass, it draws the three panels and writes the files."
        ),
        p("One run takes about fifteen seconds."),

        // ---- 3 ---------------------------------------------------------
        h1("Where the boundaries come from"),
        p(
          "Four government datasets, all free to use. Nothing is bought, and no account or password is needed."
        ),
        table(
          ["Layer", "Published by", "What it gives", "Rows"],
          [
            ["States", "Survey of India", "The India outline and all 36 states and union territories", "36"],
            ["Districts", "Local Government Directory", "Every district, with its official government code", "785"],
            ["Blocks", "Local Government Directory", "Every community development block", "7,143"],
            ["Tehsils", "Local Government Directory", "Sub-districts, used only where blocks are not published", "6,471"],
          ],
          [1500, 2400, 4360, 1100]
        ),
        new Paragraph({ spacing: { after: 220 }, children: [] }),
        p(
          "The states layer matters most. India's official map shows Jammu and Kashmir and Ladakh in a particular way, and a general-purpose world map does not. We checked this rather than assuming it: the Ladakh shape in this dataset reaches 37.09 degrees north, which only happens if Gilgit-Baltistan is included, and its area of 168,011 square kilometres matches. That is the official depiction, so it is safe for anything Cognizant Foundation publishes."
        ),
        p(
          "One deliberate departure. Survey of India also publishes a district layer, and we tested it. It has 37 districts for Tamil Nadu and is missing Mayiladuthurai, created in 2020. The Local Government Directory has all 38. Being current mattered more than the source being the same, so districts come from the Directory."
        ),
        p(
          "Every dataset, its download link, its licence and the date it was checked is recorded in a file called SOURCES.md in the project. Every map prints its sources along the bottom edge."
        ),

        // ---- 4 ---------------------------------------------------------
        h1("The checks that run before anything is drawn"),
        p("Five, every single time, with no way to skip them."),
        ...numbered([
          {
            b: "Do the names exist? ",
            t: "The state, district and block are looked up in the government register. Spelling variants are handled by a lookup table, so Thirumangalam and Tirumangalam are understood to be the same place.",
          },
          {
            b: "Is the district count right? ",
            t: "Tamil Nadu should have 38 districts. If the map data shows a different number, the tool says which districts are missing or extra, by name.",
          },
          {
            b: "Is the block count right? ",
            t: "The same check, one level down. Madurai should have 13 blocks.",
          },
          {
            b: "Is each site really where it is said to be? ",
            t: "Every site is tested against the actual district shape, and the tool reports which block it truly falls in.",
          },
          {
            b: "Do the shapes fit together? ",
            t: "The blocks of a district should tile it with no gaps and no overlaps.",
          },
        ]),
        p(
          "A failure is reported in plain English and stops the map. Warnings can be overridden by ticking a box, but only after reading them. Missing data can never be overridden.",
          { after: 160 }
        ),
        rich([
          { t: "Check four already earned its place. " },
          { t: "The Madurai map was set up with the hospital marked in Madurai East block. The check found it actually sits in " },
          { t: "Madurai West", b: true },
          { t: " and said so, which is a fact nobody had noticed and which changes what the proposal should claim." },
        ]),

        // ---- 5 ---------------------------------------------------------
        h1("What it is built from"),
        p(
          "Written in Python, about 3,000 lines across ten files. Each file does one job, which is why a change to the colours cannot break the map-drawing."
        ),
        table(
          ["File", "What it does"],
          [
            ["app.py", "The web page people actually use: the dropdowns, the buttons, the preview"],
            ["locator/data.py", "Finds and opens the boundary files"],
            ["locator/cache.py", "Splits the national data into one file per state, so the app stays small"],
            ["locator/validate.py", "The five checks"],
            ["locator/render.py", "Draws the three panels"],
            ["locator/style.py", "Reads the Cognizant colours and fonts"],
            ["locator/theme.py", "The Cognizant styling for the web page"],
            ["locator/names.py", "Handles spelling variants between government registers"],
            ["locator/geocode.py", "Looks a place name up and returns real coordinates"],
            ["locator/cli.py", "Lets it run from a command line as well as the web page"],
          ],
          [2600, 6760]
        ),
        new Paragraph({ spacing: { after: 220 }, children: [] }),
        p("All nine libraries it uses are free and open source. None needs a paid key."),
        table(
          ["Library", "What it is for"],
          [
            ["GeoPandas", "Handling map shapes as data"],
            ["Shapely", "Geometry: is this point inside that shape?"],
            ["PyProj", "Projections, so India is not the wrong shape on a flat page"],
            ["PyArrow", "Reading the compressed boundary files"],
            ["Matplotlib", "Drawing the actual picture"],
            ["adjustText", "Moving labels apart so they do not overlap"],
            ["Pandas", "Tables of names and codes"],
            ["PyYAML", "Reading the settings files"],
            ["Streamlit", "Turning a Python program into a web page"],
          ],
          [2600, 6760]
        ),
        new Paragraph({ spacing: { after: 220 }, children: [] }),
        p(
          "There are 48 automated tests. Six of them try to add each of the eight blocks the old AI map invented, and check the tool refuses every one."
        ),

        // ---- 6 ---------------------------------------------------------
        h1("What changed while building it"),
        p(
          "Four problems were found by measuring rather than by guessing. Each one would have been invisible until it caused trouble in front of someone."
        ),
        image(".docbuild/fig_memory.png", 5.9),
        p(
          "The tool originally loaded the boundary data for all of India to draw one district. That needed 1,072 MB, and a free hosted web app is allowed 1,024 MB. It would have been shut down on the first day. Splitting the data into one file per state brought it to 370 MB."
        ),
        table(
          ["What was wrong", "Before", "After"],
          [
            ["Time to draw one map", "80 seconds", "14 seconds"],
            ["Same inputs give the same map", "No", "Yes"],
            ["Districts that produce a map", "768 of 785", "785 of 785"],
          ],
          [4560, 2400, 2400]
        ),
        new Paragraph({ spacing: { after: 220 }, children: [] }),
        p(
          "The second row was the subtle one. Two runs with identical settings produced slightly different images, because the label-placement library stops after one second of work rather than after a fixed number of attempts. On a busy computer it got less done. Fixing it to a set number of attempts made the output identical every time, which is what the brief required and what nobody would have thought to test."
        ),

        // ---- 7 ---------------------------------------------------------
        h1("How the team uses it, and how it is published"),
        p(
          "It is a web page. Someone opens a link, picks from three dropdown lists, adds their sites and presses one button. Nothing is installed and no code is edited."
        ),
        p(
          "The page carries Cognizant Foundation's own colours, typeface and logo, taken from the brand guidelines rather than approximated: midnight blue for text, light grey for the areas that are not the subject, teal for the one that is. The maps match, and the logo sits in a corner as the communication guidelines require."
        ),
        p(
          "Typing coordinates by hand is the fiddly part, so there is a search box: type a hospital's name and it looks the place up and shows you the address it found, for you to confirm. That lookup is a search of OpenStreetMap's database, not an AI. The difference matters. An AI returns a plausible answer rather than a looked-up one, and a hospital placed 1.5 kilometres from where it really is still falls inside the right district and the right block, so every check passes and the map is quietly wrong. A database either knows the place or returns nothing."
        ),
        p("Three ways to run it, from the same code:"),
        table(
          ["Where", "Who it suits", "What it needs"],
          [
            ["A laptop", "One person making maps often", "A one-time setup, then one command"],
            ["A hosted web page", "The whole team", "A free hosting account and a code repository"],
            ["Google Colab", "Anyone, occasionally", "Nothing but a browser"],
          ],
          [2200, 3280, 3880]
        ),
        new Paragraph({ spacing: { after: 220 }, children: [] }),
        p(
          "The hosted route is the one being set up now. It is free, and it redeploys itself whenever the code changes."
        ),

        // ---- 8: the plain-English summary -----------------------------
        h1("In short"),
        rich([
          { t: "The background. ", b: true },
          { t: "Every funding proposal needs a map showing where the work will happen. Those maps used to be made by asking an AI image tool to draw one. The maps looked convincing, but some of the places on them were not real. One map of Madurai showed eight blocks that do not exist, and left out four districts that do. Nobody spotted it, because a made-up place name on a map looks exactly like a real one." },
        ]),
        rich([
          { t: "What was built. ", b: true },
          { t: "A tool that cannot invent anything, because it cannot draw. It copies shapes out of government map files and arranges them on a page. If a place is not in those files, there is no shape to copy, so the tool stops and says so instead of filling the gap." },
        ]),
        rich([
          { t: "What it is made of. ", b: true },
          { t: "It is a program written in Python, the language most commonly used for this kind of work. It is about 3,000 lines long, split into ten small files so each one does a single job. It uses nine ready-made free tools that other people maintain, for things like handling map shapes, working out whether a point sits inside an area, and drawing the picture. Nothing was bought, and nothing needs a password or a subscription." },
        ]),
        rich([
          { t: "Where the information comes from. ", b: true },
          { t: "Four map files published by the Government of India: the Survey of India for the country outline and the states, and the Local Government Directory for districts, blocks and sub-districts. These cover all 36 states and union territories, all 785 districts and all 7,143 blocks." },
        ]),
        rich([
          { t: "How it is used. ", b: true },
          { t: "It is a web page. You pick a state, a district and a block from lists, type in your sites or search for them by name, and press a button. About fifteen seconds later you have the map in four file formats, ready to drop into a proposal." },
        ]),
        rich([
          { t: "The one idea worth repeating. ", b: true },
          { t: "The tool checks its own work five times before it draws anything, and refuses to produce a map it cannot stand behind. That is the whole point of it. An attractive map that is wrong is worse than no map, because everyone believes it." },
        ]),
      ],
    },
  ],
});

Packer.toBuffer(doc).then((buf) => {
  fs.writeFileSync("Locator map generator - how it works.docx", buf);
  console.log("written:", buf.length, "bytes");
});
