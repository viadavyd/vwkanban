// Plan §7 "Initial JS": the JS that login, dashboard and board load (the entry script and
// its modulepreloads in dist/index.html) is < 80 KB gzip, and the CodeMirror editor is in
// a lazy chunk only. Run after `vite build` (npm run size). Report-only unless
// VWK_PERF_ENFORCE=1, like the other §7 checks.
import { readFileSync, readdirSync } from "node:fs";
import { gzipSync } from "node:zlib";

const LIMIT_KB = 80;
const dir = "dist";
const enforce = process.env.VWK_PERF_ENFORCE === "1";

const html = readFileSync(`${dir}/index.html`, "utf8");
const initial = [
  ...html.matchAll(/<script[^>]+src="\/assets\/([^"]+\.js)"/g),
  ...html.matchAll(/<link[^>]+rel="modulepreload"[^>]+href="\/assets\/([^"]+\.js)"/g),
].map((m) => m[1]);

// ".cm-content" is a CodeMirror theme selector that survives minification.
const rows = readdirSync(`${dir}/assets`)
  .filter((f) => f.endsWith(".js"))
  .map((file) => {
    const buf = readFileSync(`${dir}/assets/${file}`);
    return {
      file,
      initial: initial.includes(file),
      codemirror: buf.toString("utf8").includes("cm-content"),
      kbGzip: Math.round((gzipSync(buf, { level: 9 }).length / 1024) * 10) / 10,
    };
  });
console.table(rows);

const initialKb = rows.filter((r) => r.initial).reduce((n, r) => n + r.kbGzip, 0);
const failures = [];
if (initial.length === 0) failures.push("no entry script in dist/index.html");
if (initialKb >= LIMIT_KB) failures.push(`initial JS ${initialKb.toFixed(1)} KB gz ≥ ${LIMIT_KB}`);
if (rows.some((r) => r.initial && r.codemirror)) failures.push("CodeMirror is in the initial JS");
if (!rows.some((r) => !r.initial && r.codemirror)) failures.push("no lazy CodeMirror chunk");

console.log(
  `perf: initial JS ${initialKb.toFixed(1)} KB gz (limit ${LIMIT_KB}); ` +
    `editor lazy: ${!rows.some((r) => r.initial && r.codemirror)}`,
);
for (const f of failures) console.error(`${enforce ? "FAIL" : "report"}: ${f}`);
if (enforce && failures.length) process.exit(1);
