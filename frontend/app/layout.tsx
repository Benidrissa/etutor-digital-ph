// Root layout is intentionally a pass-through. The real <html>/<body> and
// `generateMetadata` live in app/[locale]/layout.tsx so we can set
// `<html lang={locale}>` from the URL segment (issue #1617). Next.js 15
// accepts this arrangement as long as exactly one layout in the tree
// emits <html>/<body>.

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return children;
}
