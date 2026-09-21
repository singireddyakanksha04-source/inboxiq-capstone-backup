// Same name, same colour, every time: sender monograms and subscription
// tiles pick a system colour from the name itself.
const TONES = ["blue", "purple", "pink", "orange", "green", "teal", "indigo", "red"];

export function toneFor(name) {
  let h = 0;
  for (const ch of String(name || "?")) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return TONES[h % TONES.length];
}
