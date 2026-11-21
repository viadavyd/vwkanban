// Point 7 of the spike: entry vs lazy editor chunk sizes (gzip), from dist-spike/.
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const dir = "dist-spike";
const html = readFileSync(`${dir}/spike.html`, "utf8");
const entry = html.match(/src="\/assets\/([^"]+\.js)"/)?.[1];
const files = readdirSync(`${dir}/assets`).filter((f) => f.endsWith(".js"));
const rows = files.map((f) => {
  const buf = readFileSync(`${dir}/assets/${f}`);
  const src = buf.toString("utf8");
  return {
    file: f,
    entry: f === entry,
    // ".cm-content" is a CodeMirror theme selector string that survives minification.
    hasCodeMirror: src.includes("cm-content"),
    bytes: buf.length,
    gzip: gzipSync(buf, { level: 9 }).length,
  };
});
const report = {
  entry: rows.find((r) => r.entry),
  lazy: rows.filter((r) => !r.entry),
  lazyGzipTotal: rows.filter((r) => !r.entry).reduce((n, r) => n + r.gzip, 0),
};
writeFileSync(`${dir}/size-report.json`, JSON.stringify(report, null, 2));
console.table(rows.map((r) => ({ ...r, kbGz: (r.gzip / 1024).toFixed(1) })));
if (!report.entry || report.entry.hasCodeMirror) {
  console.error("FAIL: entry chunk missing or contains CodeMirror");
  process.exit(1);
}
