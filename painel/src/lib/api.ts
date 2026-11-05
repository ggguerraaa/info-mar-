// Dados do painel e formatação.
//
// Dois modos:
//  - estático (produção, GitHub Pages): NEXT_PUBLIC_BACKEND_URL vazio. O
//    GitHub Actions gera a cada ~30 min os arquivos em /dados/ (ver
//    ais-service/gerar_estatico.py) e o painel lê esses arquivos. Os caminhos
//    "/api/..." continuam iguais no código: buscarJson traduz para o arquivo.
//  - backend ao vivo (desenvolvimento): NEXT_PUBLIC_BACKEND_URL aponta para o
//    FastAPI (uvicorn backend_app:app).
export const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL ?? "";
export const MODO_ESTATICO = BACKEND_URL === "";

/** Prefixo do site (GitHub Pages de projeto: "/nome-do-repo"). */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

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

async function baixar<T>(url: string, sinal?: AbortSignal): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(url, { signal: sinal, cache: MODO_ESTATICO ? "default" : "no-store" });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ErroApi(0, "Sem conexão com o servidor. Confira a internet e tente de novo.");
  }
  if (resp.status === 429) throw new ErroApi(429, "Muitas consultas seguidas. Aguarde meio minuto.");
  if (resp.status === 404) throw new ErroApi(404, "Não encontrado.");
  if (!resp.ok) throw new ErroApi(resp.status, `O servidor respondeu com erro ${resp.status}. Tente de novo em instantes.`);
  return resp.json();
}

export async function buscarJson<T>(caminho: string, sinal?: AbortSignal): Promise<T> {
  if (MODO_ESTATICO) return (await rotaEstatica(caminho, sinal)) as T;
  return baixar<T>(`${BACKEND_URL}${caminho}`, sinal);
}

// ------------------------------------------------------------- modo estático

/** Arquivo gerado pelo Actions. O parâmetro muda a cada minuto: fura o cache
 *  do navegador/CDN sem baixar de novo a cada clique. */
async function arquivo<T>(nome: string, sinal?: AbortSignal): Promise<T> {
  const v = Math.floor(Date.now() / 60_000);
  return envelhecer(await baixar<T>(`${BASE_PATH}/dados/${nome}?v=${v}`, sinal));
}

/** Os arquivos trazem "idade_s" do momento em que foram gerados; soma o tempo
 *  que passou desde "gerado_em" para a idade continuar certa na tela. */
function envelhecer<T>(dados: T): T {
  const raiz = dados as { gerado_em?: string } | unknown[];
  const gerado = !Array.isArray(raiz) && raiz?.gerado_em ? new Date(raiz.gerado_em).getTime() : NaN;
  if (Number.isNaN(gerado)) return dados;
  const extra = Math.max(0, Math.round((Date.now() - gerado) / 1000));
  const somar = (v: unknown): void => {
    if (Array.isArray(v)) v.forEach(somar);
    else if (v && typeof v === "object") {
      for (const [k, x] of Object.entries(v)) {
        if (k === "idade_s" && typeof x === "number") (v as Record<string, number>)[k] = x + extra;
        else somar(x);
      }
    }
  };
  somar(dados);
  return dados;
}

/** Datas dos arquivos gerados (para mostrar "atualizado há X"). */
export interface MetaDados {
  gerado_em: string;
  intervalo_min: number;
  escuta_s: number;
  navios_em_memoria: number;
}
export const buscarMeta = (sinal?: AbortSignal) => arquivo<MetaDados>("meta.json", sinal);

interface TodosNavios {
  campos: string[];
  navios: (string | number | boolean | null)[][];
  gerado_em: string;
}
let cacheTodos: { em: number; dados: Record<string, unknown>[] } | null = null;

async function todosNavios(sinal?: AbortSignal) {
  if (cacheTodos && Date.now() - cacheTodos.em < 60_000) return cacheTodos.dados;
  const t = await arquivo<TodosNavios>("navios/todos.json", sinal);
  const iIdade = t.campos.indexOf("idade_s");
  const extra = Math.max(0, Math.round((Date.now() - new Date(t.gerado_em).getTime()) / 1000));
  const dados = t.navios.map((linha) => {
    const o: Record<string, unknown> = Object.fromEntries(t.campos.map((c, i) => [c, linha[i]]));
    if (typeof linha[iIdade] === "number") o.idade_s = (linha[iIdade] as number) + extra;
    return o;
  });
  cacheTodos = { em: Date.now(), dados };
  return dados;
}

async function rotaEstatica(caminho: string, sinal?: AbortSignal): Promise<unknown> {
  const url = new URL(caminho, "http://x");
  const p = url.pathname.replace(/\/$/, "");
  const q = url.searchParams;
  let m: RegExpMatchArray | null;

  if (p === "/api/navios") {
    const dados = await arquivo<RespostaNavios>("navios.json", sinal);
    const caixa = q.get("bbox")?.split(",").map(Number);
    if (caixa?.length === 4 && caixa.every((n) => !Number.isNaN(n))) {
      const [lonMin, latMin, lonMax, latMax] = caixa;
      dados.navios = dados.navios.filter((n) => n[1] >= latMin && n[1] <= latMax && n[2] >= lonMin && n[2] <= lonMax);
    }
    return dados;
  }
  if (p === "/api/portos") return arquivo("portos.json", sinal);
  if (p === "/api/schedule") return arquivo("schedule.json", sinal);
  if (p === "/api/portos/resumo") {
    const linhas = await arquivo<ResumoPorto[]>("portos/resumo.json", sinal);
    const pedidos = (q.get("slugs") ?? "").split(",").filter(Boolean);
    if (!pedidos.length) return linhas;
    const por = new Map(linhas.map((l) => [l.slug, l]));
    return pedidos.map((s) => por.get(s)).filter(Boolean);
  }
  if ((m = p.match(/^\/api\/portos\/([a-z0-9_]+)\/painel$/))) return arquivo(`portos/${m[1]}/painel.json`, sinal);

  if (p === "/api/navios/busca") {
    const termo = (q.get("q") ?? "").trim().toUpperCase();
    if (termo.length < 3) return [];
    const todos = await todosNavios(sinal);
    const numero = /^\d+$/.test(termo);
    const achados = todos.filter((n) =>
      numero
        ? String(n.mmsi).startsWith(termo) || String(n.imo ?? "").startsWith(termo)
        : String(n.nome ?? "").toUpperCase().includes(termo),
    );
    const exato = (n: Record<string, unknown>) =>
      numero ? n.mmsi === termo || n.imo === termo : String(n.nome ?? "").toUpperCase().startsWith(termo);
    achados.sort((a, b) => Number(exato(b)) - Number(exato(a)) || String(a.nome ?? "~").localeCompare(String(b.nome ?? "~")));
    return achados.slice(0, 20).map((n) => ({
      mmsi: n.mmsi, nome: n.nome, imo: n.imo, tipo: n.tipo, bandeira: n.bandeira, tem_posicao: n.tem_posicao,
    }));
  }
  if (p === "/api/navios/lote") {
    const pedidos = (q.get("mmsi") ?? "").split(",").filter((s) => /^\d{9}$/.test(s));
    const por = new Map((await todosNavios(sinal)).map((n) => [n.mmsi, n]));
    return pedidos.map((mmsi) => {
      const n = por.get(mmsi);
      return {
        mmsi,
        nome: n?.nome ?? null, imo: n?.imo ?? null, destino_informado: n?.destino_informado ?? null,
        status_codigo: n?.status_codigo ?? null, velocidade_nos: n?.velocidade_nos ?? null,
        latitude: n?.latitude ?? null, longitude: n?.longitude ?? null, idade_s: n?.idade_s ?? null,
      };
    });
  }
  if ((m = p.match(/^\/api\/navios\/(\d{9})\/trajetoria$/))) {
    try {
      return await arquivo(`navios/${m[1]}/trajetoria.json`, sinal);
    } catch (e) {
      if (e instanceof ErroApi && e.status === 404) return { type: "LineString", coordinates: [] };
      throw e;
    }
  }
  if ((m = p.match(/^\/api\/navios\/(\d{9})$/))) {
    try {
      return await arquivo(`navios/${m[1]}.json`, sinal);
    } catch (e) {
      if (!(e instanceof ErroApi) || e.status !== 404) throw e;
      // sem posição na retenção: monta o card com o que se sabe do navio
      const n = (await todosNavios(sinal)).find((x) => x.mmsi === m![1]);
      if (!n) throw new ErroApi(404, "Navio ainda não visto pelo AIS.");
      return {
        mmsi: n.mmsi, nome: n.nome, imo: n.imo, indicativo: null, tipo: n.tipo, comprimento_m: null, boca_m: null,
        calado_max_m: null, bandeira: n.bandeira, destino_informado: n.destino_informado, eta_informada: null,
        armador: { nome: null, fonte: null, em: null }, dados_estaticos_em: null, posicao: null,
        fonte: "AISstream.io (antenas terrestres)",
      };
    }
  }
  throw new ErroApi(404, "Não disponível na versão estática.");
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

// ------------------------------------------------------------- schedule

export type SituacaoEscala =
  | "no_prazo" | "atrasado" | "adiantado" | "fundeado" | "atracado" | "saiu" | "omitido"
  | "possivel_omissao" | "nao_observado" | "sem_sinal" | "sem_mmsi" | "sem_dado";

export interface Escala {
  porto: string;
  porto_nome: string;
  viagem: string;
  programado: { eta: string | null; etb: string | null; ets: string | null };
  estimado: { eta: string | null; etb: string | null; ets: string | null };
  real: { ata: string | null; atb: string | null; atd: string | null };
  desvio_h: { eta: number | null; etb: number | null; ets: number | null };
  base_previsao: "real" | "velocidade_ais" | "velocidade_padrao" | "encadeado" | null;
  situacao: SituacaoEscala;
}

export interface NavioSchedule {
  navio: string;
  imo: string;
  mmsi: string;
  posicao: { lat: number; lon: number; sog: number | null; hora: string } | null;
  sinal_idade_h: number | null;
  escalas: Escala[];
}

export interface RespostaSchedule {
  gerado_em: string;
  tolerancia_h: number;
  avisos: string[];
  portos: Record<string, { nome: string; lat: number; lon: number }>;
  navios: NavioSchedule[];
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
