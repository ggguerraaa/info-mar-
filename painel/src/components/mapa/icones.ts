// Ícones do mapa desenhados em canvas (sem arquivo externo): triângulo
// estreito apontando para o rumo, ponto para navio parado e o pino de porto.
// Desenhados em 2x para ficarem nítidos em tela de alta densidade.

const ESCALA = 2;

type Imagem = { width: number; height: number; data: Uint8ClampedArray };

function desenhar(largura: number, altura: number, pintar: (c: CanvasRenderingContext2D) => void): Imagem {
  const canvas = document.createElement("canvas");
  canvas.width = largura * ESCALA;
  canvas.height = altura * ESCALA;
  const c = canvas.getContext("2d")!;
  c.scale(ESCALA, ESCALA);
  pintar(c);
  const { data } = c.getImageData(0, 0, canvas.width, canvas.height);
  return { width: canvas.width, height: canvas.height, data };
}

/** Navio em movimento: triângulo achatado, ponta para cima (rumo 0°). */
export function iconeNavio(preenchimento: string, contorno: string, tamanho: number): Imagem {
  const l = tamanho * 0.62;
  return desenhar(tamanho, tamanho, (c) => {
    const meio = tamanho / 2;
    c.beginPath();
    c.moveTo(meio, 1);
    c.lineTo(meio + l / 2, tamanho - 2);
    c.lineTo(meio, tamanho - 2 - tamanho * 0.18);
    c.lineTo(meio - l / 2, tamanho - 2);
    c.closePath();
    c.fillStyle = preenchimento;
    c.fill();
    c.lineWidth = 1;
    c.lineJoin = "round";
    c.strokeStyle = contorno;
    c.stroke();
  });
}

/** Navio parado (velocidade ~0): ponto. */
export function iconePonto(preenchimento: string, contorno: string, tamanho: number): Imagem {
  return desenhar(tamanho, tamanho, (c) => {
    c.beginPath();
    c.arc(tamanho / 2, tamanho / 2, tamanho / 2 - 1.5, 0, Math.PI * 2);
    c.fillStyle = preenchimento;
    c.fill();
    c.lineWidth = 1;
    c.strokeStyle = contorno;
    c.stroke();
  });
}

/** Porto: pino com um barco simples dentro. Ponta do pino embaixo. */
export function iconePorto(cor: string, destaque: boolean): Imagem {
  const t = destaque ? 30 : 22;
  return desenhar(t, t * 1.3, (c) => {
    const r = t / 2 - 1;
    const cx = t / 2;
    c.beginPath();
    c.arc(cx, r + 1, r, Math.PI * 0.82, Math.PI * 0.18);
    c.lineTo(cx, t * 1.3 - 1);
    c.closePath();
    c.fillStyle = cor;
    c.fill();
    c.lineWidth = 1.5;
    c.strokeStyle = "#ffffff";
    c.stroke();
    // barco: casco e mastro
    const s = r / 8;
    c.beginPath();
    c.moveTo(cx - 5 * s, r + 1 + 1 * s);
    c.lineTo(cx + 5 * s, r + 1 + 1 * s);
    c.lineTo(cx + 3 * s, r + 1 + 4 * s);
    c.lineTo(cx - 3 * s, r + 1 + 4 * s);
    c.closePath();
    c.fillStyle = "#ffffff";
    c.fill();
    c.beginPath();
    c.moveTo(cx, r + 1 - 5 * s);
    c.lineTo(cx, r + 1 + 1 * s);
    c.lineTo(cx + 4 * s, r + 1);
    c.closePath();
    c.fill();
  });
}

export const ESCALA_ICONES = ESCALA;
