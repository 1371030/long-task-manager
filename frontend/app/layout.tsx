import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Long Task Manager",
  description: "Long-running task management kernel",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
