import fs from "node:fs";
const html = fs.readFileSync("prototypes/rate-card/demo.html", "utf8");
const marker = "// ─── the page: a thin shell over the module above ───";
const script = html.split("<script>")[1].split("</script>")[0];
if (!script.includes(marker)) { console.error("marker not found"); process.exit(2); }
const pure = script.split(marker)[0];
const mod = await import("data:text/javascript," + encodeURIComponent(
  pure + "\nexport { resolve, computeCost, CARDS };"));
const fixtures = JSON.parse(fs.readFileSync("prototypes/rate-card/fixtures.json", "utf8"));
const SHAPES = fixtures.shapes;
let bad = 0, n = 0, skipped = 0, dated = 0;
for (const f of fixtures.fixtures) {
  const isNull = f.shape.startsWith("nullflat:");
  const shape = isNull ? f.shape.slice("nullflat:".length) : f.shape;
  const flat = isNull ? null
    : shape === "missing_prompt_tokens" ? { completion_tokens: 10 }
    : SHAPES[shape];
  if (flat === undefined) { skipped++; continue; }
  const r = mod.resolve(f.model, new Date(f.at));
  const cost = mod.computeCost(r, flat);
  const gotPrice = r.rates ? { miss: r.rates.miss, hit: r.rates.hit, out: r.rates.out } : null;
  if ((f.model || "").toLowerCase().includes("glm-5.3-flash")) { dated++; continue; }
  n++;
  if (JSON.stringify(gotPrice) !== JSON.stringify(f.price)) {
    if (bad++ < 3) console.error("PRICE", f.model, f.shape, f.at, f.price, gotPrice);
  }
  if (cost !== f.cost) {
    if (bad++ < 6) console.error("COST", f.model, f.shape, f.at, f.cost, cost);
  }
}
console.log(`demo.html JS vs real usage-lib.mjs: ${n} compared, `
  + `${skipped} skipped, ${dated} dated-range (checked in parity_check.py), ${bad} mismatches`);
process.exit(bad ? 1 : 0);
