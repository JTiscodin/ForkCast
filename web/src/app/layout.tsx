import type { Metadata, Viewport } from "next";
import { Manrope, Geist_Mono, Bricolage_Grotesque } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

// Manrope is the closest available free grotesque substitute for Basis Grotesque Pro.
const manrope = Manrope({
  variable: "--font-manrope",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700", "800"],
  display: "swap",
});

// Display: Bricolage has the warm, slightly hand-cut feel of a dhaba signboard
const bricolage = Bricolage_Grotesque({
  variable: "--font-bricolage",
  subsets: ["latin"],
  weight: ["600", "700", "800"],
  display: "swap",
});

// Utility: numerals / data / code
const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Forkcast — today's meals, sorted",
    template: "%s · Forkcast",
  },
  description:
    "Forkcast picks breakfast, lunch, snack and dinner for you every day from Swiggy and Instamart, inside your budget, diet and allergies.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#FFFFFF" },
    { media: "(prefers-color-scheme: dark)", color: "#121212" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${manrope.variable} ${geistMono.variable} ${bricolage.variable} h-full antialiased`}
    >
      <body
        className="min-h-full flex flex-col"
        // Browser extensions (ColorZilla's cz-shortcut-listen, password
        // managers, dark-mode injectors) stamp attributes onto <body> before
        // React hydrates; that mismatch is benign and not ours to fix, so
        // suppress the warning on this element only.
        suppressHydrationWarning
      >
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          {children}
          <Toaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
