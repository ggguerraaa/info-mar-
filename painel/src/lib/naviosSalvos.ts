"use client";

import { useSyncExternalStore } from "react";

// "Meus navios": ficam só no navegador de cada pessoa (sem conta, o servidor
// não sabe quem acompanha o quê). localStorage pode falhar (aba anônima,
// cota, bloqueio): try/catch em toda leitura e escrita, e a página continua
// funcionando, só sem guardar. Como o navegador pode apagar, há exportar e
// importar em arquivo JSON.

export interface NavioSalvo {
  mmsi: string;
  nome: string | null;
  imo: string | null;
}

const CHAVE = "info-mare:navios-salvos";
const FORMATO = "info-mare/meus-navios";
const MAXIMO = 500;
const VAZIO: NavioSalvo[] = [];
const ouvintes = new Set<() => void>();
let cache: NavioSalvo[] | null = null;
let armazenamentoOk = true;

function valido(n: unknown): n is NavioSalvo {
  if (!n || typeof n !== "object") return false;
  const { mmsi, nome, imo } = n as Record<string, unknown>;
  return (
    typeof mmsi === "string" && /^\d{9}$/.test(mmsi) &&
    (nome == null || (typeof nome === "string" && nome.length <= 40)) &&
    (imo == null || (typeof imo === "string" && /^\d{7}$/.test(imo)))
  );
}

function limpar(lista: unknown[]): NavioSalvo[] {
  const vistos = new Set<string>();
  const saida: NavioSalvo[] = [];
  for (const n of lista) {
    if (!valido(n) || vistos.has(n.mmsi)) continue;
    vistos.add(n.mmsi);
    saida.push({ mmsi: n.mmsi, nome: n.nome ?? null, imo: n.imo ?? null });
    if (saida.length >= MAXIMO) break;
  }
  return saida;
}

function ler(): NavioSalvo[] {
  if (cache) return cache;
  try {
    const bruto = window.localStorage.getItem(CHAVE);
    const lista = bruto ? JSON.parse(bruto) : [];
    cache = Array.isArray(lista) ? limpar(lista) : [];
  } catch {
    armazenamentoOk = false;
    cache = [];
  }
  return cache;
}

function gravar(lista: NavioSalvo[]) {
  cache = lista;
  try {
    window.localStorage.setItem(CHAVE, JSON.stringify(lista));
    armazenamentoOk = true;
  } catch {
    armazenamentoOk = false; // vale só nesta aba
  }
  ouvintes.forEach((o) => o());
}

export function armazenamentoDisponivel(): boolean {
  return armazenamentoOk;
}

export function salvarNavio(navio: NavioSalvo) {
  const lista = ler();
  if (!lista.some((n) => n.mmsi === navio.mmsi)) gravar(limpar([...lista, navio]));
}

export function removerNavio(mmsi: string) {
  gravar(ler().filter((n) => n.mmsi !== mmsi));
}

/** Atualiza nome/IMO guardados quando o AIS traz dado novo. */
export function atualizarNavio(navio: NavioSalvo) {
  const lista = ler();
  const i = lista.findIndex((n) => n.mmsi === navio.mmsi);
  if (i < 0) return;
  const atual = lista[i];
  const novo = { mmsi: atual.mmsi, nome: navio.nome ?? atual.nome, imo: navio.imo ?? atual.imo };
  if (novo.nome === atual.nome && novo.imo === atual.imo) return;
  gravar(limpar(lista.map((n, j) => (j === i ? novo : n))));
}

export function useNaviosSalvos(): NavioSalvo[] {
  return useSyncExternalStore(
    (ouvinte) => {
      ouvintes.add(ouvinte);
      return () => ouvintes.delete(ouvinte);
    },
    ler,
    () => VAZIO,
  );
}

export function exportarArquivo(): Blob {
  const conteudo = { formato: FORMATO, versao: 1, exportado_em: new Date().toISOString(), navios: ler() };
  return new Blob([JSON.stringify(conteudo, null, 2)], { type: "application/json" });
}

/** Junta os navios do arquivo à lista atual. Devolve quantos entraram. */
export async function importarArquivo(arquivo: File): Promise<number> {
  if (arquivo.size > 200_000) throw new Error("Arquivo grande demais. Use o arquivo exportado por esta página.");
  let dados: unknown;
  try {
    dados = JSON.parse(await arquivo.text());
  } catch {
    throw new Error("O arquivo não é um JSON válido. Use o arquivo exportado por esta página.");
  }
  const lista = Array.isArray(dados) ? dados : (dados as { navios?: unknown })?.navios;
  if (!Array.isArray(lista)) throw new Error("Não achei a lista de navios no arquivo.");
  const atuais = ler();
  const novos = limpar([...atuais, ...lista]);
  gravar(novos);
  return novos.length - atuais.length;
}
