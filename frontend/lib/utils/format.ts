const APP_TIME_ZONE = "Europe/Zurich";

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
