// Proxy ke API backend. Browser cukup memanggil /api/... di origin yang sama,
// jadi alamat API dibaca saat runtime (API_INTERNAL_URL) dan tidak perlu CORS.
import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";

const API = (process.env.API_INTERNAL_URL || "http://localhost:8000").replace(/\/$/, "");
// x-forwarded-for: alamat klien asli dari ingress, untuk log audit dan batas percobaan login.
// API hanya mempercayainya dari web/ingress (uvicorn --proxy-headers + NetworkPolicy).
const PASS_REQUEST = ["authorization", "content-type", "accept", "x-request-id", "x-forwarded-for"];
const PASS_RESPONSE = ["content-type", "content-disposition", "cache-control", "retry-after", "x-request-id"];

async function forward(req: NextRequest, ctx: { params: Promise<{ path: string[] }> }) {
  const { path } = await ctx.params;
  const url = `${API}/${path.map(encodeURIComponent).join("/")}${req.nextUrl.search}`;
  const headers = new Headers();
  for (const h of PASS_REQUEST) {
    const v = req.headers.get(h);
    if (v) headers.set(h, v);
  }
  const hasBody = !["GET", "HEAD"].includes(req.method);
  let upstream: Response;
  try {
    upstream = await fetch(url, {
      method: req.method,
      headers,
      body: hasBody ? await req.arrayBuffer() : undefined,
      cache: "no-store",
    });
  } catch {
    return Response.json({ detail: "API tidak bisa dihubungi" }, { status: 502 });
  }
  const out = new Headers();
  for (const h of PASS_RESPONSE) {
    const v = upstream.headers.get(h);
    if (v) out.set(h, v);
  }
  return new Response(upstream.body, { status: upstream.status, headers: out });
}

export { forward as GET, forward as POST, forward as PUT, forward as PATCH, forward as DELETE };
