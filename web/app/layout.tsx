import type { Metadata, Viewport } from "next";
import { messages } from "@/lib/i18n";
import { serverLocale, serverTheme } from "@/lib/request-prefs";
import "./globals.css";

export async function generateMetadata(): Promise<Metadata> {
  const t = messages(await serverLocale());
  return { title: t.appName, description: t.tagline };
}

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const locale = await serverLocale();
  const theme = await serverTheme();
  return (
    <html lang={locale === "es" ? "es-419" : "en"} className={theme === "dark" ? "dark" : undefined}>
      <body>{children}</body>
    </html>
  );
}
