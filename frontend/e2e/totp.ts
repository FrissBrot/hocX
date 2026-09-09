import crypto from "node:crypto";

// Minimal RFC 6238 TOTP code generator, mirroring backend/app/core/totp.py exactly
// (SHA1, 6 digits, 30s step, base32 secret) so e2e tests can complete TOTP enrollment
// for accounts that require MFA - see mfa_service.py's user_requires_mfa(): any user
// with an admin role in any tenant.

const BASE32_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

function decodeBase32(secret: string): Buffer {
  const cleaned = secret.toUpperCase().replace(/=+$/, "");
  let bits = "";
  for (const char of cleaned) {
    const value = BASE32_ALPHABET.indexOf(char);
    if (value === -1) throw new Error(`Invalid base32 character in TOTP secret: ${char}`);
    bits += value.toString(2).padStart(5, "0");
  }
  const bytes: number[] = [];
  for (let i = 0; i + 8 <= bits.length; i += 8) {
    bytes.push(parseInt(bits.slice(i, i + 8), 2));
  }
  return Buffer.from(bytes);
}

export function totpCounter(now: number = Date.now()): number {
  return Math.floor(now / 1000 / 30);
}

export function currentTotpCode(secret: string, now: number = Date.now()): string {
  const counterBuffer = Buffer.alloc(8);
  counterBuffer.writeBigUInt64BE(BigInt(totpCounter(now)));
  const digest = crypto.createHmac("sha1", decodeBase32(secret)).update(counterBuffer).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const codeInt =
    (((digest[offset] & 0x7f) << 24) |
      ((digest[offset + 1] & 0xff) << 16) |
      ((digest[offset + 2] & 0xff) << 8) |
      (digest[offset + 3] & 0xff)) >>>
    0;
  return String(codeInt % 1_000_000).padStart(6, "0");
}

// mfa_service.py rejects a verification code from the same (or an earlier) 30s counter
// as the one already consumed for this factor (anti-replay: UserMfaFactor.totp_last_counter),
// so a login that immediately follows this account's own TOTP enrolment needs a code from
// a *later* window - waits out whatever's left of the current one, plus a small buffer for
// clock/request skew, rather than producing a code doomed to be rejected.
export async function waitForNextTotpWindow(afterCounter: number, stepSeconds = 30): Promise<void> {
  while (totpCounter(Date.now()) <= afterCounter) {
    const msIntoStep = Date.now() % (stepSeconds * 1000);
    const msRemaining = stepSeconds * 1000 - msIntoStep + 250;
    await new Promise((resolve) => setTimeout(resolve, msRemaining));
  }
}
