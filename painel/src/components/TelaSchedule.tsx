"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AVISO_NAVEGACAO, buscarFrota, buscarJson, haQuantoTempo, mapaImoMmsi,
  type Escala, type NavioSchedule, type RespostaFrota, type RespostaRastros, type RespostaSchedule, type SituacaoEscala,
} from "@/lib/api";
import { analisarScheduleLocal } from "@/lib/scheduleLocal";
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

const CHAVE_ARQUIVO = "info-mare:schedule-csv";

function lerArquivoSalvo(): { nome: string; texto: string } | null {
  try {
    const bruto = localStorage.getItem(CHAVE_ARQUIVO);
    return bruto ? JSON.parse(bruto) : null;
  } catch {
    return null;
  }
}

export default function TelaSchedule() {
  const [publicado, setPublicado] = useState<RespostaSchedule | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [filtro, setFiltro] = useState("");
  const [porto, setPorto] = useState("");
  const [situacao, setSituacao] = useState<SituacaoEscala | "">("");
  const [armador, setArmador] = useState("");
  const [frota, setFrota] = useState<RespostaFrota | null>(null);
  // CSV que a pessoa arrastou: fica só neste navegador
  const [arquivo, setArquivo] = useState<{ nome: string; texto: string } | null>(null);
  const [fonte, setFonte] = useState<"publicado" | "arquivo">("publicado");
  const [analise, setAnalise] = useState<{ de: { nome: string; texto: string }; dados: RespostaSchedule } | null>(null);
  const [arrastando, setArrastando] = useState(false);

  // localStorage só existe no navegador (a página é gerada estática)
  useEffect(() => {
    Promise.resolve().then(() => {
      const salvo = lerArquivoSalvo();
      if (salvo) { setArquivo(salvo); setFonte("arquivo"); }
    });
  }, []);

  useEffect(() => {
    const controle = new AbortController();
    const carregar = () => {
      buscarJson<RespostaSchedule>("/api/schedule", controle.signal)
        .then((d) => { setPublicado(d); setErro(null); })
        .catch((e) => {
          if (e.name === "AbortError") return;
          setErro(e.status === 404 ? "O schedule publicado ainda não foi gerado." : e.message);
        });
      buscarFrota().then(setFrota).catch(() => {});
    };
    carregar();
    const intervalo = setInterval(carregar, 120_000);
    return () => { controle.abort(); clearInterval(intervalo); };
  }, []);

  // Análise do CSV no navegador, com os rastros publicados
  useEffect(() => {
    if (!arquivo || !publicado) return;
    let vivo = true;
    (async () => {
      try {
        const [rastros, imoParaMmsi, fr] = await Promise.all([
          buscarJson<RespostaRastros>("/api/rastros"), mapaImoMmsi(), buscarFrota().catch(() => null),
        ]);
        const armadorPorImo = new Map<string, string>();
        for (const n of fr?.navios ?? []) {
          armadorPorImo.set(n.imo, n.armador);
          if (n.mmsi && !imoParaMmsi.has(n.imo)) imoParaMmsi.set(n.imo, n.mmsi);
        }
        const r = analisarScheduleLocal({
          csv: arquivo.texto, portos: publicado.portos, regras: publicado.regras, rastros, imoParaMmsi, armadorPorImo,
        });
        if (vivo) setAnalise({ de: arquivo, dados: r });
      } catch (e) {
        if (vivo) setErro(`Não deu para analisar o arquivo: ${(e as Error).message}`);
      }
    })();
    return () => { vivo = false; };
  }, [arquivo, publicado]);

  async function receberArquivo(f: File | undefined) {
    if (!f) return;
    if (f.size > 2_000_000) { setErro("Arquivo grande demais (máx. 2 MB). Exporte só as colunas do schedule em CSV."); return; }
    const texto = await f.text();
    const novo = { nome: f.name, texto };
    setArquivo(novo);
    setFonte("arquivo");
    setErro(null);
    try { localStorage.setItem(CHAVE_ARQUIVO, JSON.stringify(novo)); } catch { /* sem armazenamento: vale só nesta aba */ }
  }

  function esquecerArquivo() {
    setArquivo(null);
    setAnalise(null);
    setFonte("publicado");
    try { localStorage.removeItem(CHAVE_ARQUIVO); } catch { /* nada */ }
  }

  const local = analise && analise.de === arquivo ? analise.dados : null;
  const dados = fonte === "arquivo" ? local : publicado;

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
    (!armador || (armador === "frota" ? Boolean(n.armador) : n.armador === armador)) &&
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
          Programado (o schedule publicado no projeto ou o arquivo que você arrastar) comparado com o que o AIS mostra. Real = evento visto no rastro do navio;
          estimado = conta explicada em cada linha. No prazo até ±{tolerancia} h.
        </p>

        <div className={arrastando ? "painel carregar-csv arrastando" : "painel carregar-csv"}
          onDragOver={(e) => { e.preventDefault(); setArrastando(true); }}
          onDragLeave={() => setArrastando(false)}
          onDrop={(e) => { e.preventDefault(); setArrastando(false); receberArquivo(e.dataTransfer.files[0]); }}>
          <div className="fontes-schedule" role="group" aria-label="Qual schedule mostrar">
            <button className={fonte === "publicado" ? "chip ligado" : "chip"} aria-pressed={fonte === "publicado"}
              onClick={() => setFonte("publicado")}>Schedule publicado</button>
            <button className={fonte === "arquivo" ? "chip ligado" : "chip"} aria-pressed={fonte === "arquivo"}
              disabled={!arquivo} onClick={() => setFonte("arquivo")}>
              {arquivo ? `Meu arquivo: ${arquivo.nome}` : "Meu arquivo"}
            </button>
          </div>
          <p className="nota">
            Arraste aqui o CSV do seu schedule, de qualquer armador, ou{" "}
            <label className="link-acao escolher-arquivo">
              escolha o arquivo
              <input type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => receberArquivo(e.target.files?.[0])} />
            </label>
            . A comparação é feita no seu navegador, e o arquivo não é enviado para lugar nenhum.
            {arquivo && <> <button className="link-acao botao-link" onClick={esquecerArquivo}>Esquecer arquivo</button></>}
          </p>
          <p className="fonte">
            Colunas: navio;imo;mmsi;viagem;porto;eta;etb;ets;omitido, com datas dd/mm/aaaa hh:mm em horário de Brasília.
            O rastro publicado cobre 7 dias para a frota em destaque e 3 dias para os demais navios.
          </p>
        </div>

        {erro && <p className="painel aviso-erro" role="alert">{erro}</p>}
        {fonte === "arquivo" && arquivo && !local && !erro && <p className="nota" role="status">Analisando o arquivo…</p>}
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
              {frota && frota.armadores.length > 0 && (
                <>
                  <label className="sr-only" htmlFor="filtro-armador-schedule">Armador</label>
                  <select id="filtro-armador-schedule" className="seletor" value={armador} onChange={(e) => setArmador(e.target.value)}>
                    <option value="">Todos os armadores</option>
                    <option value="frota">Só a frota em destaque</option>
                    {frota.armadores.map((a) => <option key={a.id} value={a.id}>{a.nome}</option>)}
                  </select>
                </>
              )}
            </div>

            <div className="lista-schedule">
              {visiveis.map((n) => (
                <section key={n.navio} className="painel navio-schedule" aria-labelledby={`n-${n.navio}`}>
                  <div className="navio-schedule-cabeca">
                    <div>
                      <h2 id={`n-${n.navio}`}>
                        {n.armador && frota && (
                          <i className="cor-armador titulo-cor" aria-hidden="true"
                            style={{ background: frota.armadores.find((a) => a.id === n.armador)?.cor }} />
                        )}
                        {n.navio}
                      </h2>
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
