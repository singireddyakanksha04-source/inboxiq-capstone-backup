function folded(text) {
  return text.normalize("NFD").replace(/\p{Diacritic}/gu, "").toLocaleLowerCase();
}

function indexedFold(text) {
  let value = "";
  const offsets = [0];
  let position = 0;
  for (const character of text) {
    const normalized = folded(character);
    value += normalized;
    for (let i = 0; i < normalized.length; i++) offsets.push(position + character.length);
    position += character.length;
    // Combining marks belong to the original character, including at a match end.
    offsets[value.length] = position;
  }
  return { value, offsets };
}

export function searchTerms(query) {
  const terms = [];
  const pattern = /(?:(?:from|subject):)?(?:"([^"]*)"?|(\S+))/gi;
  for (const match of query.matchAll(pattern)) {
    const term = folded(match[1] ?? match[2]);
    if (term) terms.push(term);
  }
  return terms;
}

export function MatchText({ text = "", query = "" }) {
  const terms = searchTerms(query);
  if (!terms.length) return text;
  const { value: lower, offsets } = indexedFold(text);
  const parts = [];
  let start = 0;
  while (start < lower.length) {
    const hits = terms.map((term) => ({ index: lower.indexOf(term, start), length: term.length }))
      .filter((hit) => hit.index >= 0).sort((a, b) => a.index - b.index || b.length - a.length);
    if (!hits.length) { parts.push(text.slice(offsets[start])); break; }
    const hit = hits[0];
    parts.push(text.slice(offsets[start], offsets[hit.index]));
    parts.push(<mark key={hit.index}>{text.slice(offsets[hit.index], offsets[hit.index + hit.length])}</mark>);
    start = hit.index + hit.length;
  }
  return parts;
}

export function matchingSnippet(email, query) {
  const terms = searchTerms(query);
  const snippet = email.snippet || "";
  if (!terms.length || terms.some((term) => folded(snippet).includes(term))) return snippet;
  const body = (email.body_text || "").replace(/\s+/g, " ");
  const { value, offsets } = indexedFold(body);
  const hits = terms.map((term) => value.indexOf(term)).filter((index) => index >= 0).map((index) => offsets[index]);
  if (!hits.length) return snippet;
  const start = Math.max(0, Math.min(...hits) - 45);
  return `${start ? "…" : ""}${body.slice(start, start + 200)}`;
}
