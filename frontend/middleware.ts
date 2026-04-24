import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";
import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

const PUBLIC_PATTERNS = [
  /^\/$/,
  /^\/(fr|en)$/,
  /^\/(fr|en)\/(login|register|register-options|register-totp|register-email-otp|register-password|magic-link|forgot-password)(\/.*)*/,
  /^\/(fr|en)\/courses(\/[^/]+)?$/,
  /^\/(fr|en)\/about$/,
  /^\/(fr|en)\/verify\/[^/]+$/,
  /^\/api\//,
  /^\/_next\//,
  /^\/favicon\.ico$/,
  /^\/manifest\.json$/,
  /^\/icon-.*\.(svg|png)$/,
  /^\/sw\.js$/,
  /^\/offline\.html$/,
  /^\/manifest\.webmanifest$/,
  /^\/.well-known\//,
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATTERNS.some((pattern) => pattern.test(pathname));
}

function hasSession(request: NextRequest): boolean {
  if (request.cookies.get("access_token")?.value) return true;

  const auth = request.headers.get("authorization");
  if (auth?.startsWith("Bearer ")) return true;

  // Refresh token cookie (HttpOnly, ~90 days) is sufficient evidence of an
  // authenticated session — client-side authClient will exchange it for a new
  // access_token via /api/v1/auth/refresh on the first 401. Without this, the
  // 15-minute access_token cookie expires and SSR redirects to /login on every
  // page load, defeating the long-lived refresh token.
  if (request.cookies.get("refresh_token")?.value) return true;

  return false;
}

export default function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Auth-aware root redirect: authenticated → /dashboard, anonymous → /courses
  const localeRootMatch = pathname.match(/^\/(fr|en)$/);
  if (localeRootMatch || pathname === "/") {
    const locale = localeRootMatch ? localeRootMatch[1] : "fr";
    const dest = hasSession(request) ? `/${locale}/dashboard` : `/${locale}/courses`;
    return NextResponse.redirect(new URL(dest, request.url));
  }

  if (pathname === "/settings") {
    return NextResponse.redirect(new URL("/profile", request.url));
  }
  if (pathname === "/fr/settings" || pathname === "/en/settings") {
    const locale = pathname.split("/")[1];
    return NextResponse.redirect(new URL(`/${locale}/profile`, request.url));
  }

  if (!isPublicPath(pathname) && !hasSession(request)) {
    const locale = pathname.split("/")[1];
    const validLocale = ["fr", "en"].includes(locale) ? locale : "fr";
    const loginUrl = new URL(`/${validLocale}/login`, request.url);
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  // API routes are proxied by next.config.ts rewrites — skip i18n middleware.
  if (pathname.startsWith("/api/")) {
    return NextResponse.next();
  }

  return intlMiddleware(request);
}

export const config = {
  matcher: ["/", "/(fr|en)/:path*", "/((?!_next|favicon.ico|manifest.webmanifest|icon-|sw.js|offline\\.html|.well-known|api/|.*\\.(?:png|jpg|jpeg|gif|webp|ico|pdf)).*)"],
};
