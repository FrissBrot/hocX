// Liest Aufnahmedatum, GPS, Kamera, Abmessungen und Ausrichtung direkt aus den Dateibytes -
// ohne Bibliothek und ohne Netzwerk, damit der Browser vor dem Upload entscheiden kann, ob ein
// Bild schon vorhanden ist und ob ihm ein Aufnahmedatum fehlt. Unterstützt JPEG, PNG, WebP, TIFF
// und HEIC/HEIF (ISOBMFF), dazu XMP in JPEG/PNG/WebP. GIF und BMP tragen praktisch keine
// Metadaten: lesbar, aber ohne Datum. Alles andere gilt als "nicht prüfbar".
//
// Konventionen wie im Backend (image_metadata_service.py): Datum = lokale Kamerazeit ohne
// Zeitzone ("YYYY-MM-DDTHH:MM:SS"), Offset separat, Süd/West negativ, (0, 0) = kein GPS-Fix.
// Die Werte sind nur Hinweise - der Server validiert alles erneut.

export type ImageFormat = "jpeg" | "png" | "webp" | "tiff" | "heic" | "gif" | "bmp";

export type ParsedGps = {
  latitude: number;
  longitude: number;
  altitude_m?: number;
  direction_deg?: number;
  accuracy_m?: number;
  timestamp?: string;
};

export type ParsedImageMetadata = {
  taken_at?: string;
  taken_offset?: string;
  gps?: ParsedGps;
  camera_make?: string;
  camera_model?: string;
  width?: number;
  height?: number;
  orientation?: number;
  // Von hocX exportiertes Schätzdatum (XMP-Markierung) - nie ein echtes Aufnahmedatum.
  estimated_taken_on?: string;
};

const MIN_YEAR = 1826;

export function detectImageFormat(bytes: Uint8Array): ImageFormat | null {
  if (bytes.length < 12) return null;
  if (bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return "jpeg";
  if (bytes[0] === 0x89 && bytes[1] === 0x50 && bytes[2] === 0x4e && bytes[3] === 0x47) return "png";
  if (ascii(bytes, 0, 4) === "RIFF" && ascii(bytes, 8, 4) === "WEBP") return "webp";
  if ((bytes[0] === 0x49 && bytes[1] === 0x49 && bytes[2] === 0x2a && bytes[3] === 0) || (bytes[0] === 0x4d && bytes[1] === 0x4d && bytes[2] === 0 && bytes[3] === 0x2a)) return "tiff";
  if (ascii(bytes, 0, 3) === "GIF") return "gif";
  if (bytes[0] === 0x42 && bytes[1] === 0x4d) return "bmp";
  if (ascii(bytes, 4, 4) === "ftyp") {
    const brand = ascii(bytes, 8, 4);
    if (["heic", "heix", "hevc", "hevx", "heim", "heis", "mif1", "msf1", "heif", "avif"].includes(brand)) return brand === "avif" ? null : "heic";
  }
  return null;
}

function ascii(bytes: Uint8Array, offset: number, length: number): string {
  let text = "";
  for (let i = offset; i < Math.min(bytes.length, offset + length); i++) text += String.fromCharCode(bytes[i]);
  return text;
}

function utf8(bytes: Uint8Array): string {
  return new TextDecoder("utf-8", { fatal: false }).decode(bytes);
}

// --- TIFF/EXIF ------------------------------------------------------------------------------

type TagValue = number | number[] | string | Uint8Array;
type Ifd = Map<number, TagValue>;
type ExifData = { ifd0: Ifd; exif: Ifd; gps: Ifd };

const TYPE_SIZES: Record<number, number> = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8 };

function readIfd(view: DataView, offset: number, little: boolean): { tags: Ifd } {
  const tags: Ifd = new Map();
  if (offset < 8 || offset + 2 > view.byteLength) return { tags };
  const count = view.getUint16(offset, little);
  for (let i = 0; i < count && i < 1000; i++) {
    const entry = offset + 2 + i * 12;
    if (entry + 12 > view.byteLength) break;
    const tag = view.getUint16(entry, little);
    const type = view.getUint16(entry + 2, little);
    const n = view.getUint32(entry + 4, little);
    const size = (TYPE_SIZES[type] ?? 0) * n;
    if (!size || n > 100_000) continue;
    const valueOffset = size <= 4 ? entry + 8 : view.getUint32(entry + 8, little);
    if (valueOffset + size > view.byteLength) continue;
    tags.set(tag, readValue(view, valueOffset, type, n, little));
  }
  return { tags };
}

function readValue(view: DataView, offset: number, type: number, count: number, little: boolean): TagValue {
  if (type === 2) {
    let text = "";
    for (let i = 0; i < count; i++) {
      const code = view.getUint8(offset + i);
      if (code === 0) break;
      text += String.fromCharCode(code);
    }
    return text.trim();
  }
  if (type === 7 || type === 1 || type === 6) {
    if (count === 1) return view.getUint8(offset);
    return new Uint8Array(view.buffer, view.byteOffset + offset, count);
  }
  const values: number[] = [];
  for (let i = 0; i < count; i++) {
    const at = offset + i * (TYPE_SIZES[type] ?? 0);
    if (type === 3) values.push(view.getUint16(at, little));
    else if (type === 8) values.push(view.getInt16(at, little));
    else if (type === 4) values.push(view.getUint32(at, little));
    else if (type === 9) values.push(view.getInt32(at, little));
    else if (type === 5 || type === 10) {
      const numerator = type === 5 ? view.getUint32(at, little) : view.getInt32(at, little);
      const denominator = type === 5 ? view.getUint32(at + 4, little) : view.getInt32(at + 4, little);
      values.push(denominator === 0 ? Number.NaN : numerator / denominator);
    } else if (type === 11) values.push(view.getFloat32(at, little));
    else if (type === 12) values.push(view.getFloat64(at, little));
  }
  return count === 1 ? values[0] : values;
}

export function parseTiff(bytes: Uint8Array): ExifData | null {
  if (bytes.length < 8) return null;
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const order = ascii(bytes, 0, 2);
  if (order !== "II" && order !== "MM") return null;
  const little = order === "II";
  if (view.getUint16(2, little) !== 42) return null;
  const ifd0 = readIfd(view, view.getUint32(4, little), little).tags;
  const exifPointer = ifd0.get(0x8769);
  const gpsPointer = ifd0.get(0x8825);
  const exif = typeof exifPointer === "number" ? readIfd(view, exifPointer, little).tags : new Map();
  const gps = typeof gpsPointer === "number" ? readIfd(view, gpsPointer, little).tags : new Map();
  return { ifd0, exif, gps };
}

function stripExifHeader(bytes: Uint8Array): Uint8Array {
  return ascii(bytes, 0, 6) === "Exif\0\0" ? bytes.subarray(6) : bytes;
}

// --- Werte deuten ---------------------------------------------------------------------------

const DATETIME_RE = /^\s*(\d{4})[:-](\d{2})[:-](\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/;
const OFFSET_RE = /^([+-])(\d{2}):?(\d{2})$/;

export function parseCaptureDateTime(raw: unknown, now: Date = new Date()): string | undefined {
  if (typeof raw !== "string") return undefined;
  const match = DATETIME_RE.exec(raw.replace(/\0/g, ""));
  if (!match) return undefined;
  const [, y, mo, d, h, mi, s] = match;
  const year = Number(y), month = Number(mo), day = Number(d), hour = Number(h), minute = Number(mi), second = Number(s ?? "0");
  if (year < MIN_YEAR || month < 1 || month > 12 || day < 1 || hour > 23 || minute > 59 || second > 59) return undefined;
  const asUtc = Date.UTC(year, month - 1, day, hour, minute, second);
  const check = new Date(asUtc);
  if (check.getUTCDate() !== day || check.getUTCMonth() !== month - 1) return undefined; // 31.02. usw.
  // Zukunft: gleiche Toleranz wie der Server (1 Tag, image_metadata_service._MAX_FUTURE) - sonst
  // zeigt das Popup "hat Datum", der Server verwirft es aber und das Bild landet beim Uploaddatum.
  if (asUtc > now.getTime() + 86_400_000) return undefined;
  return `${y}-${mo}-${d}T${h}:${mi}:${s ?? "00"}`;
}

export function parseOffset(raw: unknown): string | undefined {
  if (typeof raw !== "string") return undefined;
  const match = OFFSET_RE.exec(raw.trim());
  if (!match || Number(match[2]) > 14 || Number(match[3]) >= 60) return undefined;
  return `${match[1]}${match[2]}:${match[3]}`;
}

function text(value: TagValue | undefined): string | undefined {
  if (typeof value !== "string") return undefined;
  const cleaned = value.replace(/\0/g, "").trim().slice(0, 120);
  return cleaned || undefined;
}

function num(value: TagValue | undefined): number | undefined {
  const n = Array.isArray(value) ? value[0] : value;
  return typeof n === "number" && Number.isFinite(n) ? n : undefined;
}

function dmsToDegrees(value: TagValue | undefined): number | undefined {
  if (typeof value === "number") return Number.isFinite(value) ? value : undefined;
  if (!Array.isArray(value) || value.length === 0 || value.some((part) => !Number.isFinite(part))) return undefined;
  return value[0] + (value[1] ?? 0) / 60 + (value[2] ?? 0) / 3600;
}

function ref(value: TagValue | undefined): string {
  return typeof value === "string" ? value.trim().toUpperCase().slice(0, 1) : "";
}

export function gpsFromIfd(gps: Ifd): ParsedGps | undefined {
  let latitude = dmsToDegrees(gps.get(2));
  let longitude = dmsToDegrees(gps.get(4));
  if (latitude === undefined || longitude === undefined) return undefined;
  if (ref(gps.get(1)) === "S") latitude = -Math.abs(latitude);
  if (ref(gps.get(3)) === "W") longitude = -Math.abs(longitude);
  if (Math.abs(latitude) > 90 || Math.abs(longitude) > 180 || (latitude === 0 && longitude === 0)) return undefined;
  const result: ParsedGps = { latitude: round(latitude, 7), longitude: round(longitude, 7) };
  let altitude = num(gps.get(6));
  if (altitude !== undefined) {
    const altitudeRef = gps.get(5);
    const below = altitudeRef === 1 || (altitudeRef instanceof Uint8Array && altitudeRef[0] === 1);
    if (below) altitude = -Math.abs(altitude);
    if (altitude >= -12_000 && altitude <= 60_000) result.altitude_m = round(altitude, 2);
  }
  const direction = num(gps.get(17));
  if (direction !== undefined && direction >= 0 && direction <= 360) result.direction_deg = round(direction, 3) % 360; // erst runden: nie 360 (Server-CHECK < 360)
  const accuracy = num(gps.get(31));
  if (accuracy !== undefined && accuracy >= 0 && accuracy <= 100_000) result.accuracy_m = round(accuracy, 2);
  const dateStamp = gps.get(29);
  const timeStamp = gps.get(7);
  if (typeof dateStamp === "string" && Array.isArray(timeStamp) && timeStamp.length === 3 && timeStamp.every(Number.isFinite)) {
    const day = /^(\d{4})[:-](\d{2})[:-](\d{2})/.exec(dateStamp);
    if (day) {
      const ms = Date.UTC(Number(day[1]), Number(day[2]) - 1, Number(day[3])) + (timeStamp[0] * 3600 + timeStamp[1] * 60 + Math.floor(timeStamp[2])) * 1000;
      if (Number.isFinite(ms)) result.timestamp = new Date(ms).toISOString().replace(/\.\d{3}Z$/, "Z");
    }
  }
  return result;
}

function round(value: number, digits: number): number {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
}

function applyExif(target: ParsedImageMetadata, data: ExifData): void {
  target.camera_make ??= text(data.ifd0.get(0x010f));
  target.camera_model ??= text(data.ifd0.get(0x0110));
  const orientation = num(data.ifd0.get(0x0112));
  if (orientation !== undefined && orientation >= 1 && orientation <= 8) target.orientation ??= orientation;
  if (!target.taken_at) {
    const candidates: Array<[number, number]> = [[0x9003, 0x9011], [0x9004, 0x9012]];
    for (const [dateTag, offsetTag] of candidates) {
      const takenAt = parseCaptureDateTime(data.exif.get(dateTag));
      if (takenAt) {
        target.taken_at = takenAt;
        target.taken_offset = parseOffset(data.exif.get(offsetTag)) ?? parseOffset(data.exif.get(0x9010));
        break;
      }
    }
    if (!target.taken_at) {
      // IFD0 DateTime als letzter Ausweg - gleiches Verhalten wie der Server.
      const fallback = parseCaptureDateTime(data.ifd0.get(0x0132));
      if (fallback) {
        target.taken_at = fallback;
        target.taken_offset = parseOffset(data.exif.get(0x9010));
      }
    }
  }
  target.gps ??= gpsFromIfd(data.gps);
  const width = num(data.exif.get(0xa002)) ?? num(data.ifd0.get(0x0100));
  const height = num(data.exif.get(0xa003)) ?? num(data.ifd0.get(0x0101));
  if (width && height) setDimensions(target, width, height);
}

function setDimensions(target: ParsedImageMetadata, width: number, height: number) {
  if (target.width || !(width > 0 && height > 0 && width <= 100_000 && height <= 100_000)) return;
  target.width = Math.round(width);
  target.height = Math.round(height);
}

// --- XMP ------------------------------------------------------------------------------------

function xmpValue(xmp: string, name: string): string | undefined {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escaped}\\s*=\\s*"([^"]+)"|<${escaped}>([^<]+)</${escaped}>`).exec(xmp);
  return match ? (match[1] ?? match[2])?.trim() : undefined;
}

function xmpCoordinate(raw: string | undefined): number | undefined {
  const match = raw ? /^\s*(\d{1,3}),(\d{1,2}(?:\.\d+)?)(?:,(\d{1,2}(?:\.\d+)?))?\s*([NSEW])\s*$/i.exec(raw) : null;
  if (!match) return undefined;
  const value = Number(match[1]) + Number(match[2]) / 60 + (match[3] ? Number(match[3]) / 3600 : 0);
  return /[SW]/i.test(match[4]) ? -value : value;
}

export function applyXmp(target: ParsedImageMetadata, xmp: string): void {
  const estimatedRaw = xmpValue(xmp, "hocx:EstimatedCaptureDate");
  const estimated = estimatedRaw && /^\d{4}-\d{2}-\d{2}$/.test(estimatedRaw) ? estimatedRaw : undefined;
  // Markierung nur, solange das EXIF-Datum fehlt oder exakt dem Exportwert (Schätzdatum 12:00:00)
  // entspricht - ein abweichendes, nachträglich gesetztes Datum ist echt (wie im Server).
  const markerApplies = !target.taken_at || (estimated !== undefined && target.taken_at === `${estimated}T12:00:00`);
  if (/hocx:CaptureDateEstimated\s*=\s*"True"|<hocx:CaptureDateEstimated>True</i.test(xmp) && markerApplies) {
    // Von hocX exportiertes Schätzdatum: das technisch eingetragene 12:00-Datum ist kein
    // echtes Aufnahmedatum.
    target.taken_at = undefined;
    target.taken_offset = undefined;
    if (estimated) target.estimated_taken_on = estimated;
    return;
  }
  if (!target.taken_at) {
    for (const name of ["exif:DateTimeOriginal", "photoshop:DateCreated", "xmp:CreateDate"]) {
      const raw = xmpValue(xmp, name);
      // Ein reines Datum ist kein Aufnahmezeitpunkt - keine Uhrzeit erfinden.
      if (!raw || raw.length < 16) continue;
      const takenAt = parseCaptureDateTime(raw);
      if (takenAt) {
        target.taken_at = takenAt;
        const offset = /([+-]\d{2}:?\d{2})$/.exec(raw);
        target.taken_offset = offset ? parseOffset(offset[1]) : raw.endsWith("Z") ? "+00:00" : undefined;
        break;
      }
    }
  }
  if (!target.gps) {
    const latitude = xmpCoordinate(xmpValue(xmp, "exif:GPSLatitude"));
    const longitude = xmpCoordinate(xmpValue(xmp, "exif:GPSLongitude"));
    if (latitude !== undefined && longitude !== undefined && Math.abs(latitude) <= 90 && Math.abs(longitude) <= 180 && !(latitude === 0 && longitude === 0)) {
      target.gps = { latitude: round(latitude, 7), longitude: round(longitude, 7) };
    }
  }
  target.camera_make ??= xmpValue(xmp, "tiff:Make")?.slice(0, 120);
  target.camera_model ??= xmpValue(xmp, "tiff:Model")?.slice(0, 120);
}

// --- Container ------------------------------------------------------------------------------

const XMP_JPEG_HEADER = "http://ns.adobe.com/xap/1.0/\0";

function parseJpeg(bytes: Uint8Array, target: ParsedImageMetadata): void {
  let pos = 2;
  let xmp: string | undefined;
  while (pos + 4 <= bytes.length) {
    if (bytes[pos] !== 0xff) return;
    const marker = bytes[pos + 1];
    if (marker === 0xff) { pos += 1; continue; }
    if (marker === 0xd9 || marker === 0xda) break;
    if ((marker >= 0xd0 && marker <= 0xd7) || marker === 0x01) { pos += 2; continue; }
    const length = (bytes[pos + 2] << 8) | bytes[pos + 3];
    const payload = bytes.subarray(pos + 4, pos + 2 + length);
    if (marker === 0xe1 && ascii(payload, 0, 6) === "Exif\0\0") {
      const data = parseTiff(payload.subarray(6));
      if (data) applyExif(target, data);
    } else if (marker === 0xe1 && ascii(payload, 0, XMP_JPEG_HEADER.length) === XMP_JPEG_HEADER && xmp === undefined) {
      xmp = utf8(payload.subarray(XMP_JPEG_HEADER.length));
    } else if ([0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf].includes(marker) && payload.length >= 5) {
      const height = (payload[1] << 8) | payload[2];
      const width = (payload[3] << 8) | payload[4];
      // SOF-Masse sind massgeblich (EXIF-PixelDimensions können veraltet sein).
      target.width = undefined;
      setDimensions(target, width, height);
    }
    pos += 2 + length;
  }
  if (xmp) applyXmp(target, xmp);
}

function parsePng(bytes: Uint8Array, target: ParsedImageMetadata): void {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let pos = 8;
  let xmp: string | undefined;
  while (pos + 8 <= bytes.length) {
    const length = view.getUint32(pos);
    const type = ascii(bytes, pos + 4, 4);
    const data = bytes.subarray(pos + 8, pos + 8 + length);
    if (type === "IHDR" && data.length >= 8) {
      setDimensions(target, view.getUint32(pos + 8), view.getUint32(pos + 12));
    } else if (type === "eXIf") {
      const exif = parseTiff(stripExifHeader(data));
      if (exif) applyExif(target, exif);
    } else if (type === "iTXt" && ascii(data, 0, 18) === "XML:com.adobe.xmp\0" && data[18] === 0) {
      // Unkomprimiertes XMP; komprimiertes iTXt ist selten und wird ausgelassen.
      let cursor = 20;
      for (let skip = 0; skip < 2; skip++) {
        while (cursor < data.length && data[cursor] !== 0) cursor++;
        cursor++;
      }
      xmp = utf8(data.subarray(cursor));
    } else if (type === "IEND") break;
    pos += 12 + length;
  }
  if (xmp) applyXmp(target, xmp);
}

function parseWebp(bytes: Uint8Array, target: ParsedImageMetadata): void {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let pos = 12;
  let xmp: string | undefined;
  while (pos + 8 <= bytes.length) {
    const type = ascii(bytes, pos, 4);
    const length = view.getUint32(pos + 4, true);
    const data = bytes.subarray(pos + 8, pos + 8 + length);
    if (type === "VP8X" && data.length >= 10) {
      setDimensions(target, 1 + (data[4] | (data[5] << 8) | (data[6] << 16)), 1 + (data[7] | (data[8] << 8) | (data[9] << 16)));
    } else if (type === "VP8 " && data.length >= 10) {
      setDimensions(target, (data[6] | (data[7] << 8)) & 0x3fff, (data[8] | (data[9] << 8)) & 0x3fff);
    } else if (type === "VP8L" && data.length >= 5 && data[0] === 0x2f) {
      const bits = data[1] | (data[2] << 8) | (data[3] << 16) | (data[4] << 24);
      setDimensions(target, (bits & 0x3fff) + 1, ((bits >> 14) & 0x3fff) + 1);
    } else if (type === "EXIF") {
      const exif = parseTiff(stripExifHeader(data));
      if (exif) applyExif(target, exif);
    } else if (type === "XMP ") {
      xmp = utf8(data);
    }
    pos += 8 + length + (length & 1);
  }
  if (xmp) applyXmp(target, xmp);
}

type Box = { type: string; start: number; end: number; body: number };

function* boxes(bytes: Uint8Array, start: number, end: number): Generator<Box> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let pos = start;
  while (pos + 8 <= end) {
    let size = view.getUint32(pos);
    const type = ascii(bytes, pos + 4, 4);
    let header = 8;
    if (size === 1 && pos + 16 <= end) {
      size = Number(view.getBigUint64(pos + 8));
      header = 16;
    } else if (size === 0) size = end - pos;
    if (size < header || pos + size > end) return;
    yield { type, start: pos, end: pos + size, body: pos + header };
    pos += size;
  }
}

function readUint(view: DataView, offset: number, size: number): number {
  if (size === 0) return 0;
  if (size === 2) return view.getUint16(offset);
  if (size === 4) return view.getUint32(offset);
  if (size === 8) return Number(view.getBigUint64(offset));
  return 0;
}

function parseHeic(bytes: Uint8Array, target: ParsedImageMetadata): void {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const meta = [...boxes(bytes, 0, bytes.length)].find((box) => box.type === "meta");
  if (!meta) return;
  const children = [...boxes(bytes, meta.body + 4, meta.end)]; // FullBox: 4 Byte Version/Flags
  let exifItem: number | undefined;
  const iinf = children.find((box) => box.type === "iinf");
  if (iinf) {
    const version = bytes[iinf.body];
    const entriesStart = iinf.body + 4 + (version === 0 ? 2 : 4);
    for (const infe of boxes(bytes, entriesStart, iinf.end)) {
      if (infe.type !== "infe") continue;
      const infeVersion = bytes[infe.body];
      if (infeVersion < 2) continue;
      const idSize = infeVersion === 2 ? 2 : 4;
      const itemId = readUint(view, infe.body + 4, idSize);
      const itemType = ascii(bytes, infe.body + 4 + idSize + 2, 4);
      if (itemType === "Exif") exifItem = itemId;
    }
  }
  const ispe = children.find((box) => box.type === "iprp");
  if (ispe) {
    for (const ipco of boxes(bytes, ispe.body, ispe.end)) {
      if (ipco.type !== "ipco") continue;
      // Grösste ispe-Angabe = Hauptbild (Vorschaubilder sind kleiner).
      let best: [number, number] | undefined;
      for (const property of boxes(bytes, ipco.body, ipco.end)) {
        if (property.type !== "ispe" || property.body + 12 > property.end) continue;
        const size: [number, number] = [view.getUint32(property.body + 4), view.getUint32(property.body + 8)];
        if (!best || size[0] * size[1] > best[0] * best[1]) best = size;
      }
      if (best) setDimensions(target, best[0], best[1]);
    }
  }
  const iloc = children.find((box) => box.type === "iloc");
  if (exifItem === undefined || !iloc) return;
  const version = bytes[iloc.body];
  let pos = iloc.body + 4;
  const offsetSize = bytes[pos] >> 4;
  const lengthSize = bytes[pos] & 0x0f;
  const baseOffsetSize = bytes[pos + 1] >> 4;
  const indexSize = version === 1 || version === 2 ? bytes[pos + 1] & 0x0f : 0;
  pos += 2;
  const itemCount = version < 2 ? view.getUint16(pos) : view.getUint32(pos);
  pos += version < 2 ? 2 : 4;
  for (let i = 0; i < itemCount && pos < iloc.end; i++) {
    const itemId = version < 2 ? view.getUint16(pos) : view.getUint32(pos);
    pos += version < 2 ? 2 : 4;
    let constructionMethod = 0;
    if (version === 1 || version === 2) {
      constructionMethod = view.getUint16(pos) & 0x0f;
      pos += 2;
    }
    pos += 2; // data_reference_index
    const baseOffset = readUint(view, pos, baseOffsetSize);
    pos += baseOffsetSize;
    const extentCount = view.getUint16(pos);
    pos += 2;
    let extentOffset = 0;
    let extentLength = 0;
    for (let e = 0; e < extentCount; e++) {
      pos += indexSize;
      const offset = readUint(view, pos, offsetSize);
      pos += offsetSize;
      const length = readUint(view, pos, lengthSize);
      pos += lengthSize;
      if (e === 0) { extentOffset = offset; extentLength = length; }
    }
    if (itemId !== exifItem || constructionMethod !== 0) continue;
    const start = baseOffset + extentOffset;
    const end = extentLength ? start + extentLength : bytes.length;
    if (start + 4 > bytes.length) return;
    // Exif-Item: 4 Byte Offset bis zum TIFF-Header, danach (optional "Exif\0\0") TIFF.
    const headerOffset = view.getUint32(start);
    const tiff = stripExifHeader(bytes.subarray(start + 4 + headerOffset, Math.min(end, bytes.length)));
    const data = parseTiff(tiff);
    if (data) applyExif(target, data);
    return;
  }
}

export function parseImageMetadata(bytes: Uint8Array, format: ImageFormat): ParsedImageMetadata {
  const target: ParsedImageMetadata = {};
  if (format === "jpeg") parseJpeg(bytes, target);
  else if (format === "png") parsePng(bytes, target);
  else if (format === "webp") parseWebp(bytes, target);
  else if (format === "heic") parseHeic(bytes, target);
  else if (format === "tiff") {
    const data = parseTiff(bytes);
    if (data) applyExif(target, data);
  }
  return target;
}
