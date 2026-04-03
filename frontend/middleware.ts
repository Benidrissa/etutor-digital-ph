import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";
import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

function parseJwtRole(token: string): string | null {
  try {
    const base64Url = token.split(".")[1];
    if (!base64Url) return null;
    const base64 = base64Url.replace(/-/g, "+").replace(/_/g, "/");
    const payload = JSON.parse(atob(base64)) as Record<string, unknown>;
    return typeof payload?.role === "string" ? payload.role : null;
  } catch {
    return null;
  }
}

export default function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Redirect /settings to /profile (with locale support)
  if (pathname === "/settings") {
    return NextResponse.redirect(new URL("/profile", request.url));
  }

  // Handle locale-aware /settings redirect
  if (pathname === "/fr/settings" || pathname === "/en/settings") {
    const locale = pathname.split("/")[1];
    return NextResponse.redirect(new URL(`/${locale}/profile`, request.url));
  }

  // Protect /*/admin/* routes — redirect non-admin/expert users to dashboard
  const adminPattern = /^\/(fr|en)\/admin(\/.*)?$/;
  if (adminPattern.test(pathname)) {
    const locale = pathname.split("/")[1];
    const authHeader = request.headers.get("authorization");
    let role: string | null = null;

    if (authHeader?.startsWith("Bearer ")) {
      role = parseJwtRole(authHeader.slice(7));
    }

    if (role !== "admin" && role !== "expert") {
      return NextResponse.redirect(new URL(`/${locale}/dashboard`, request.url));
    }
  }

  return intlMiddleware(request);
}

export const config = {
  matcher: ["/", "/(fr|en)/:path*"],
};
