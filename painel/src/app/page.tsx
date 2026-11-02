import { Suspense } from "react";
import TelaMapa from "@/components/TelaMapa";

export default function Inicio() {
  return (
    <Suspense fallback={<div className="mapa-gl" />}>
      <TelaMapa />
    </Suspense>
  );
}
