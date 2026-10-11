// The panel's classifier must agree with the backend's, or the same message
// would sit in different mailboxes in Gmail and in the dashboard. Rather than
// copy the fixtures, this runs the backend's own classifier test cases through
// both implementations and compares category, confidence and promo
// subcategory. Needs the backend virtualenv; skips with a notice without it.
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const backend = fileURLToPath(new URL("../../backend", import.meta.url));
const python = `${backend}/.venv/bin/python`;
if (!existsSync(python)) {
  console.log("skipped: no backend/.venv to read the reference cases from");
  process.exit(0);
}

const DUMP = `
import sys, json, os
sys.path.insert(0, "tests"); sys.path.insert(0, ".")
os.environ.setdefault("GOOGLE_CLOUD_PROJECT", "test-project")
from conftest import mk
import test_classifier as unit, test_real_mail_cases as real
from app.services.classifier import RuleClassifier, extract_promo_subcategory
clf = RuleClassifier()
out = []
for source, cases in (("unit", unit.CASES), ("real", real.CASES)):
    for case_id, kwargs, expected in cases:
        email = mk(**kwargs)
        category, confidence = clf.classify(email)
        out.append({"id": source + ":" + case_id,
                    "email": {"subject": email.subject, "snippet": email.snippet,
                              "body_text": email.body_text, "labels": email.labels,
                              "sender": email.sender, "sender_domain": email.sender_domain},
                    "expected": expected, "category": category, "confidence": confidence,
                    "promo_subcategory": extract_promo_subcategory(email)})
json.dump(out, sys.stdout)
`;

const cases = JSON.parse(
  execFileSync(python, ["-I", "-c", DUMP], { cwd: backend, encoding: "utf8", maxBuffer: 32e6 })
);
assert.ok(cases.length > 100, "expected the backend's full case list");

// classifier.js is a plain script shared with the content scripts, so it is
// loaded the same way a service worker would: given a global to attach to.
const source = readFileSync(fileURLToPath(new URL("../src/classifier.js", import.meta.url)), "utf8");
const module = { exports: {} };
globalThis.self = {};
new Function("module", "self", source)(module, globalThis.self);
const { classify, promoSubcategory } = module.exports;

const mismatches = [];
for (const c of cases) {
  const got = classify(c.email);
  const sub = promoSubcategory(c.email);
  if (got.category !== c.category || got.confidence !== c.confidence || sub !== c.promo_subcategory) {
    mismatches.push(`${c.id}: backend ${c.category}/${c.confidence}/${c.promo_subcategory}` +
      ` vs panel ${got.category}/${got.confidence}/${sub}`);
  }
  assert.equal(got.category, c.expected, `${c.id} should be ${c.expected}`);
}
assert.deepEqual(mismatches, [], mismatches.join("\n"));
console.log(`${cases.length} classifier cases match the backend`);
