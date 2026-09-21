import { randomBytes } from "node:crypto";
import { deflateRawSync, inflateRawSync } from "node:zlib";

// Exact duplicates are detected tenant-wide (backend/UPLOAD_DUPLICATES.md): a byte-identical
// file that is already stored is skipped with "Exaktes Duplikat". The E2E suite shares one
// tenant across specs and runs, so every upload of a fixture needs its own bytes. These
// helpers return a copy that is functionally the same file but has a different SHA-256:
// PNG gets an extra ancillary tEXt chunk, DOCX a ZIP archive comment (both are ignored by
// readers), and a ZIP has each contained .docx rewritten that way.

const CRC_TABLE = (() => {
  const table = new Uint32Array(256);
  for (let n = 0; n < 256; n++) {
    let c = n;
    for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
    table[n] = c >>> 0;
  }
  return table;
})();

function crc32(buffer: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of buffer) crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}

function nonce(): Buffer {
  return Buffer.from(`hocx-e2e-${Date.now()}-${randomBytes(6).toString("hex")}`, "latin1");
}

export function uniquePng(png: Buffer): Buffer {
  const iendStart = png.length - 12; // IEND is the last chunk: length(4) + "IEND"(4) + crc(4)
  if (iendStart < 8 || png.subarray(iendStart + 4, iendStart + 8).toString("latin1") !== "IEND") {
    throw new Error("uniquePng: PNG does not end with an IEND chunk");
  }
  const data = Buffer.concat([Buffer.from("hocx-e2e\0", "latin1"), nonce()]);
  const type = Buffer.from("tEXt", "latin1");
  const header = Buffer.alloc(4);
  header.writeUInt32BE(data.length);
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([type, data])));
  return Buffer.concat([png.subarray(0, iendStart), header, type, data, crc, png.subarray(iendStart)]);
}

const EOCD_SIGNATURE = 0x06054b50;

function findEndOfCentralDirectory(zip: Buffer): number {
  for (let index = zip.length - 22; index >= Math.max(0, zip.length - 22 - 0xffff); index--) {
    if (zip.readUInt32LE(index) === EOCD_SIGNATURE) return index;
  }
  throw new Error("ZIP: end of central directory not found");
}

export function uniqueDocx(docx: Buffer): Buffer {
  const eocd = findEndOfCentralDirectory(docx);
  const comment = nonce();
  const length = Buffer.alloc(2);
  length.writeUInt16LE(comment.length);
  return Buffer.concat([docx.subarray(0, eocd + 20), length, comment]);
}

type ZipEntry = { name: Buffer; flags: number; time: number; date: number; data: Buffer };

function readZipEntries(zip: Buffer): ZipEntry[] {
  const eocd = findEndOfCentralDirectory(zip);
  const count = zip.readUInt16LE(eocd + 10);
  let cursor = zip.readUInt32LE(eocd + 16);
  const entries: ZipEntry[] = [];
  for (let i = 0; i < count; i++) {
    if (zip.readUInt32LE(cursor) !== 0x02014b50) throw new Error("ZIP: bad central directory entry");
    const flags = zip.readUInt16LE(cursor + 8);
    const method = zip.readUInt16LE(cursor + 10);
    const time = zip.readUInt16LE(cursor + 12);
    const date = zip.readUInt16LE(cursor + 14);
    const compressedSize = zip.readUInt32LE(cursor + 20);
    const nameLength = zip.readUInt16LE(cursor + 28);
    const extraLength = zip.readUInt16LE(cursor + 30);
    const commentLength = zip.readUInt16LE(cursor + 32);
    const localOffset = zip.readUInt32LE(cursor + 42);
    const name = zip.subarray(cursor + 46, cursor + 46 + nameLength);
    cursor += 46 + nameLength + extraLength + commentLength;

    const dataStart = localOffset + 30 + zip.readUInt16LE(localOffset + 26) + zip.readUInt16LE(localOffset + 28);
    const raw = zip.subarray(dataStart, dataStart + compressedSize);
    if (method !== 0 && method !== 8) throw new Error(`ZIP: unsupported compression method ${method}`);
    entries.push({ name, flags: flags & 0x0800, time, date, data: method === 8 ? inflateRawSync(raw) : Buffer.from(raw) });
  }
  return entries;
}

function writeZip(entries: ZipEntry[]): Buffer {
  const locals: Buffer[] = [];
  const centrals: Buffer[] = [];
  let offset = 0;
  for (const entry of entries) {
    const compressed = deflateRawSync(entry.data);
    const crc = crc32(entry.data);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(entry.flags, 6);
    local.writeUInt16LE(8, 8);
    local.writeUInt16LE(entry.time, 10);
    local.writeUInt16LE(entry.date, 12);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(compressed.length, 18);
    local.writeUInt32LE(entry.data.length, 22);
    local.writeUInt16LE(entry.name.length, 26);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(entry.flags, 8);
    central.writeUInt16LE(8, 10);
    central.writeUInt16LE(entry.time, 12);
    central.writeUInt16LE(entry.date, 14);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(compressed.length, 20);
    central.writeUInt32LE(entry.data.length, 24);
    central.writeUInt16LE(entry.name.length, 28);
    central.writeUInt32LE(offset, 42);
    locals.push(local, entry.name, compressed);
    centrals.push(central, entry.name);
    offset += local.length + entry.name.length + compressed.length;
  }
  const directory = Buffer.concat(centrals);
  const eocd = Buffer.alloc(22);
  eocd.writeUInt32LE(EOCD_SIGNATURE, 0);
  eocd.writeUInt16LE(entries.length, 8);
  eocd.writeUInt16LE(entries.length, 10);
  eocd.writeUInt32LE(directory.length, 12);
  eocd.writeUInt32LE(offset, 16);
  return Buffer.concat([...locals, directory, eocd]);
}

export function uniqueZip(zip: Buffer): Buffer {
  const entries = readZipEntries(zip).map((entry) =>
    entry.name.toString("utf8").toLowerCase().endsWith(".docx") ? { ...entry, data: uniqueDocx(entry.data) } : entry,
  );
  return writeZip(entries);
}
