import type { Metadata, Viewport } from "next";
import "@fontsource-variable/public-sans";
import "./globals.css";
import Casca from "@/components/Casca";

// Public Sans vem do pacote @fontsource (empacotada no build): nenhuma
// chamada a servidor de fontes de terceiros no navegador de quem usa.

export const metadata: Metadata = {
  title: "Info-Maré",
  description: "Navios na costa brasileira, maré, vento e ondas dos portos — com a fonte de cada dado.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#023653",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>
        <Casca>{children}</Casca>
      </body>
    </html>
  );
}
