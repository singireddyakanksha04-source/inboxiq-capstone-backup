import assert from "node:assert/strict";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { build } from "esbuild";

const scratch = await mkdtemp(join(tmpdir(), "inboxiq-search-test-"));
try {
  const output = join(scratch, "match-text.mjs");
  await build({ entryPoints: [fileURLToPath(new URL("../src/features/emails/MatchText.jsx", import.meta.url))],
    bundle: true, platform: "node", format: "esm", jsx: "automatic", outfile: output });
  const { MatchText, searchTerms, matchingSnippet } = await import(pathToFileURL(output).href);
  const render = (text, query) => renderToStaticMarkup(React.createElement(MatchText, { text, query }));
  assert.equal(render("Cafe\u0301 discount", "cafe"), "<mark>Cafe\u0301</mark> discount");
  assert.equal(render("Café discount", "CAFE"), "<mark>Café</mark> discount");
  assert.equal(render("A Cafe\u0301 offer", "offer"), "A Cafe\u0301 <mark>offer</mark>");
  assert.equal(render("Cafe\u0301 cafe", "cafe"), "<mark>Cafe\u0301</mark> <mark>cafe</mark>");
  assert.equal(render("learn c++ safely", "c++"), "learn <mark>c++</mark> safely");
  assert.equal(render("<script>alert(1)</script>", "alert"), "&lt;script&gt;<mark>alert</mark>(1)&lt;/script&gt;");
  assert.equal(render("no match", "zebra"), "no match");
  assert.deepEqual(searchTerms('from:shop subject:"running shoes"'), ["shop", "running shoes"]);
  assert.ok(matchingSnippet({ snippet: "preview", body_text: "x ".repeat(120) + "Cafe\u0301 offer" }, "cafe").includes("Cafe\u0301"));
  console.log("9 search-text regression checks passed");
} finally { await rm(scratch, { recursive: true, force: true }); }
