import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = {
  title: "설비 고장 분석기",
  description: "설비 고장이력 분석, 분류 검수 및 보고서",
};

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
