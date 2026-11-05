// Schedule no navegador: a pessoa arrasta o CSV e a comparação programado x
// real é feita aqui, com os rastros publicados (dados/rastros.json). O
// arquivo não sai do computador dela.
//
// Mesmas regras de ais-service/schedule_status.py (mantenha os dois iguais):
// a posição vale só para a escala corrente, na ordem da rota; escala vencida
// com o navio já a caminho da seguinte = "passou sem sinal"; atraso herdado
// pelas escalas seguintes.

import type {
  Escala, NavioSchedule, PortoSchedule, RegrasSchedule, RespostaRastros, RespostaSchedule, SituacaoEscala,
} from "./api";

export const REGRAS_PADRAO: RegrasSchedule = {
  tolerancia_h: 6, sinal_valido_h: 12, omissao_h: 24, raio_fundeio_nm: 15, raio_berco_nm: 1.5,
  sog_parado: 0.5, sog_saida: 3, velocidade_padrao_nos: 12, fator_rota: 1.15,
};

interface Linha {
  navio: string; imo: string; mmsi: string; viagem: string; porto: string;
  eta: Date | null; etb: Date | null; ets: Date | null; omitido: boolean;
}

interface Ponto { lat: number; lon: number; sog: number | null; status: number | null; hora: Date }

const H = 3_600_000;

const semAcento = (t: string) =>
  t.normalize("NFD").replace(/[̀-ͯ]/g, "").trim().toUpperCase();

function milhas(lat1: number, lon1: number, lat2: number, lon2: number) {
  const r = (g: number) => (g * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lon2 - lon1) / 2) ** 2;
  return 2 * 3440.065 * Math.asin(Math.sqrt(a));
}

/** dd/mm/aaaa hh:mm (Brasília, UTC−3 sem horário de verão) ou ISO. */
function dataBr(txt: string): Date | null {
  const t = (txt ?? "").trim();
  if (!t) return null;
  let m = t.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})(?:[ T](\d{1,2}):(\d{2})(?::\d{2})?)?$/);
  if (m) {
    const [, d, mes, a, h = "0", min = "0"] = m;
    return new Date(Date.UTC(+a, +mes - 1, +d, +h + 3, +min));
  }
  m = t.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2}))?/);
  if (m) {
    const [, a, mes, d, h = "0", min = "0"] = m;
    return new Date(Date.UTC(+a, +mes - 1, +d, +h + 3, +min));
  }
  throw new Error(`data inválida: "${t}"`);
}

/** CSV simples com ; ou , e aspas. */
function lerCsv(texto: string): Record<string, string>[] {
  const limpo = texto.replace(/^﻿/, "");
  const sep = (limpo.match(/;/g)?.length ?? 0) >= (limpo.match(/,/g)?.length ?? 0) ? ";" : ",";
  const linhas: string[][] = [];
  let campo = "", linha: string[] = [], aspas = false;
  for (let i = 0; i < limpo.length; i++) {
    const c = limpo[i];
    if (aspas) {
      if (c === '"' && limpo[i + 1] === '"') { campo += '"'; i++; }
      else if (c === '"') aspas = false;
      else campo += c;
    } else if (c === '"') aspas = true;
    else if (c === sep) { linha.push(campo); campo = ""; }
    else if (c === "\n" || c === "\r") {
      if (c === "\r" && limpo[i + 1] === "\n") i++;
      linha.push(campo); campo = "";
      if (linha.some((x) => x.trim())) linhas.push(linha);
      linha = [];
    } else campo += c;
  }
  linha.push(campo);
  if (linha.some((x) => x.trim())) linhas.push(linha);
  const [cab, ...corpo] = linhas;
  if (!cab) return [];
  const nomes = cab.map((c) => semAcento(c).toLowerCase());
  return corpo.map((l) => Object.fromEntries(nomes.map((n, i) => [n, (l[i] ?? "").trim()])));
}

export interface EntradaLocal {
  csv: string;
  portos: Record<string, PortoSchedule>;
  regras?: RegrasSchedule;
  rastros: RespostaRastros;
  imoParaMmsi: Map<string, string>;
  armadorPorImo: Map<string, string>;
}

export function analisarScheduleLocal(e: EntradaLocal): RespostaSchedule {
  const cfg = e.regras ?? REGRAS_PADRAO;
  const agora = new Date();
  const avisos: string[] = [];

  const indice = new Map<string, string>();
  for (const [slug, p] of Object.entries(e.portos)) {
    for (const nome of [slug, slug.replace(/_/g, " "), p.nome, ...(p.apelidos ?? [])]) indice.set(semAcento(nome), slug);
  }

  const linhas: Linha[] = [];
  lerCsv(e.csv).forEach((row, i) => {
    const n = i + 2;
    if (!row.navio) return;
    const porto = indice.get(semAcento(row.porto ?? ""));
    if (!porto) { avisos.push(`Linha ${n}: porto "${row.porto ?? ""}" não reconhecido.`); return; }
    try {
      linhas.push({
        navio: row.navio.toUpperCase(),
        imo: (row.imo ?? "").toUpperCase().replace("IMO", "").trim(),
        mmsi: (row.mmsi ?? "").trim(),
        viagem: row.viagem ?? "",
        porto,
        eta: dataBr(row.eta), etb: dataBr(row.etb), ets: dataBr(row.ets),
        omitido: ["s", "sim", "x", "1", "true"].includes((row.omitido ?? "").toLowerCase()),
      });
    } catch (erro) {
      avisos.push(`Linha ${n}: ${(erro as Error).message}`);
    }
  });
  if (!linhas.length && !avisos.length) avisos.push("Nenhuma linha com navio no arquivo. Confira o cabeçalho (navio;imo;mmsi;viagem;porto;eta;etb;ets;omitido).");

  for (const l of linhas) if (!l.mmsi && l.imo) l.mmsi = e.imoParaMmsi.get(l.imo) ?? "";

  const porNavio = new Map<string, Linha[]>();
  for (const l of linhas) porNavio.set(l.navio, [...(porNavio.get(l.navio) ?? []), l]);

  const navios: NavioSchedule[] = [];
  for (const [nome, todas] of porNavio) {
    todas.sort((a, b) => +(a.eta ?? a.etb ?? a.ets ?? agora) - +(b.eta ?? b.etb ?? b.ets ?? agora));
    const escalas = todas.filter((x) => !x.omitido);
    const mmsi = todas.find((x) => x.mmsi)?.mmsi ?? "";
    const chave = (x: Linha) => `${x.viagem}|${x.porto}`;
    const eventos = new Map<string, { ata?: Date; atb?: Date; atd?: Date; nao?: Date }>();
    const ev = (x: Linha) => { const k = chave(x); if (!eventos.has(k)) eventos.set(k, {}); return eventos.get(k)!; };

    const rastro: Ponto[] = (e.rastros.navios[mmsi] ?? []).map(([min, la, lo, v, st]) => ({
      lat: la / 1e4, lon: lo / 1e4, sog: v == null ? null : v / 10, status: st, hora: new Date(min * 60_000),
    }));

    // aplica o rastro na ordem: cada posição só na escala corrente
    for (const pos of rastro) {
      for (let i = 0; i < escalas.length; i++) {
        const x = escalas[i];
        const evx = ev(x);
        if (evx.atd || evx.nao) continue;
        const porto = e.portos[x.porto];
        const raioF = porto.raio_fundeio_nm ?? cfg.raio_fundeio_nm;
        const raioB = porto.raio_berco_nm ?? cfg.raio_berco_nm;
        const d = milhas(pos.lat, pos.lon, porto.lat, porto.lon);
        if (!evx.ata && i + 1 < escalas.length && x.eta && pos.hora > x.eta) {
          const prox = e.portos[escalas[i + 1].porto];
          if (d > raioF && milhas(pos.lat, pos.lon, prox.lat, prox.lon) < milhas(porto.lat, porto.lon, prox.lat, prox.lon) - raioF) {
            evx.nao = pos.hora;
            continue;
          }
        }
        const sog = pos.sog ?? 0;
        if (!evx.ata && d <= raioF) evx.ata = pos.hora;
        if (evx.ata && !evx.atb && d <= raioB && (sog < cfg.sog_parado || pos.status === 5)) evx.atb = pos.hora;
        if (evx.atb && !evx.atd && (d > raioB + 1 || sog > cfg.sog_saida)) evx.atd = pos.hora;
        break;
      }
    }

    const pos = rastro.at(-1) ?? null;
    const idadeH = pos ? (+agora - +pos.hora) / H : null;
    const sinalOk = idadeH != null && idadeH <= cfg.sinal_valido_h;
    const desvio = (est: Date | null, prog: Date | null) => (est && prog ? Math.round(((+est - +prog) / H) * 10) / 10 : null);
    const somar = (base: Date | null, de: Date | null, ate: Date | null) => (base && de && ate ? new Date(+base + (+ate - +de)) : null);
    const iso = (d: Date | null | undefined) => (d ? d.toISOString() : null);

    const saida: Escala[] = [];
    let etsAntEst: Date | null = null, etsAntProg: Date | null = null, proximoDefinido = false;
    for (const x of todas) {
      const p = e.portos[x.porto];
      const evx = x.omitido ? {} as ReturnType<typeof ev> : ev(x);
      const { ata = null, atb = null, atd = null } = evx;
      const nao = Boolean(evx.nao);

      let etaEst: Date | null = null;
      let base: Escala["base_previsao"] = null;
      if (x.omitido || nao) { /* sem estimativa */ }
      else if (ata) { etaEst = ata; base = "real"; }
      else if (sinalOk && pos && !proximoDefinido) {
        const dist = milhas(pos.lat, pos.lon, p.lat, p.lon) * (p.fator_rota ?? cfg.fator_rota);
        let vel = pos.sog ?? 0;
        if (vel < cfg.sog_parado) { vel = cfg.velocidade_padrao_nos; base = "velocidade_padrao"; }
        else base = "velocidade_ais";
        etaEst = new Date(Math.max(+pos.hora + (dist / vel) * H, +agora));
      } else if (etsAntEst && etsAntProg && x.eta) {
        etaEst = new Date(+etsAntEst + (+x.eta - +etsAntProg)); base = "encadeado";
      }
      const etbEst: Date | null = atb ?? somar(etaEst, x.eta, x.etb);
      const etsEst: Date | null = atd ?? somar(etbEst, x.etb, x.ets);

      let situacao: SituacaoEscala;
      if (x.omitido) situacao = "omitido";
      else if (nao) situacao = "nao_observado";
      else if (atd) situacao = "saiu";
      else if (atb) situacao = "atracado";
      else if (ata) situacao = "fundeado";
      else if (x.ets && +agora > +x.ets + cfg.omissao_h * H) situacao = "possivel_omissao";
      else if (!mmsi) situacao = "sem_mmsi";
      else if (!sinalOk && base !== "encadeado") situacao = "sem_sinal";
      else {
        const d = desvio(etaEst, x.eta);
        situacao = d == null ? "sem_dado" : d > cfg.tolerancia_h ? "atrasado" : d < -cfg.tolerancia_h ? "adiantado" : "no_prazo";
      }

      saida.push({
        porto: x.porto, porto_nome: p.nome, viagem: x.viagem,
        programado: { eta: iso(x.eta), etb: iso(x.etb), ets: iso(x.ets) },
        estimado: { eta: iso(etaEst), etb: iso(etbEst), ets: iso(etsEst) },
        real: { ata: iso(ata), atb: iso(atb), atd: iso(atd) },
        desvio_h: { eta: desvio(etaEst, x.eta), etb: desvio(etbEst, x.etb), ets: desvio(etsEst, x.ets) },
        base_previsao: base,
        situacao,
      });
      if (!x.omitido && !nao) {
        if (!atd && situacao !== "possivel_omissao") proximoDefinido = true;
        etsAntEst = etsEst ?? etsAntEst;
        etsAntProg = x.ets ?? etsAntProg;
      }
    }

    const imo = todas.find((x) => x.imo)?.imo ?? "";
    navios.push({
      navio: nome, imo, mmsi,
      armador: e.armadorPorImo.get(imo) ?? null,
      posicao: pos ? { lat: pos.lat, lon: pos.lon, sog: pos.sog, hora: pos.hora.toISOString() } : null,
      sinal_idade_h: idadeH == null ? null : Math.round(idadeH * 10) / 10,
      escalas: saida,
    });
  }

  return {
    gerado_em: e.rastros.gerado_em,
    tolerancia_h: cfg.tolerancia_h,
    avisos,
    portos: e.portos,
    regras: cfg,
    navios,
  };
}
