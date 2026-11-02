import type { Metadata } from "next";
import TelaPortos from "@/components/TelaPortos";

export const metadata: Metadata = { title: "Portos · Info-Maré" };

export default function Portos() {
  return <TelaPortos />;
}
