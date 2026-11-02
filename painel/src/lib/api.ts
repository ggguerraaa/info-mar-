// Chamadas ao backend (ais-service/backend_app.py) e formatação.
// Em produção o painel é servido pelo próprio backend: URL vazia = mesma
// origem. Nenhuma chave passa por aqui — os endpoints são públicos, só de
// leitura, com limite de requisições por IP.
export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";

export const ESTILO_MAPA_URL =
  process.env.NEXT_PUBLIC_MAPA_ESTILO_URL || "https://tiles.openfreemap.org/styles/positron";

export const AVISO_NAVEGACAO =
  "Auxílio à análise. Não use como única fonte para navegação. A decisão é do comandante e da praticagem.";

export const AVISO_COBERTURA =
  "Cobertura: antenas terrestres. Navios longe da costa podem não aparecer.";

export class ErroApi extends Error {
  constructor(public status: number, mensagem: string) {
    super(mensagem);
  }
}

export async function buscarJson<T>(caminho: string, sinal?: AbortSignal): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${BACKEND_URL}${caminho}`, { signal: sinal, cache: "no-store" });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ErroApi(0, "Sem conexão com o servidor. Confira a internet e tente de novo.");
  }
  if (resp.status === 429) throw new ErroApi(429, "Muitas consultas seguidas. Aguarde meio minuto.");
  if (resp.status === 404) throw new ErroApi(404, "Não encontrado.");
  if (!resp.ok) throw new ErroApi(resp.status, `O servidor respondeu com erro ${resp.status}. Tente de novo em instantes.`);
  return resp.json();
}

// ------------------------------------------------------------- navios

/** Linha compacta de /api/navios (ordem em `campos` da resposta). */
export type LinhaNavio = [
  mmsi: string,
  lat: number,
  lon: number,
  velocidade: number | null,
  rumo: number | null,
  proa: number | null,
  status: number | null,
  nome: string | null,
  idade_s: number,
];

export interface RespostaNavios {
  campos: string[];
  navios: LinhaNavio[];
  total_memoria: number;
  gerado_em: string;
}

export interface CardNavio {
  mmsi: string;
  nome: string | null;
  imo: string | null;
  indicativo: string | null;
  tipo: string | null;
  comprimento_m: number | null;
  boca_m: number | null;
  calado_max_m: number | null;
  bandeira: string | null;
  destino_informado: string | null;
  eta_informada: string | null;
  armador: { nome: string | null; fonte: string | null; em: string | null };
  dados_estaticos_em: string | null;
  posicao: {
    latitude: number;
    longitude: number;
    velocidade_nos: number | null;
    rumo: number | null;
    proa: number | null;
    status: string | null;
    status_codigo: number | null;
    timestamp_utc: string;
    idade_s: number | null;
  } | null;
  fonte: string;
}

export interface ResultadoBusca {
  mmsi: string;
  nome: string | null;
  imo: string | null;
  tipo: string | null;
  bandeira: string | null;
  tem_posicao: boolean;
}

export interface Trajetoria {
  coordinates: [number, number][];
}

/** Status de navegação AIS -> situação em uma palavra. */
export function situacaoNavio(status: number | null | undefined, velocidade: number | null | undefined): string {
  if (status === 5) return "Atracado";
  if (status === 1) return "Fundeado";
  if (velocidade != null && velocidade >= 0.5) return "Em rota";
  if (velocidade != null) return "Parado";
  return "Sem dado";
}

// ------------------------------------------------------------- portos

export interface PortoMapa {
  slug: string;
  porto: string;
  estado: string;
  lat: number;
  lon: number;
  modelo: "mare" | "nivel_rio";
}

export interface Fonte {
  fonte: string | null;
}

export interface BlocoMare {
  altura_m: number;
  subindo: boolean | null;
  proxima_alta: { horario: string; altura_m: number } | null;
  proxima_baixa: { horario: string; altura_m: number } | null;
  curva_hoje: { hora: string; altura_m: number }[];
  eventos_hoje: { tipo: string; horario: string; altura_m: number }[];
  hora_atual: string;
  fonte: string | null;
}

export interface BlocoTempo {
  fonte: string;
  obtido_em: string | null;
  vento_kn: number | null;
  vento_direcao: string | null;
  rajada_kn: number | null;
  onda_m: number | null;
  onda_periodo_s: number | null;
  onda_direcao: string | null;
  visibilidade_km: number | null;
  proximas_horas: { hora: string; vento_kn: number | null; rajada_kn: number | null; onda_m: number | null }[];
}

export interface BlocoBarra {
  disponivel: boolean;
  situacao?: string | null;
  fechada?: boolean;
  fonte?: string | null;
  desde?: string | null;
  coletado_em?: string | null;
}

export interface BlocoIndice {
  calculavel: boolean;
  valor: number | null;
  status: "ideal" | "atencao" | "restrita" | null;
  calculado_em: string | null;
  explicacao?: string | null;
  motivo?: string | null;
}

export interface NavioPerto {
  mmsi: string;
  nome: string | null;
  velocidade_nos: number | null;
  idade_s: number;
  distancia_km: number;
  destino?: string;
  eta_informada?: string | null;
}

export interface BlocoNavios {
  raio_km: number;
  atracados: NavioPerto[];
  fundeados: NavioPerto[];
  parados: NavioPerto[];
  em_movimento: NavioPerto[];
  a_caminho: NavioPerto[];
  fonte: string;
}

export interface NivelRio {
  data_leitura: string | null;
  cota_m: number | null;
  variacao_cm: number | null;
  tendencia: string | null;
  fonte: string;
  coletado_em: string;
  disponivel: boolean;
}

export interface Limite {
  operacao: string;
  fonte: string;
  documento: string;
  data_documento: string;
  confianca: string;
  vento_kn?: number;
  onda_hs_m?: number;
  visibilidade_mn?: number;
  mare_minima_m?: number;
  aplica_a?: string;
  observacao?: string;
}

export interface PainelPorto {
  slug: string;
  porto: string;
  estado: string;
  lat: number;
  lon: number;
  modelo: "mare" | "nivel_rio";
  situacao: { palavra: string; motivo: string };
  indice: BlocoIndice;
  mare: BlocoMare | null;
  rio: NivelRio | null;
  tempo: BlocoTempo | null;
  barra: BlocoBarra;
  calado: {
    calado_maximo_m: number;
    canal: string | null;
    bercos: string | null;
    fonte: string | null;
    verificado_em: string | null;
    confianca: string | null;
  } | null;
  limites: Limite[];
  navios: BlocoNavios;
  gerado_em: string;
}

export interface ResumoPorto {
  slug: string;
  porto: string;
  estado: string;
  modelo: "mare" | "nivel_rio";
  calado_maximo_m: number | null;
  mare: { altura_m: number; subindo: boolean | null; fonte: string | null } | null;
  rio?: NivelRio | null;
  tempo: BlocoTempo | null;
  barra: BlocoBarra;
  indice: BlocoIndice;
  situacao: { palavra: string; motivo: string };
}

export function classeSituacao(palavra: string): string {
  if (palavra === "Normal" || palavra === "Aberta") return "selo normal";
  if (palavra === "Atenção") return "selo atencao";
  if (palavra === "Restrita") return "selo grave";
  return "selo";
}

// ------------------------------------------------------------- formatação

const numero = (casas: number) =>
  new Intl.NumberFormat("pt-BR", { minimumFractionDigits: casas, maximumFractionDigits: casas });

/** 1,2 m · 14 nós · null -> "sem dado" */
export function fmt(v: number | null | undefined, casas = 1, sufixo = ""): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "sem dado";
  return `${numero(casas).format(v)}${sufixo}`;
}

export function idadeTexto(segundos: number | null | undefined): string {
  if (segundos === null || segundos === undefined) return "sem dado";
  const s = Math.max(0, Math.round(segundos));
  if (s < 60) return `há ${s} s`;
  if (s < 3600) return `há ${Math.round(s / 60)} min`;
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.round((s % 3600) / 60);
    return m ? `há ${h} h ${m} min` : `há ${h} h`;
  }
  return `há ${Math.round(s / 86400)} d`;
}

/** "há 3 min" a partir de um ISO UTC */
export function haQuantoTempo(iso: string | null | undefined): string {
  if (!iso) return "sem dado";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "sem dado";
  return idadeTexto((Date.now() - t) / 1000);
}

/** "2026-11-02T14:40:00" (hora local da tábua) -> "14h40" */
export function horaCurta(isoLocal: string | null | undefined): string {
  if (!isoLocal) return "sem dado";
  const m = isoLocal.match(/T(\d{2}):(\d{2})/);
  return m ? `${m[1]}h${m[2]}` : isoLocal;
}

export function dataCurta(iso: string | null | undefined): string {
  if (!iso) return "sem data";
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : iso;
}

/** Posição sem sinal recente: acima disso o navio aparece "sem sinal há X". */
export const SINAL_RECENTE_S = 30 * 60;
