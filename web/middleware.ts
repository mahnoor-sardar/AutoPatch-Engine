import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

function isWebhookPath(pathname: string): boolean {
  return (
    pathname === "/v1/github/webhook" ||
    pathname.startsWith("/v1/webhooks/")
  );
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (!pathname.startsWith("/v1/") || isWebhookPath(pathname)) {
    return NextResponse.next();
  }
  const apiKey = process.env.API_KEY;
  if (!apiKey) {
    return NextResponse.next();
  }
  const headers = new Headers(request.headers);
  headers.set("X-API-Key", apiKey);
  return NextResponse.next({ request: { headers } });
}

export const config = {
  matcher: ["/v1/:path*"],
};
