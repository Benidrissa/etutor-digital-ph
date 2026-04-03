import createMiddleware from "next-intl/middleware";
import { NextRequest, NextResponse } from "next/server";
import { routing } from "./i18n/routing";

const intlMiddleware = createMiddleware(routing);

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
  
  return intlMiddleware(request);
}

export const config = {
  matcher: ["/", "/(fr|en)/:path*"],
};
