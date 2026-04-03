import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";
import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

const ADMIN_ROUTE_PATTERN = /^\/(fr|en)\/(admin)(\/.*)?$/;

function getTokenRoleFromCookie(request: NextRequest): string | null {
  const token = request.cookies.get("access_token")?.value;
  if (!token) return null;

  try {
    const [, payload] = token.split(".");
    const decoded = JSON.parse(
      Buffer.from(payload, "base64url").toString("utf-8")
    );
    return decoded?.role ?? null;
  } catch {
    return null;
  }
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

  if (ADMIN_ROUTE_PATTERN.test(pathname)) {
    const role = getTokenRoleFromCookie(request);
    if (role !== "admin" && role !== "expert") {
      const locale = pathname.split("/")[1] ?? "fr";
      return NextResponse.redirect(
        new URL(`/${locale}/dashboard`, request.url)
      );
    }
  }

  return intlMiddleware(request);
}

export const config = {
  matcher: ["/", "/(fr|en)/:path*"],
};
