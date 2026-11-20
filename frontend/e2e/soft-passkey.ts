import crypto from "node:crypto";
import fs from "node:fs/promises";

// Software-Passkey für die API-Anmeldung der Plattform-Admins in auth.setup.ts: Admins melden sich
// nur noch mit Passwort + Passkey an (backend admin_mfa_service.py). Im Browser übernimmt das der
// virtuelle CDP-Authenticator (webauthn.ts); für reine API-Kontexte erzeugt diese Klasse echte
// WebAuthn-Antworten (Attestation «none», ECDSA P-256), die das Backend vollständig prüft.
// Gegenstück zu backend/tests/soft_passkey.py.

function b64url(data: Buffer | Uint8Array): string {
  return Buffer.from(data).toString("base64url");
}

function head(major: number, value: number): Buffer {
  if (value < 24) return Buffer.from([(major << 5) | value]);
  if (value < 256) return Buffer.from([(major << 5) | 24, value]);
  const out = Buffer.alloc(3);
  out[0] = (major << 5) | 25;
  out.writeUInt16BE(value, 1);
  return out;
}

type CborValue = number | string | Buffer | Map<CborValue, CborValue>;

function cbor(value: CborValue): Buffer {
  if (typeof value === "number") return value >= 0 ? head(0, value) : head(1, -1 - value);
  if (typeof value === "string") {
    const raw = Buffer.from(value, "utf8");
    return Buffer.concat([head(3, raw.length), raw]);
  }
  if (Buffer.isBuffer(value)) return Buffer.concat([head(2, value.length), value]);
  const parts = [head(5, value.size)];
  for (const [key, entry] of value) parts.push(cbor(key), cbor(entry));
  return Buffer.concat(parts);
}

const FLAGS_UP_UV = 0x01 | 0x04;
const FLAG_AT = 0x40;

type StoredPasskey = { privateKeyPem: string; credentialId: string; signCount: number };

export class SoftPasskey {
  private readonly privateKey: crypto.KeyObject;
  readonly credentialId: Buffer;
  private signCount: number;

  private constructor(privateKey: crypto.KeyObject, credentialId: Buffer, signCount: number) {
    this.privateKey = privateKey;
    this.credentialId = credentialId;
    this.signCount = signCount;
  }

  static create(): SoftPasskey {
    const { privateKey } = crypto.generateKeyPairSync("ec", { namedCurve: "P-256" });
    return new SoftPasskey(privateKey, crypto.randomBytes(16), 0);
  }

  static async load(file: string): Promise<SoftPasskey | null> {
    try {
      const stored = JSON.parse(await fs.readFile(file, "utf8")) as StoredPasskey;
      return new SoftPasskey(crypto.createPrivateKey(stored.privateKeyPem), Buffer.from(stored.credentialId, "base64url"), stored.signCount);
    } catch {
      return null;
    }
  }

  async save(file: string): Promise<void> {
    const stored: StoredPasskey = {
      privateKeyPem: this.privateKey.export({ type: "pkcs8", format: "pem" }).toString(),
      credentialId: b64url(this.credentialId),
      signCount: this.signCount,
    };
    await fs.writeFile(file, JSON.stringify(stored), { mode: 0o600 });
  }

  private clientData(type: string, challenge: string, origin: string): Buffer {
    return Buffer.from(JSON.stringify({ type, challenge, origin, crossOrigin: false }), "utf8");
  }

  private rpIdHash(rpId: string): Buffer {
    return crypto.createHash("sha256").update(rpId).digest();
  }

  registration(publicKey: Record<string, unknown>, origin: string) {
    const options = publicKey as { challenge: string; rp: { id: string } };
    const jwk = crypto.createPublicKey(this.privateKey).export({ format: "jwk" }) as { x: string; y: string };
    const coseKey = cbor(new Map<CborValue, CborValue>([
      [1, 2], [3, -7], [-1, 1], [-2, Buffer.from(jwk.x, "base64url")], [-3, Buffer.from(jwk.y, "base64url")],
    ]));
    const idLength = Buffer.alloc(2);
    idLength.writeUInt16BE(this.credentialId.length);
    const counter = Buffer.alloc(4);
    counter.writeUInt32BE(this.signCount);
    const authData = Buffer.concat([
      this.rpIdHash(options.rp.id), Buffer.from([FLAGS_UP_UV | FLAG_AT]), counter, Buffer.alloc(16), idLength, this.credentialId, coseKey,
    ]);
    const attestation = cbor(new Map<CborValue, CborValue>([["fmt", "none"], ["attStmt", new Map()], ["authData", authData]]));
    return {
      id: b64url(this.credentialId),
      rawId: b64url(this.credentialId),
      type: "public-key",
      response: {
        clientDataJSON: b64url(this.clientData("webauthn.create", options.challenge, origin)),
        attestationObject: b64url(attestation),
        transports: ["internal"],
      },
    };
  }

  assertion(publicKey: Record<string, unknown>, origin: string) {
    const options = publicKey as { challenge: string; rpId: string };
    this.signCount += 1;
    const counter = Buffer.alloc(4);
    counter.writeUInt32BE(this.signCount);
    const authData = Buffer.concat([this.rpIdHash(options.rpId), Buffer.from([FLAGS_UP_UV]), counter]);
    const clientData = this.clientData("webauthn.get", options.challenge, origin);
    const signature = crypto.sign("sha256", Buffer.concat([authData, crypto.createHash("sha256").update(clientData).digest()]), this.privateKey);
    return {
      id: b64url(this.credentialId),
      rawId: b64url(this.credentialId),
      type: "public-key",
      response: {
        clientDataJSON: b64url(clientData),
        authenticatorData: b64url(authData),
        signature: b64url(signature),
        userHandle: null,
      },
    };
  }
}

// Passkey-Bestätigung (Step-up) für eine Admin-API-Anfrage aus einem API-Kontext (backend
// app/core/admin_step_up.py): Zweck, Methode, Pfad und SHA-256 des Bodys.
export async function stepUpHeaders(
  context: { post: (url: string, options: { data: unknown }) => Promise<{ ok(): boolean; text(): Promise<string>; json(): Promise<any> }> },
  passkey: SoftPasskey,
  origin: string,
  purpose: string,
  method: string,
  path: string,
  body = ""
): Promise<Record<string, string>> {
  const bodySha256 = crypto.createHash("sha256").update(body).digest("hex");
  const start = await context.post("/api/admin/mfa/step-up/start", { data: { purpose, method, path, body_sha256: bodySha256 } });
  if (!start.ok()) throw new Error(`step-up start: ${await start.text()}`);
  const { flow_token, public_key } = await start.json();
  const proof = JSON.stringify({ flow_token, credential: passkey.assertion(public_key, origin) });
  return { "X-Hocx-Step-Up": Buffer.from(proof).toString("base64url") };
}
