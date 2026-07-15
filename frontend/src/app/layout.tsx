import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import Shell from "@/components/Shell";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-body" });
const grotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-display" });

export const metadata: Metadata = {
  title: "Self Planner",
  description: "AI-powered personal meeting assistant",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" data-theme="dark" className={`${inter.variable} ${grotesk.variable}`}>
      <body>
        {/* Apply saved theme before paint to avoid a light/dark flash */}
        <script
          dangerouslySetInnerHTML={{
            __html: `try{var t=localStorage.getItem("theme");if(t)document.documentElement.dataset.theme=t}catch(e){}`,
          }}
        />
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
