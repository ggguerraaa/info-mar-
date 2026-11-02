import { fmt } from "@/lib/api";

// Curva de maré do dia (pontos a cada 30 min, hora de Brasília) com o
// instante atual marcado. Só traço e área clara: o número vem no texto.

const minutos = (hhmm: string) => {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
};

export default function CurvaMare({
  curva,
  horaAtual,
  altura = 90,
}: {
  curva: { hora: string; altura_m: number }[];
  horaAtual: string;
  altura?: number;
}) {
  if (curva.length < 2) return null;
  const L = 320;
  const H = altura;
  const topo = 14;
  const base = H - 18;
  const valores = curva.map((p) => p.altura_m);
  const min = Math.min(...valores);
  const max = Math.max(...valores);
  const faixa = max - min || 1;
  const x = (hhmm: string) => (minutos(hhmm) / 1440) * L;
  const y = (v: number) => base - ((v - min) / faixa) * (base - topo);
  const linha = curva.map((p, i) => `${i ? "L" : "M"}${x(p.hora).toFixed(1)},${y(p.altura_m).toFixed(1)}`).join(" ");
  const area = `${linha} L${x(curva[curva.length - 1].hora).toFixed(1)},${base} L0,${base} Z`;

  // altura agora: interpolação linear entre os pontos de 30 min (só para o marcador)
  const agora = minutos(horaAtual);
  const i = Math.min(curva.length - 2, Math.max(0, Math.floor(agora / 30)));
  const t = Math.min(1, Math.max(0, (agora - minutos(curva[i].hora)) / 30));
  const vAgora = curva[i].altura_m + (curva[i + 1].altura_m - curva[i].altura_m) * t;
  const xAgora = (agora / 1440) * L;

  return (
    <svg viewBox={`0 0 ${L} ${H}`} className="curva-mare" role="img"
      aria-label={`Curva de maré de hoje, entre ${fmt(min, 2, " m")} e ${fmt(max, 2, " m")}. Agora, ${horaAtual}.`}>
      <path d={area} fill="#C3E4E9" opacity="0.6" />
      <path d={linha} fill="none" stroke="#056C89" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
      <line x1={xAgora} y1={topo - 8} x2={xAgora} y2={base} stroke="#023653" strokeWidth="1" strokeDasharray="3 4" />
      <circle cx={xAgora} cy={y(vAgora)} r="4.5" fill="#023653" />
      <g fontSize="11" fill="#41667D">
        <text x="0" y={H - 3}>0h</text>
        <text x={L / 2} y={H - 3} textAnchor="middle">12h</text>
        <text x={L} y={H - 3} textAnchor="end">24h</text>
      </g>
    </svg>
  );
}
