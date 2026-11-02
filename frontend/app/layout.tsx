import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Assessment · Institution workspace",
  description: "Governed question authoring and independent review",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <a className="skip" href="#main">
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
