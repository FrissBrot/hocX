/**
 * Passwortregel für neue Passwörter (Einladung, Passwort vergessen) - Live-Anzeige.
 *
 * Gleiche Regel wie im Backend `backend/app/core/password_policy.py`, das sie beim Speichern
 * erzwingt; beide Seiten prüfen dieselben Beispiele (`password-strength.test.ts` bzw.
 * `tests/test_password_policy.py`). Wer sie ändert, ändert beide Dateien und beide Tests.
 *
 * Mindestens 12 Zeichen (Pflicht) und mindestens Stufe «Mittel» (2 von 4). Name, E-Mail,
 * Organisation, häufige Wörter und dreimal dasselbe Zeichen deckeln auf «Schwach».
 */

export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MIN_SCORE = 2;

// Häufige Wörter und Muster (klein geschrieben, als Teilstring geprüft). Gleiche Liste wie im Backend.
export const COMMON_PASSWORD_WORDS: readonly string[] = [
  "passwort", "password", "kennwort", "hocx", "qwertz", "qwerty", "asdf", "yxcv",
  "123456", "654321", "abc123", "abcdef", "letmein", "welcome", "willkommen", "hallo",
  "admin", "login", "geheim", "secret", "sommer", "winter", "fruehling", "herbst",
  "iloveyou", "schatz", "fussball", "football", "schweiz", "verein",
  // Häufigste Grundwörter aus öffentlich bekannten Passwortlisten (offline) und Tastaturfolgen
  "qwertzuiop", "qwertyuiop", "asdfghjkl", "zxcvbnm", "1q2w3e", "q1w2e3", "112233", "121212",
  "dragon", "monkey", "master", "sunshine", "princess", "shadow", "superman", "batman", "trustno1",
  "starwars", "baseball", "hockey", "liebe", "schalke", "bayern", "hallo123", "changeme", "zugang",
  "startpass", "default", "computer", "internet", "michael", "andrea", "daniel", "thomas",
];

// Ersetzungen aus Passwortlisten (p@ssw0rd = password), gleiche Tabelle wie im Backend
const LEET: Readonly<Record<string, string>> = { "4": "a", "@": "a", "3": "e", "1": "i", "!": "i", "0": "o", "5": "s", "$": "s", "7": "t" };
export const SEQUENCE_LENGTH = 5;

function isAlnum(char: string): boolean {
  return /^[\p{L}\p{N}]$/u.test(char);
}

/** Auf- oder absteigende Folge ab `length` Zeichen (12345, abcde, 98765) - wie has_sequence im Backend. */
export function hasSequence(value: string, length = SEQUENCE_LENGTH): boolean {
  const chars = Array.from(value);
  let run = 1;
  let direction = 0;
  for (let index = 1; index < chars.length; index++) {
    const previous = chars[index - 1];
    const current = chars[index];
    const step = (current.codePointAt(0) ?? 0) - (previous.codePointAt(0) ?? 0);
    const alnum = isAlnum(current) && isAlnum(previous);
    if ((step === 1 || step === -1) && alnum && (direction === 0 || direction === step)) {
      run += 1;
      direction = step;
      if (run >= length) return true;
    } else {
      run = (step === 1 || step === -1) && alnum ? 2 : 1;
      direction = run === 2 ? step : 0;
    }
  }
  return false;
}

const SPLIT = /[^a-z0-9äöüàâçéèêëîïôûùÿñ]+/;
const REPEAT = /(.)\1\1/su;

export type PasswordStrength = {
  length: number;
  classes: number;
  guessable: boolean;
  /** 0 (leer/zu kurz) … 4 */
  score: number;
  acceptable: boolean;
  checks: {
    minLength: boolean;
    mixedCase: boolean;
    numberOrSymbol: boolean;
    notGuessable: boolean;
  };
};

export type PasswordStrengthLevel = "empty" | "tooShort" | "weak" | "medium" | "strong" | "veryStrong";

/** Teile von Name, E-Mail und Organisation ab 3 Zeichen, klein geschrieben. */
export function personalTokens(values: ReadonlyArray<string | null | undefined>): string[] {
  const tokens = new Set<string>();
  for (const value of values) {
    if (!value) continue;
    let lowered = value.trim().toLowerCase();
    if (lowered.includes("@")) {
      const at = lowered.indexOf("@");
      const local = lowered.slice(0, at);
      const domain = lowered.slice(at + 1);
      lowered = `${local} ${domain.split(".")[0]}`;
    }
    for (const part of lowered.split(SPLIT)) {
      if (Array.from(part).length >= 3) tokens.add(part);
    }
  }
  return Array.from(tokens).sort();
}

export function evaluatePassword(password: string, personal: ReadonlyArray<string | null | undefined> = []): PasswordStrength {
  // Code-Punkte statt UTF-16-Einheiten zählen (wie len() in Python)
  const length = Array.from(password).length;
  const hasLower = /[a-z]/.test(password);
  const hasUpper = /[A-Z]/.test(password);
  const hasDigit = /[0-9]/.test(password);
  const hasSymbol = /[^A-Za-z0-9]/.test(password);
  const classes = [hasLower, hasUpper, hasDigit, hasSymbol].filter(Boolean).length;
  const lowered = password.toLowerCase();
  const unleet = Array.from(lowered).map((char) => LEET[char] ?? char).join("");
  const words = [...COMMON_PASSWORD_WORDS, ...personalTokens(personal)];
  const guessable = length > 0 && (
    words.some((word) => lowered.includes(word) || unleet.includes(word)) || REPEAT.test(password) || hasSequence(lowered)
  );
  let score = 0;
  if (length >= PASSWORD_MIN_LENGTH) {
    score = 1;
    if (length >= 16) score += 1;
    if (classes >= 3) score += 1;
    if (classes === 4 || length >= 20) score += 1;
    if (score === 1 && classes >= 2) score = 2;
    score = Math.min(score, 4);
    if (guessable) score = Math.min(score, 1);
  }
  return {
    length,
    classes,
    guessable,
    score,
    acceptable: length >= PASSWORD_MIN_LENGTH && score >= PASSWORD_MIN_SCORE,
    checks: {
      minLength: length >= PASSWORD_MIN_LENGTH,
      mixedCase: hasLower && hasUpper,
      numberOrSymbol: hasDigit || hasSymbol,
      notGuessable: length > 0 && !guessable,
    },
  };
}

export function passwordStrengthLevel(strength: PasswordStrength): PasswordStrengthLevel {
  if (strength.length === 0) return "empty";
  if (strength.length < PASSWORD_MIN_LENGTH) return "tooShort";
  return (["weak", "weak", "medium", "strong", "veryStrong"] as const)[strength.score];
}
