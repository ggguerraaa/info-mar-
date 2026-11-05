import type { Metadata } from "next";
import TelaSchedule from "@/components/TelaSchedule";

export const metadata: Metadata = { title: "Schedule · Info-Maré" };

export default function Schedule() {
  return <TelaSchedule />;
}
