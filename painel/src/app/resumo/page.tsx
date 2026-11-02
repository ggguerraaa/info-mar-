import type { Metadata } from "next";
import TelaResumo from "@/components/TelaResumo";

export const metadata: Metadata = { title: "Resumo dos portos · Info-Maré" };

export default function Resumo() {
  return <TelaResumo />;
}
