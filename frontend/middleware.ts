import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";
import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

const PUBLIC_PATTERNS = [
  /^\/$/,
  /^\/(fr|en)$/,
  /^\/(fr|en)\/(login|register|register-options|register-totp|register-email-otp|register-password|magic-link|forgot-password)(\/.*)*/,
  /^\/(fr|en)\/courses(\/[^/]+)?$/,
  /^\/api\//,
  /^\/_next\//,
  /^\/favicon\.ico$/,
  /^\/manifest\.json$/,
  /^\/icon-.*\.svg$/,
  /^\/sw\.js$/,
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATTERNS.some((pattern) => pattern.test(pathname));
}

function getToken(request: NextRequest): string | null {
  const cookie = request.cookies.get("access_token")?.value;
  if (cookie) return cookie;

  const auth = request.headers.get("authorization");
  if (auth?.startsWith("Bearer ")) return auth.slice(7);

  return null;
}

export default function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (pathname === "/settings") {
    return NextResponse.redirect(new URL("/profile", request.url));
  }
  if (pathname === "/fr/settings" || pathname === "/en/settings") {
    const locale = pathname.split("/")[1];
    return NextResponse.redirect(new URL(`/${locale}/profile`, request.url));
  }

  if (!isPublicPath(pathname)) {
    const token = getToken(request);
    if (!token) {
      const locale = pathname.split("/")[1];
      const validLocale = ["fr", "en"].includes(locale) ? locale : "fr";
      const loginUrl = new URL(`/${validLocale}/login`, request.url);
      loginUrl.searchParams.set("redirect", pathname);
      return NextResponse.redirect(loginUrl);
    }
  }

  return intlMiddleware(request);
}

export const config = {
  matcher: ["/", "/(fr|en)/:path*", "/((?!_next|favicon.ico|manifest.json|icon-|sw.js).*)"],
};
