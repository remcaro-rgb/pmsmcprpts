import type { Metadata, Viewport } from "next";
import { messages } from "@/lib/i18n";
import { serverLocale } from "@/lib/locale-server";
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
  return (
    <html lang={locale === "es" ? "es-419" : "en"}>
      <body>{children}</body>
    </html>
  );
}
