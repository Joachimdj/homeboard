// Generated demo pictures (real PNG bytes, no DOM), a tiny PDF, and a store that
// hands out expiring "signed" URLs the way the real files view does.

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function adler32(bytes) {
  let a = 1;
  let b = 0;
  for (const byte of bytes) {
    a = (a + byte) % 65521;
    b = (b + a) % 65521;
  }
  return ((b << 16) | a) >>> 0;
}

const be32 = (n) => [(n >>> 24) & 255, (n >>> 16) & 255, (n >>> 8) & 255, n & 255];

function concat(parts) {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let offset = 0;
  for (const part of parts) {
    out.set(part, offset);
    offset += part.length;
  }
  return out;
}

function chunk(type, data) {
  const body = concat([Uint8Array.from([...type].map((c) => c.charCodeAt(0))), data]);
  return concat([Uint8Array.from(be32(data.length)), body, Uint8Array.from(be32(crc32(body)))]);
}

/** painter(x, y) -> [r, g, b]. Uncompressed (stored) zlib blocks keep this tiny. */
export function makePng(width, height, painter) {
  const raw = new Uint8Array(height * (1 + width * 3));
  let at = 0;
  for (let y = 0; y < height; y++) {
    raw[at++] = 0;
    for (let x = 0; x < width; x++) {
      const [r, g, b] = painter(x, y);
      raw[at++] = r;
      raw[at++] = g;
      raw[at++] = b;
    }
  }
  const blocks = [Uint8Array.from([0x78, 0x01])];
  for (let offset = 0; offset < raw.length; offset += 65535) {
    const part = raw.subarray(offset, Math.min(raw.length, offset + 65535));
    const last = offset + part.length >= raw.length ? 1 : 0;
    blocks.push(Uint8Array.from([last, part.length & 255, part.length >> 8, ~part.length & 255, (~part.length >> 8) & 255]), part);
  }
  blocks.push(Uint8Array.from(be32(adler32(raw))));
  const header = Uint8Array.from([...be32(width), ...be32(height), 8, 2, 0, 0, 0]);
  return concat([
    Uint8Array.from([137, 80, 78, 71, 13, 10, 26, 10]),
    chunk("IHDR", header),
    chunk("IDAT", concat(blocks)),
    chunk("IEND", new Uint8Array(0)),
  ]);
}

function hsv(h, s, v) {
  const f = (n) => {
    const k = (n + h / 60) % 6;
    return Math.round((v - v * s * Math.max(0, Math.min(k, 4 - k, 1))) * 255);
  };
  return [f(5), f(3), f(1)];
}

/** A little "photograph": sky gradient, ground, a disc and stripes, tinted by `seed`. */
const pictures = new Map();

export function demoPicture(seed, width = 320, height = 200) {
  const key = `${seed}:${width}:${height}`;
  if (!pictures.has(key)) pictures.set(key, paintPicture(seed, width, height));
  return pictures.get(key);
}

function paintPicture(seed, width, height) {
  const hue = (Math.abs(seed) * 47) % 360;
  const cx = width * (0.3 + ((Math.abs(seed) * 13) % 40) / 100);
  const cy = height * 0.42;
  const radius = height * 0.2;
  return makePng(width, height, (x, y) => {
    if (Math.hypot(x - cx, y - cy) < radius) return hsv((hue + 40) % 360, 0.55, 0.95);
    if (y > height * 0.68) return hsv((hue + 120) % 360, 0.5, 0.35 + 0.25 * ((Math.floor(x / 14) + Math.floor(y / 14)) % 2));
    return hsv(hue, 0.35, 0.55 + 0.4 * (1 - y / height));
  });
}

export const MINIMAL_PDF = new TextEncoder().encode(
  "%PDF-1.1\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n" +
    "3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 300 160]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n" +
    "4 0 obj<</Length 46>>stream\nBT /F1 20 Tf 24 80 Td (Homeboard demo PDF) Tj ET\nendstream endobj\n" +
    "5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n",
);

/** Files by attachment id; url() returns a blob: URL that stops working after expire(). */
export class FileStore {
  constructor() {
    this.files = new Map();
    this.urls = new Map();
  }

  add(id, { mime, bytes, thumb = null }) {
    this.files.set(id, { mime, bytes, thumb });
  }

  remove(id) {
    this.files.delete(id);
    for (const key of [...this.urls.keys()].filter((k) => k.startsWith(`${id}:`))) {
      URL.revokeObjectURL(this.urls.get(key));
      this.urls.delete(key);
    }
  }

  /** null for a thumbnail of something that has none (PDF). */
  url(id, thumbnail = false) {
    const file = this.files.get(id);
    const bytes = thumbnail ? (file?.thumb ?? (file?.mime.startsWith("image/") ? file.bytes : null)) : file?.bytes;
    if (!bytes) return null;
    const key = `${id}:${thumbnail ? "t" : "f"}`;
    if (!this.urls.has(key)) this.urls.set(key, URL.createObjectURL(new Blob([bytes], { type: file.mime })));
    return this.urls.get(key);
  }

  /** Revoke every URL handed out so far; the next detail fetch signs fresh ones. */
  expire() {
    for (const url of this.urls.values()) URL.revokeObjectURL(url);
    this.urls.clear();
  }
}
