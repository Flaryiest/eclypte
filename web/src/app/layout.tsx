import type { Metadata } from "next";
import { Inter, Inter_Tight } from "next/font/google";
import {ThemeProvider } from 'next-themes'
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

const interTight = Inter_Tight({
  variable: "--font-inter-tight",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Eclypte",
  description: "An AMV creator",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html suppressHydrationWarning lang="en">

      <body className={`${inter.variable} ${interTight.variable}`}>
        <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem={false}>
            {children}
          </ThemeProvider>      
        </body>
    </html>
  );
}
