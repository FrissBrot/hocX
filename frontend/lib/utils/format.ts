const APP_TIME_ZONE = "Europe/Zurich";
const ISO_DATE_PATTERN = /^(\d{4})-(\d{2})-(\d{2})$/;
const DISPLAY_DATE_PATTERN = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/;

function isValidIsoDateParts(year: number, month: number, day: number) {
  if (!Number.isInteger(year) || !Number.isInteger(month) || !Number.isInteger(day)) {
    return false;
  }
  if (month < 1 || month > 12 || day < 1 || day > 31) {
    return false;
  }
  const parsed = new Date(Date.UTC(year, month - 1, day));
  return (
    parsed.getUTCFullYear() === year &&
    parsed.getUTCMonth() === month - 1 &&
    parsed.getUTCDate() === day
  );
}

export function parseDateInputValue(input: string | null | undefined) {
  const trimmed = String(input ?? "").trim();
  if (!trimmed) {
    return "";
  }

  const isoMatch = trimmed.match(ISO_DATE_PATTERN);
  if (isoMatch) {
    const [, year, month, day] = isoMatch;
    return isValidIsoDateParts(Number(year), Number(month), Number(day)) ? trimmed : null;
  }

  const displayMatch = trimmed.match(DISPLAY_DATE_PATTERN);
  if (!displayMatch) {
    return null;
  }

  const [, day, month, year] = displayMatch;
  const normalizedDay = day.padStart(2, "0");
  const normalizedMonth = month.padStart(2, "0");
  const isoValue = `${year}-${normalizedMonth}-${normalizedDay}`;
  return isValidIsoDateParts(Number(year), Number(normalizedMonth), Number(normalizedDay)) ? isoValue : null;
}

export function formatDateInputValue(input: string | null | undefined) {
  const normalized = parseDateInputValue(input);
  return normalized ? formatDate(normalized) : "";
}

export function formatDate(input: string | null | undefined) {
  if (!input) {
    return "";
  }

  const [datePart] = input.split("T");
  const [year, month, day] = datePart.split("-");
  if (year && month && day) {
    return `${day}.${month}.${year}`;
  }

  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) {
    return input;
  }

  return new Intl.DateTimeFormat("de-CH", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: APP_TIME_ZONE,
  }).format(parsed);
}

export function formatDateRange(start: string | null | undefined, end?: string | null | undefined) {
  const formattedStart = formatDate(start);
  const formattedEnd = formatDate(end);
  if (!formattedStart) {
    return "";
  }
  if (!formattedEnd || formattedEnd === formattedStart) {
    return formattedStart;
  }
  return `${formattedStart} - ${formattedEnd}`;
}

export function formatDateTime(input: string | null | undefined) {
  if (!input) {
    return "";
  }

  const parsed = new Date(input);
  if (Number.isNaN(parsed.getTime())) {
    return formatDate(input);
  }

  return new Intl.DateTimeFormat("de-CH", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
    timeZone: APP_TIME_ZONE,
  }).format(parsed);
}
