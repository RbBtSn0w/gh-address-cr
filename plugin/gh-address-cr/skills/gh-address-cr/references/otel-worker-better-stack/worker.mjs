export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/healthz") {
      return new Response(JSON.stringify({ status: "ok" }), {
        headers: { "Content-Type": "application/json" },
      });
    }

    if (request.method !== "POST" || url.pathname !== "/v1/logs") {
      return new Response("Not found", { status: 404 });
    }

    const upstreamHeaders = new Headers({
      Authorization: `Bearer ${env.SOURCE_TOKEN}`,
      "Content-Type": request.headers.get("content-type") || "application/json",
    });

    const contentEncoding = request.headers.get("content-encoding");
    if (contentEncoding) {
      upstreamHeaders.set("Content-Encoding", contentEncoding);
    }

    const acceptEncoding = request.headers.get("accept-encoding");
    if (acceptEncoding) {
      upstreamHeaders.set("Accept-Encoding", acceptEncoding);
    }

    const upstream = await fetch(`https://${env.INGESTING_HOST}/v1/logs`, {
      method: "POST",
      headers: upstreamHeaders,
      body: request.body,
    });

    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: {
        "Content-Type": upstream.headers.get("Content-Type") || "application/json",
      },
    });
  },
};
