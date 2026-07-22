import type { Metadata, Viewport } from "next";
import "./globals.css";
import I18nProvider from "@/components/providers/I18nProvider";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
};

export const metadata: Metadata = {
  title: "WIGVO — AI Voice Agent Platform",
  description:
    "AI voice assistant service that makes phone calls on your behalf",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <body
        className="h-dvh overflow-hidden bg-[#F5F4F6] antialiased"
      >
        <I18nProvider>
          <main className="h-full">
            {children}
          </main>
        </I18nProvider>
      </body>
    </html>
  );
}
