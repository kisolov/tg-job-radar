// Статичный локальный превью макета: .dc.html → обычный .html (без рантайма Claude Design).
// Поддерживает ровно то, что используют артборды панели: {{path}}-дыры и одноуровневые <sc-for>.
// Запуск: node design/web-panel/render-preview.mjs  → design/web-panel/preview/*.html
import { readFileSync, writeFileSync, mkdirSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const src = join(here, "project");
const out = join(here, "preview");
mkdirSync(out, { recursive: true });

class DCLogic { constructor() { this.props = {}; this.state = {}; } setState() {} }

function lookup(scope, path) {
  return path.trim().split(".").reduce((v, k) => (v == null ? undefined : v[k]), scope);
}

function holes(text, scope) {
  return text.replace(/\{\{\s*([\w.$]+)\s*\}\}/g, (_, p) => {
    const v = lookup(scope, p);
    return v == null ? "" : String(v);
  });
}

function expand(tpl, scope) {
  const re = /<sc-for\s+list="\{\{\s*([\w.]+)\s*\}\}"\s+as="(\w+)"[^>]*>([\s\S]*?)<\/sc-for>/g;
  return holes(tpl.replace(re, (_, list, as, inner) =>
    (lookup(scope, list) || []).map((item, i) => holes(inner, { ...scope, [as]: item, $index: i })).join("")
  ), scope);
}

for (const file of readdirSync(src).filter((f) => f.endsWith(".dc.html"))) {
  const html = readFileSync(join(src, file), "utf8");
  const title = (html.match(/<title>([\s\S]*?)<\/title>/) || [, file])[1];
  const helmet = (html.match(/<helmet>([\s\S]*?)<\/helmet>/) || [, ""])[1];
  const body = html.match(/<x-dc>([\s\S]*?)<\/x-dc>/)[1].replace(/<helmet>[\s\S]*?<\/helmet>/, "");
  const script = (html.match(/<script type="text\/x-dc"[^>]*>([\s\S]*?)<\/script>/) || [])[1];
  // статичный артборд (без скрипта и дыр) рендерится как есть
  const vals = script ? new (new Function("DCLogic", `${script}; return Component;`)(DCLogic))().renderVals() : {};
  const page = expand(body, vals).replace(/href="(\w+)\.dc\.html"/g, 'href="$1.html"');
  const name = file.replace(/\.dc\.html$/, ".html");
  writeFileSync(join(out, name),
    `<!doctype html>\n<html lang="ru">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width, initial-scale=1">\n<title>${title}</title>\n${helmet}\n</head>\n<body>\n${page}\n</body>\n</html>\n`);
  console.log("ok", name);
}
