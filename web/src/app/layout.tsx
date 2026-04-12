import type { Metadata } from "next";
import { Inter, Inter_Tight, Outfit } from "next/font/google";
import localFont from "next/font/local";
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

const outfit = Outfit({
  variable: "--font-outfit",
  subsets: ["latin"],
});

const neueMontreal = localFont({
  src: [
    { path: "../../public/fonts/PPNeueMontreal-Thin.otf", weight: "100" },
    { path: "../../public/fonts/PPNeueMontreal-Book.otf", weight: "400" },
    { path: "../../public/fonts/PPNeueMontreal-Italic.otf", weight: "400", style: "italic" },
    { path: "../../public/fonts/PPNeueMontreal-Medium.otf", weight: "500" },
    { path: "../../public/fonts/PPNeueMontreal-SemiBolditalic.otf", weight: "600", style: "italic" },
    { path: "../../public/fonts/PPNeueMontreal-Bold.otf", weight: "700" },
  ],
  variable: "--font-neue",
});

const eiko = localFont({
  src: [
    { path: "../../public/fonts/PPEiko-Thin.otf", weight: "100" },
    { path: "../../public/fonts/PPEiko-LightItalic.otf", weight: "300", style: "italic" },
    { path: "../../public/fonts/PPEiko-Medium.otf", weight: "500" },
    { path: "../../public/fonts/PPEiko-Heavy.otf", weight: "800" },
    { path: "../../public/fonts/PPEiko-BlackItalic.otf", weight: "900", style: "italic" },
  ],
  variable: "--font-eiko",
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

      <body className={`${inter.variable} ${interTight.variable} ${outfit.variable} ${neueMontreal.variable} ${eiko.variable}`}>
        <ThemeProvider attribute="data-theme" defaultTheme="dark" enableSystem={false}>
            {children}
          </ThemeProvider>      
        </body>
    </html>
  );
}
