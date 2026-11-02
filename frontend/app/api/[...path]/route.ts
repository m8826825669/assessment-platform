import { NextRequest } from "next/server";
export const dynamic = "force-dynamic";
// Fixed operator-configured upstream; never accept a browser-provided destination.
async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  if (path[0] !== "v1" || path.some((p) => !/^[a-zA-Z0-9_-]+$/.test(p)))
    return new Response(null, { status: 404 });
  const base = new URL(
    process.env.ASSESSMENT_API_ORIGIN ?? "http://127.0.0.1:8000",
  );
  if (
    !["http:", "https:"].includes(base.protocol) ||
    base.username ||
    base.password ||
    base.pathname !== "/" ||
    base.search ||
    base.hash
  )
    return new Response(null, { status: 503 });
  const headers = new Headers();
  for (const name of ["authorization", "content-type", "idempotency-key"]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const isBody = !["GET", "HEAD"].includes(request.method);
  const limit = path.includes("media") ? 8 * 1024 * 1024 : 2 * 1024 * 1024;
  const reader = isBody ? request.body?.getReader() : null;
  const chunks: Uint8Array[] = [];
  let size = 0;
  if (reader) {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > limit) {
        await reader.cancel();
        return Response.json({ code: "body_too_large" }, { status: 413 });
      }
      chunks.push(value);
    }
  }
  const body = isBody ? new Uint8Array(size) : undefined;
  let offset = 0;
  for (const chunk of chunks) {
    body!.set(chunk, offset);
    offset += chunk.length;
  }
  try {
    const upstream = await fetch(
      new URL("api/" + path.join("/") + request.nextUrl.search, base),
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(120000),
      },
    );
    const outgoing = new Headers({
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    });
    for (const name of [
      "content-type",
      "content-disposition",
      "x-request-id",
    ]) {
      const value = upstream.headers.get(name);
      if (value) outgoing.set(name, value);
    }
    return new Response(upstream.body, {
      status: upstream.status,
      headers: outgoing,
    });
  } catch {
    return Response.json(
      { code: "upstream_unavailable" },
      { status: 503, headers: { "Cache-Control": "no-store" } },
    );
  }
}
export { proxy as GET, proxy as POST, proxy as PUT, proxy as PATCH };
