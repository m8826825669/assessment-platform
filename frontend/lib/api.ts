export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    public requestId: string,
    public locations: string[] = [],
  ) {
    super(
      code === "invalid_credentials"
        ? "Invalid email or password."
        : code === "review_self"
          ? "An independent reviewer is required. Authors and submitters cannot approve their own work."
          : status === 409
            ? "This record changed or conflicts with the current state. Reload and review before retrying."
            : status === 401
              ? "Your session ended. Sign in again."
              : status === 403
                ? "Your current role cannot perform this action."
                : status === 422
                  ? "Check the fields below. Your work has been retained."
                  : status === 413
                    ? "The file exceeds the allowed size."
                    : status === 503
                      ? "A required service is unavailable. Keep your work and retry later."
                      : "The request could not be completed. Keep your work and try again.",
    );
  }
}
export async function request<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/${path}`, {
      ...init,
      cache: "no-store",
      credentials: "omit",
      headers: {
        ...(init.body && typeof init.body === "string"
          ? { "Content-Type": "application/json" }
          : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init.headers,
      },
    });
  } catch {
    throw new Error(
      "Connection interrupted. Your work is retained. For an import, retry with the same key.",
    );
  }
  if (!response.ok) {
    let problem: {
      code?: string;
      request_id?: string;
      errors?: { location?: unknown[] }[];
    } = {};
    try {
      problem = await response.json();
    } catch {}
    const locations = (problem.errors ?? [])
      .slice(0, 100)
      .map((e) =>
        (e.location ?? [])
          .filter(
            (x) =>
              typeof x === "number" ||
              (typeof x === "string" && /^[a-z_]{1,40}$/.test(x)),
          )
          .join(" → "),
      );
    throw new ApiError(
      response.status,
      problem.code ?? "request_failed",
      problem.request_id ?? response.headers.get("x-request-id") ?? "",
      locations,
    );
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}
export async function imageBytes(
  path: string,
  token: string,
  signal: AbortSignal,
) {
  const response = await fetch(`/api/v1/${path}`, {
    cache: "no-store",
    credentials: "omit",
    headers: { Authorization: `Bearer ${token}` },
    signal,
  });
  if (!response.ok) throw new Error("Protected image unavailable");
  const type = response.headers.get("content-type")?.split(";")[0];
  if (type !== "image/png" && type !== "image/jpeg")
    throw new Error("Unsupported image");
  return response.blob();
}
