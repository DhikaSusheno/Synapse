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
      <body className={`${inter.variable} bg-slate-950 text-slate-100 antialiased`}>
        <BackendStatusBanner />
        {children}
      </body>
    </html>
  );
}
