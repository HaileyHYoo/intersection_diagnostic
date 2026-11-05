# Technical report (docx)

Sources of `docs/Intersections_Diagnostics_V1_Technical_Design_v1.docx`, in the style of the chatbot's
`SCATS_QA_Bot_Technical_Design_v5.docx`.

- `content.py` – the text and tables (edit here)
- `build.js` – the docx layout (npm `docx`)
- `toc.py` – reads the rendered PDF and writes `toc.json`, the static table of contents with page numbers
- `map.html` → `datamap.png` – Figure 1 (rendered with Playwright)

Build (two passes, so the table of contents has the right page numbers):

```bash
cd tools/technical_report
python3 content.py content.json
rm -f toc.json
for i in 1 2; do node build.js "$PWD/report.docx" && soffice --headless --convert-to pdf report.docx && python3 toc.py content.json report.pdf; done
node build.js "$PWD/report.docx"
cp report.docx ../../docs/Intersections_Diagnostics_V1_Technical_Design_v1.docx
```
