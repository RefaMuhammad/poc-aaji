import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MAB Indonesia POC",
  description: "Platform telaah medis klaim rawat inap (Tahap 0, data rekaan)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id">
      <body className="min-h-screen bg-slate-50 text-slate-900">
        <div className="bg-amber-100 px-4 py-2 text-center text-sm font-medium text-amber-900">
          Data rekaan untuk demonstrasi
        </div>
        {children}
      </body>
    </html>
  );
}
