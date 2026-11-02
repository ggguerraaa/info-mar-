// Ícones em SVG próprio, traço simples, cor herdada do texto (currentColor).
// Decorativos por padrão (aria-hidden); o botão que os contém leva o rótulo.

type P = { tamanho?: number };

const base = (t: number) => ({
  width: t, height: t, viewBox: "0 0 24 24", fill: "none", "aria-hidden": true as const,
  stroke: "currentColor", strokeWidth: 1.8, strokeLinecap: "round" as const, strokeLinejoin: "round" as const,
});

/** Logotipo: navio visto de frente sobre ondas. */
export function Logo({ tamanho = 22 }: P) {
  return (
    <svg {...base(tamanho)} strokeWidth={1.9}>
      <path d="M12 3v4" />
      <path d="M8 7h8l1.5 7h-11L8 7Z" />
      <path d="M4.5 14h15l-2 3.5h-11l-2-3.5Z" />
      <path d="M3 20.5c1.5 1 3 1 4.5 0s3-1 4.5 0 3 1 4.5 0 3-1 4.5 0" />
    </svg>
  );
}

export function IconeMapa({ tamanho = 22 }: P) {
  return (
    <svg {...base(tamanho)}>
      <path d="M9 20 3 17V4l6 3 6-3 6 3v13l-6-3-6 3Z" />
      <path d="M9 7v13M15 4v13" />
    </svg>
  );
}

export function IconeResumo({ tamanho = 22 }: P) {
  return (
    <svg {...base(tamanho)}>
      <rect x="3.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="3.5" width="7" height="7" rx="1.5" />
      <rect x="3.5" y="13.5" width="7" height="7" rx="1.5" />
      <rect x="13.5" y="13.5" width="7" height="7" rx="1.5" />
    </svg>
  );
}

/** Porto: pino com barco. */
export function IconePorto({ tamanho = 22 }: P) {
  return (
    <svg {...base(tamanho)}>
      <path d="M12 21s-6.5-6-6.5-11a6.5 6.5 0 0 1 13 0c0 5-6.5 11-6.5 11Z" />
      <path d="M9 10.5h6l-1 2h-4l-1-2ZM12 6.5v4" />
    </svg>
  );
}

export function IconeNavio({ tamanho = 22 }: P) {
  return (
    <svg {...base(tamanho)}>
      <path d="M4 15h16l-2 5H6l-2-5Z" />
      <path d="M7 15V9h10v6M12 9V5" />
    </svg>
  );
}

export function IconeBusca({ tamanho = 18 }: P) {
  return (
    <svg {...base(tamanho)}>
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-4.3-4.3" />
    </svg>
  );
}

export function IconeFechar({ tamanho = 16 }: P) {
  return (
    <svg {...base(tamanho)} strokeWidth={2}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

export function IconeSeta({ tamanho = 16, para = "cima" }: P & { para?: "cima" | "baixo" | "esquerda" }) {
  const d = { cima: "m6 15 6-6 6 6", baixo: "m6 9 6 6 6-6", esquerda: "M15 18 9 12l6-6" }[para];
  return (
    <svg {...base(tamanho)} strokeWidth={2}>
      <path d={d} />
    </svg>
  );
}

export function IconeMais({ tamanho = 16 }: P) {
  return (
    <svg {...base(tamanho)} strokeWidth={2}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

export function IconeEstrela({ tamanho = 16, cheia = false }: P & { cheia?: boolean }) {
  return (
    <svg {...base(tamanho)} fill={cheia ? "currentColor" : "none"}>
      <path d="m12 3.5 2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9L12 3.5Z" />
    </svg>
  );
}
