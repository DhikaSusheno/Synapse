import type { Metadata } from "next";
import localFont from "next/font/local";
import "./globals.css";
import BackendStatusBanner from "@/components/shared/BackendStatusBanner";

const inter = localFont({ src: "../public/fonts/InterVariable.woff2", variable: "--font-inter" });

export const metadata: Metadata = {
  title: "Synapse — Live Graph",
  description: "Reversible, conflict-aware understanding layer for AI coding agents",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className={`${inter.variable} h-screen overflow-hidden bg-[#080d14] text-slate-100 antialiased`}>
        {/* Banner sits in flow (not fixed) so it can never cover the TopNavbar or
            the LeftNav logo. Children get the remaining height. */}
        <div className="flex h-full flex-col">
          <BackendStatusBanner />
          <div className="min-h-0 flex-1">{children}</div>
        </div>
      </body>
    </html>
  );
}
