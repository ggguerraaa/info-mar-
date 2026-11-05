"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AVISO_NAVEGACAO, buscarJson, haQuantoTempo,
  type Escala, type NavioSchedule, type RespostaSchedule, type SituacaoEscala,
} from "@/lib/api";
import { IconeBusca } from "./Icones";

// Schedule programado (commit diário de schedule/schedule.csv) x real (AIS).
// "Real" é evento detectado no rastro; "estimado" é conta declarada na tela.

const ROTULO: Record<SituacaoEscala, string> = {
  no_prazo: "No prazo",
  atrasado: "Atrasado",
  adiantado: "Adiantado",
  fundeado: "Fundeado",
  atracado: "Atracado",
  saiu: "Saiu",
  omitido: "Omitido",
  possivel_omissao: "Possível omissão",
  nao_observado: "Passou sem sinal",
  sem_sinal: "Sem sinal AIS",
  sem_mmsi: "Sem MMSI",
  sem_dado: "Sem dado",
};

// Paleta do painel: só a "grave" usa o tom quente.
const CLASSE: Record<SituacaoEscala, string> = {
  no_prazo: "selo normal",
  atracado: "selo normal",
  fundeado: "selo atencao",
  adiantado: "selo atencao",
  atrasado: "selo grave",
  possivel_omissao: "selo grave",
  saiu: "selo",
  omitido: "selo",
  nao_observado: "selo",
  sem_sinal: "selo",
  sem_mmsi: "selo",
  sem_dado: "selo",
};

const BASE: Record<string, string> = {
  real: "evento real (AIS)",
  velocidade_ais: "distância ÷ velocidade AIS",
  velocidade_padrao: "navio parado: 12 nós de referência",
  encadeado: "atraso herdado da escala anterior",
};

const ORDEM_KPI: SituacaoEscala[] = ["atrasado", "no_prazo", "adiantado", "fundeado", "atracado", "possivel_omissao", "nao_observado", "sem_sinal", "sem_mmsi"];

const formatoData = new Intl.DateTimeFormat("pt-BR", {
  timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
});

function dataHora(iso: string | null): string {
  if (!iso) return "—";
  return formatoData.format(new Date(iso)).replace(",", "").replace(":", "h");
}

function desvioTexto(h: number | null, tolerancia: number) {
  if (h == null) return null;
  const abs = Math.abs(h);
  const txt = abs < 0.5 ? "±0 h" : `${h > 0 ? "+" : "−"}${abs >= 48 ? `${(abs / 24).toFixed(1).replace(".", ",")} d` : `${Math.round(abs)} h`}`;
  return <span className={h > tolerancia ? "desvio atraso" : "desvio"}>{txt}</span>;
}

function Celula({ rotulo, prog, est, real, desvio, tolerancia }: {
  rotulo: string; prog: string | null; est: string | null; real: string | null; desvio: number | null; tolerancia: number;
}) {
  return (
    <td data-rotulo={rotulo}>
      <span className="horario-prog">{dataHora(prog)}</span>
      <span className="horario-est">
        {real ? <span className="marca-real">real</span> : null}
        {dataHora(real ?? est)} {desvioTexto(desvio, tolerancia)}
      </span>
    </td>
  );
}

function situacaoAtual(n: NavioSchedule): SituacaoEscala {
  const e = n.escalas.find((x) => !["saiu", "omitido", "nao_observado"].includes(x.situacao)) ?? n.escalas.at(-1);
  return e?.situacao ?? "sem_dado";
}

export default function TelaSchedule() {
  const [dados, setDados] = useState<RespostaSchedule | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [filtro, setFiltro] = useState("");
  const [porto, setPorto] = useState("");
  const [situacao, setSituacao] = useState<SituacaoEscala | "">("");

  useEffect(() => {
    const controle = new AbortController();
    const carregar = () =>
      buscarJson<RespostaSchedule>("/api/schedule", controle.signal)
        .then((d) => { setDados(d); setErro(null); })
        .catch((e) => {
          if (e.name === "AbortError") return;
          setErro(e.status === 404 ? "O schedule ainda não foi gerado. Faça o commit de schedule/schedule.csv." : e.message);
        });
    carregar();
    const intervalo = setInterval(carregar, 120_000);
    return () => { controle.abort(); clearInterval(intervalo); };
  }, []);

  const contagem = useMemo(() => {
    const c: Partial<Record<SituacaoEscala, number>> = {};
    dados?.navios.forEach((n) => n.escalas.forEach((e) => { c[e.situacao] = (c[e.situacao] ?? 0) + 1; }));
    return c;
  }, [dados]);

  const portosUsados = useMemo(() => {
    const vistos = new Map<string, string>();
    dados?.navios.forEach((n) => n.escalas.forEach((e) => vistos.set(e.porto, e.porto_nome)));
    return [...vistos].sort((a, b) => a[1].localeCompare(b[1]));
  }, [dados]);

  const termo = filtro.trim().toUpperCase();
  const visiveis = (dados?.navios ?? []).filter((n) =>
    (!termo || `${n.navio} ${n.imo} ${n.mmsi}`.toUpperCase().includes(termo)) &&
    (!porto || n.escalas.some((e) => e.porto === porto)) &&
    (!situacao || n.escalas.some((e) => e.situacao === situacao)),
  );
  const tolerancia = dados?.tolerancia_h ?? 6;

  return (
    <div className="pagina">
      <div className="pagina-largura">
        <div className="cabecalho-pagina">
          <h1>Schedule</h1>
          <p className="nota" role="status">
            {dados ? `Atualizado ${haQuantoTempo(dados.gerado_em)} · nova leitura a cada ~30 min` : "Carregando…"}
          </p>
        </div>
        <p className="nota subtitulo">
          Programado (o schedule publicado) comparado com o que o AIS mostra. Real = evento visto no rastro do navio;
          estimado = conta explicada em cada linha. No prazo até ±{tolerancia} h.
        </p>

        {erro && <p className="painel aviso-erro" role="alert">{erro}</p>}
        {dados?.avisos.map((a) => <p key={a} className="painel aviso-erro">{a}</p>)}

        {dados && (
          <>
            <div className="kpis" role="group" aria-label="Filtrar por situação">
              <button className={situacao === "" ? "kpi ativo" : "kpi"} aria-pressed={situacao === ""} onClick={() => setSituacao("")}>
                <b>{dados.navios.length}</b><span>Navios</span>
              </button>
              {ORDEM_KPI.filter((s) => contagem[s]).map((s) => (
                <button key={s} className={situacao === s ? "kpi ativo" : "kpi"} aria-pressed={situacao === s}
                  onClick={() => setSituacao(situacao === s ? "" : s)}>
                  <b>{contagem[s]}</b><span>{ROTULO[s]}</span>
                </button>
              ))}
            </div>

            <div className="filtros-schedule">
              <div className="campo campo-filtro">
                <IconeBusca />
                <label htmlFor="filtro-navio" className="sr-only">Filtrar por navio, IMO ou MMSI</label>
                <input id="filtro-navio" type="search" placeholder="Navio, IMO ou MMSI" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
              </div>
              <label className="sr-only" htmlFor="filtro-porto">Porto</label>
              <select id="filtro-porto" className="seletor" value={porto} onChange={(e) => setPorto(e.target.value)}>
                <option value="">Todos os portos</option>
                {portosUsados.map(([slug, nome]) => <option key={slug} value={slug}>{nome}</option>)}
              </select>
            </div>

            <div className="lista-schedule">
              {visiveis.map((n) => (
                <section key={n.navio} className="painel navio-schedule" aria-labelledby={`n-${n.navio}`}>
                  <div className="navio-schedule-cabeca">
                    <div>
                      <h2 id={`n-${n.navio}`}>{n.navio}</h2>
                      <p className="nota">
                        {n.imo ? `IMO ${n.imo} · ` : ""}
                        {n.escalas[0]?.viagem ? `Viagem ${n.escalas[0].viagem} · ` : ""}
                        {n.posicao ? `AIS ${haQuantoTempo(n.posicao.hora)}${n.posicao.sog != null ? `, ${n.posicao.sog.toFixed(1).replace(".", ",")} nós` : ""}` : "sem posição AIS"}
                      </p>
                    </div>
                    <div className="acoes">
                      <span className={CLASSE[situacaoAtual(n)]}>{ROTULO[situacaoAtual(n)]}</span>
                      {n.mmsi && n.posicao && <Link href={`/?navio=${n.mmsi}`} className="link-acao">Ver no mapa</Link>}
                    </div>
                  </div>
                  <div className="tabela-rolagem">
                    <table className="tabela tabela-schedule">
                      <caption className="sr-only">Escalas de {n.navio}: programado e estimado ou real</caption>
                      <thead>
                        <tr>
                          <th scope="col">Porto</th>
                          <th scope="col">ETA <span className="nota">prog. / est.</span></th>
                          <th scope="col">ETB <span className="nota">prog. / est.</span></th>
                          <th scope="col">ETS <span className="nota">prog. / est.</span></th>
                          <th scope="col">Situação</th>
                        </tr>
                      </thead>
                      <tbody>
                        {n.escalas.filter((e) => !porto || e.porto === porto).map((e: Escala) => (
                          <tr key={`${e.porto}-${e.viagem}`}>
                            <th scope="row" data-rotulo="Porto">{e.porto_nome}</th>
                            <Celula rotulo="ETA" prog={e.programado.eta} est={e.estimado.eta} real={e.real.ata} desvio={e.desvio_h.eta} tolerancia={tolerancia} />
                            <Celula rotulo="ETB" prog={e.programado.etb} est={e.estimado.etb} real={e.real.atb} desvio={e.desvio_h.etb} tolerancia={tolerancia} />
                            <Celula rotulo="ETS" prog={e.programado.ets} est={e.estimado.ets} real={e.real.atd} desvio={e.desvio_h.ets} tolerancia={tolerancia} />
                            <td data-rotulo="Situação">
                              <span className={CLASSE[e.situacao]}>{ROTULO[e.situacao]}</span>
                              {e.base_previsao && e.base_previsao !== "real" && <span className="fonte base-previsao">{BASE[e.base_previsao]}</span>}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ))}
              {visiveis.length === 0 && <p className="nota">Nenhum navio com esses filtros.</p>}
            </div>
          </>
        )}

        <p className="fonte rodape-pagina">
          Horários em Brasília. Chegada = entrou no raio de fundeio do porto; atracação = parado junto ao porto; saída =
          deixou o porto. Estimativa por linha reta × fator de rota, sem fila, maré ou praticagem. Cobertura só de antenas
          terrestres: escala sem sinal aparece como “passou sem sinal”.
        </p>
        <p className="aviso-navegacao">{AVISO_NAVEGACAO}</p>
      </div>
    </div>
  );
}
