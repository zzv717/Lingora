/** Same-origin API proxy. BACKEND_URL is read at runtime, not during next build. */
export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const hopByHop = [
  "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
  "te", "trailer", "transfer-encoding", "upgrade",
];

function cleanHeaders(headers: Headers): Headers {
  const result = new Headers(headers);
  // Connection may nominate additional hop-by-hop headers.
  for (const name of (headers.get("connection") || "").split(",")) {
    if (name.trim()) result.delete(name.trim());
  }
  for (const name of hopByHop) result.delete(name);
  return result;
}

async function proxy(request: Request, { params }: { params: { path: string[] } }) {
  const backend = (process.env.BACKEND_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
  const url = `${backend}/${params.path.map(encodeURIComponent).join("/")}${new URL(request.url).search}`;
  const headers = cleanHeaders(request.headers);
  headers.delete("host");
  headers.delete("content-length");

  try {
    const hasBody = request.method !== "GET" && request.method !== "HEAD" && request.body !== null;
    const options: RequestInit & { duplex?: "half" } = {
      method: request.method,
      headers,
      redirect: "manual",
      signal: request.signal,
      ...(hasBody ? { body: request.body, duplex: "half" as const } : {}),
    };
    const upstream = await fetch(url, options);
    const responseHeaders = cleanHeaders(upstream.headers);
    // Node fetch decompresses the body, so these original headers are no longer valid.
    if (responseHeaders.has("content-encoding")) {
      responseHeaders.delete("content-encoding");
      responseHeaders.delete("content-length");
    }
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: responseHeaders,
    });
  } catch (error) {
    console.error("Backend proxy error:", error);
    return Response.json(
      { error: { code: "BACKEND_UNAVAILABLE", message_uz: "Serverga ulanib bo'lmadi. Keyinroq urinib ko'ring." } },
      { status: 502 },
    );
  }
}

export { proxy as GET, proxy as HEAD, proxy as POST, proxy as PUT, proxy as PATCH, proxy as DELETE, proxy as OPTIONS };
