/**
 * frontend/modules/utils.js
 *
 * Purpose:
 * Shared utility helpers for the Inferno Earnings Throne. This is the small forge
 * where number shaping, date formatting, and reusable math are kept pure so the
 * heavier game systems can stay focused on strategy instead of boilerplate.
 */

/**
 * Clamp a numeric value into a safe range.
 *
 * @param {number} value - The raw numeric input.
 * @param {number} min - The minimum allowed value.
 * @param {number} max - The maximum allowed value.
 * @returns {number} The bounded numeric value.
 */
export function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

/**
 * Format a numeric value to a fixed number of decimal places.
 *
 * We keep the historical name `round` for backward compatibility with the
 * existing dashboard code, even though it returns a formatted string.
 *
 * @param {number} value - The value to format.
 * @param {number} [places=1] - Number of decimal places to keep.
 * @returns {string} A fixed-width decimal string.
 */
export function round(value, places = 1) {
  return Number.parseFloat(value).toFixed(places);
}

/**
 * Format a USD value for the detail and desk views.
 *
 * @param {number} value - Raw numeric price.
 * @returns {string} Currency-formatted value.
 */
export function formatCurrency(value) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Format a tracker date string into a consistent UI date.
 *
 * The noon timestamp avoids timezone drift pushing the rendered date back a day
 * on clients west of UTC.
 *
 * @param {string} value - ISO-like date string.
 * @returns {string} Human-readable date.
 */
export function formatDate(value) {
  const date = new Date(`${value}T12:00:00`);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

/**
 * Format backend timestamps from files or APIs into a short status label.
 *
 * @param {number|string|null|undefined} value - Unix timestamp seconds, ISO string,
 * or missing value.
 * @returns {string} Friendly timestamp label.
 */
export function formatBackendDate(value) {
  if (!value) {
    return "Never";
  }

  const date = typeof value === "number" ? new Date(value * 1000) : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }

  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(date);
}
