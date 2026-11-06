/** Parse FastAPI HTTPException JSON `{ "detail": ... }` from response body. */
export function parseFastApiErrorBody(text: string): string {
  let message = text || "Request failed";
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (parsed.detail === undefined) {
      return message;
    }
    const d = parsed.detail;
    if (typeof d === "string") {
      message = d;
    } else if (d !== null && typeof d === "object") {
      if (
        "errors" in d &&
        Array.isArray((d as { errors: unknown }).errors)
      ) {
        message = (d as { errors: string[] }).errors.join("; ");
      } else if ("msg" in d && typeof (d as { msg: unknown }).msg === "string") {
        message = (d as { msg: string }).msg;
      } else {
        message = JSON.stringify(d);
      }
    }
  } catch {
    /* keep message */
  }
  return message;
}
