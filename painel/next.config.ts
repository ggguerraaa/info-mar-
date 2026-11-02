import type { NextConfig } from "next";

// Exportação estática (pasta out/): o backend FastAPI serve o painel na mesma
// URL da API — um serviço só no Render, sem servidor Node e sem CORS.
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  // Esconde o botão flutuante "N" do Next em `npm run dev`.
  devIndicators: false,
};

export default nextConfig;
