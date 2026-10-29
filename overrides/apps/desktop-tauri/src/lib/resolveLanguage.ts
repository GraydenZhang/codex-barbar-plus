/** Resolve the two supported UI languages, including the operating-system choice. */
export function resolveLanguage(language: string): "zh-CN" | "en-US" {
  const requested = language === "system"
    ? (typeof navigator === "undefined" ? "en-US" : navigator.language)
    : language;
  return requested?.toLowerCase().startsWith("zh") ? "zh-CN" : "en-US";
}
