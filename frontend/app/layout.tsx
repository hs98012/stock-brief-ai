import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Stock Brief AI",
  description: "근거 중심 금융 문서 브리핑",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

