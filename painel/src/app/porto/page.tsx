import type { Metadata } from "next";
import { Suspense } from "react";
import TelaPorto from "@/components/TelaPorto";

export const metadata: Metadata = { title: "Porto · Info-Maré" };

// Página estática única; o porto vem do endereço (?p=santos).
export default function Porto() {
  return (
    <Suspense fallback={<div className="pagina"><p className="nota">Carregando…</p></div>}>
      <TelaPorto />
    </Suspense>
  );
}
