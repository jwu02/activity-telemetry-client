/**
 * PROTOTYPE — throwaway. Generates ground-truth pricing fixtures by driving the
 * REAL ai-usage/usage-lib.mjs. The Python port is checked against this output.
 *
 *   node prototypes/rate-card/gen_fixtures.mjs > prototypes/rate-card/fixtures.json
 *
 * Usage: node gen_fixtures.mjs [path/to/usage-lib.mjs]
 */
import { pathToFileURL } from "node:url";
import path from "node:path";

const libPath = process.argv[2]
  ? path.resolve(process.argv[2])
  : path.resolve(import.meta.dirname, "../../../ai-usage/usage-lib.mjs");
const { resolvePrice, computeCostYuan, canonicalModelName } = await import(
  pathToFileURL(libPath).href
);

// normalizeModel is module-private in usage-lib.mjs; mirror its one-liner here.
const normalizeModel = (m) =>
  (m || "").replace(/\[.*?\]/g, "").trim().toLowerCase();

// ── Fixture matrix ─────────────────────────────────────────────────────────

// Every key currently in PRICING, the alias sources, the alias targets, and
// deliberate near-misses (the glm-5.3 / glm-5.3-flash trap, bracket suffixes,
// unknown models, substring traps).
const MODELS = [
  "kimi-k3",
  "kimi-k2.7-code",
  "kimi-k2.6",
  "kimi-k2.5",
  "deepseek-v4.1-flash",
  "deepseek-v4-pro",
  "deepseek-v4-flash",
  "glm-5.3",
  "glm-5.3-flash",
  // near-misses / shapes
  "GLM-5.3-FLASH",
  "glm-5.3[1m]",
  "glm-5.3-flash[1m]",
  "  glm-5.3-flash  ",
  "deepseek-v4-flash-vision-exp",
  "deepseek-v4-pro-202606",
  "my-kimi-k3-pro",
  "xdeepseek-v4-pro",
  "deepseek-v4",
  "kimi",
  "moonshot-v1",
  "anthropic/claude-sonnet-5",
  "unknown-model-9000",
  "",
  null,
];

// Instants around the Beijing-time band boundaries (Beijing = UTC+8), plus a
// few well inside a band. 09:00 BJ = 01:00Z, 12:00 BJ = 04:00Z,
// 14:00 BJ = 06:00Z, 18:00 BJ = 10:00Z.
const INSTANTS = [
  "2026-06-15T00:59:59Z", // 08:59:59 BJ — off-peak
  "2026-06-15T01:00:00Z", // 09:00:00 BJ — peak starts (inclusive)
  "2026-06-15T01:30:00Z", // 09:30:00 BJ — peak
  "2026-06-15T03:59:59Z", // 11:59:59 BJ — peak ends
  "2026-06-15T04:00:00Z", // 12:00:00 BJ — off-peak starts (exclusive)
  "2026-06-15T05:59:59Z", // 13:59:59 BJ — off-peak
  "2026-06-15T06:00:00Z", // 14:00:00 BJ — peak starts (inclusive)
  "2026-06-15T09:59:59Z", // 17:59:59 BJ — peak ends
  "2026-06-15T10:00:00Z", // 18:00:00 BJ — off-peak starts (exclusive)
  "2026-06-15T16:00:00Z", // 00:00:00 BJ next day — off-peak
  "2026-01-01T00:00:00Z", // winter, far from any boundary
];

// Token shapes: the normal case, both cache extremes, fresh-tokens-not-cached,
// a negative-fresh case the JS arithmetic permits, missing/zero fields, and
// non-integer token counts.
const TOKEN_SHAPES = {
  typical: {
    prompt_tokens: 10000,
    completion_tokens: 500,
    total_tokens: 10500,
    prompt_cache_hit_tokens: 4000,
    prompt_cache_miss_tokens: 6000,
  },
  no_cache: {
    prompt_tokens: 10000,
    completion_tokens: 100,
    total_tokens: 10100,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 10000,
  },
  all_cache_hit: {
    prompt_tokens: 10000,
    completion_tokens: 100,
    total_tokens: 10100,
    prompt_cache_hit_tokens: 10000,
    prompt_cache_miss_tokens: 0,
  },
  fresh_uncached: {
    // hit+miss (6000) < prompt (10000): 4000 "fresh" tokens billed at miss.
    prompt_tokens: 10000,
    completion_tokens: 200,
    total_tokens: 10200,
    prompt_cache_hit_tokens: 3000,
    prompt_cache_miss_tokens: 3000,
  },
  hit_plus_miss_exceeds_prompt: {
    // Negative "fresh": the JS arithmetic allows it. Does the port match?
    prompt_tokens: 1000,
    completion_tokens: 10,
    total_tokens: 1010,
    prompt_cache_hit_tokens: 800,
    prompt_cache_miss_tokens: 800,
  },
  zero_output: {
    prompt_tokens: 500,
    completion_tokens: 0,
    total_tokens: 500,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 500,
  },
  completion_missing: {
    prompt_tokens: 500,
    prompt_cache_hit_tokens: 0,
    prompt_cache_miss_tokens: 500,
  },
  cache_fields_missing: {
    prompt_tokens: 1234,
    completion_tokens: 56,
    total_tokens: 1290,
  },
  tiny_fractional: {
    prompt_tokens: 3,
    completion_tokens: 1,
    total_tokens: 4,
    prompt_cache_hit_tokens: 1,
    prompt_cache_miss_tokens: 1,
  },
};

const fixtures = [];
for (const model of MODELS) {
  for (const [shapeName, flat] of Object.entries(TOKEN_SHAPES)) {
    for (const iso of INSTANTS) {
      const at = new Date(iso);
      const price = resolvePrice(model, at);
      fixtures.push({
        model,
        shape: shapeName,
        at: iso,
        flat,
        canonical: canonicalModelName(model) ?? null,
        normalized: normalizeModel(model),
        price: price ?? null,
        cost: computeCostYuan(model, flat, at),
      });
    }
  }
}

// The null-argument cases are part of the contract too.
for (const [shapeName, flat] of Object.entries(TOKEN_SHAPES)) {
  fixtures.push({
    model: "deepseek-v4-pro",
    shape: `nullflat:${shapeName}`,
    at: INSTANTS[0],
    flat: null,
    canonical: "deepseek-v4-pro",
    normalized: "deepseek-v4-pro",
    price: resolvePrice("deepseek-v4-pro", new Date(INSTANTS[0])) ?? null,
    cost: computeCostYuan("deepseek-v4-pro", null, new Date(INSTANTS[0])),
  });
}
fixtures.push({
  model: "deepseek-v4-pro",
  shape: "missing_prompt_tokens",
  at: INSTANTS[0],
  flat: { completion_tokens: 10 },
  canonical: "deepseek-v4-pro",
  normalized: "deepseek-v4-pro",
  price: resolvePrice("deepseek-v4-pro", new Date(INSTANTS[0])) ?? null,
  cost: computeCostYuan(
    "deepseek-v4-pro",
    { completion_tokens: 10 },
    new Date(INSTANTS[0]),
  ),
});

process.stdout.write(
  JSON.stringify(
    {
      source: path.relative(process.cwd(), libPath),
      generatedFor: "rate-card prototype parity check",
      note:
        "Every fixture exercises model matching, band selection, and cost " +
        "arithmetic only. Effective date ranges are NEW behaviour with no " +
        "counterpart in usage-lib.mjs, so they are outside this parity set.",
      count: fixtures.length,
      shapes: TOKEN_SHAPES,
      fixtures,
    },
    null,
    2,
  ) + "\n",
);
