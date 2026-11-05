import type { NextConfig } from "next";

// Exportação estática (pasta out/), publicada no GitHub Pages pelo workflow
// .github/workflows/atualizar.yml junto com os dados em out/dados/.
// NEXT_PUBLIC_BASE_PATH: "/nome-do-repo" no Pages de projeto (o workflow
// preenche); vazio em desenvolvimento.
const nextConfig: NextConfig = {
  output: "export",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  trailingSlash: true,
  images: { unoptimized: true },
  // Esconde o botão flutuante "N" do Next em `npm run dev`.
  devIndicators: false,
};

export default nextConfig;
