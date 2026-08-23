import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "DocFiller – Intelligent Document Filler",
  description:
    "Upload an Excel file and a PDF template, and let AI intelligently fill in the blanks.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
