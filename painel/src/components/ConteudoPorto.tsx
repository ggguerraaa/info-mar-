"use client";

import { useState } from "react";
import {
  AVISO_NAVEGACAO, dataCurta, fmt, haQuantoTempo, horaCurta, idadeTexto,
  type NavioPerto, type PainelPorto,
} from "@/lib/api";
import CurvaMare from "./CurvaMare";
import { IconeSeta } from "./Icones";

// Conteúdo do painel do porto (o mesmo no mapa e na página do porto).
// Cada bloco diz a fonte e há quanto tempo foi obtido; sem fonte = "sem dado".

const OPERACAO: Record<string, string> = {
  navegacao_canal: "Navegação no canal",
  atracacao: "Atracação",
  carga: "Operação de carga",
  fechamento_barra: "Fechamento da barra",
};

function Bloco({ titulo, children, fonte }: { titulo: string; children: React.ReactNode; fonte?: React.ReactNode }) {
  return (
    <section className="secao">
      <h3>{titulo}</h3>
      <div className="secao-corpo">{children}</div>
      {fonte && <p className="fonte">{fonte}</p>}
    </section>
  );
}

function ListaNavios({ titulo, navios, onNavio, extra }: {
  titulo: string; navios: NavioPerto[]; onNavio?: (mmsi: string) => void; extra?: (n: NavioPerto) => string;
}) {
  const [aberto, setAberto] = useState(false);
  if (!navios.length) return null;
  return (
    <div className="grupo-navios">
      <button className="dobra" onClick={() => setAberto((a) => !a)} aria-expanded={aberto}>
        <span>{titulo} <strong>{navios.length}</strong></span>
        <IconeSeta para={aberto ? "cima" : "baixo"} />
      </button>
      {aberto && (
        <ul className="lista-simples">
          {navios.map((n) => (
            <li key={n.mmsi}>
              {onNavio ? (
                <button className="link-linha" onClick={() => onNavio(n.mmsi)}>{n.nome ?? `MMSI ${n.mmsi}`}</button>
              ) : (n.nome ?? `MMSI ${n.mmsi}`)}
              <span className="fonte"> · {extra ? extra(n) : `${fmt(n.distancia_km, 1, " km")} · ${idadeTexto(n.idade_s)}`}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export default function ConteudoPorto({ dados, onNavio }: { dados: PainelPorto; onNavio?: (mmsi: string) => void }) {
  const { indice, mare, tempo, barra, calado, navios, rio } = dados;
  const totalArea = navios.atracados.length + navios.fundeados.length + navios.parados.length + navios.em_movimento.length;

  return (
    <div className="conteudo-porto">
      <Bloco titulo="Índice operacional">
        {indice.valor != null ? (
          <>
            <div className="linha-titulo">
              <span className="valor">{indice.valor} de 100</span>
              <span className="nota">calculado {haQuantoTempo(indice.calculado_em)}</span>
            </div>
            <div className="barra-indice" aria-hidden="true"><div style={{ width: `${indice.valor}%` }} /></div>
          </>
        ) : (
          <p><span className="valor vazio">Sem dado.</span> <span className="nota">{indice.motivo}</span></p>
        )}
        {indice.explicacao && (
          <details className="explica">
            <summary>Como é calculado</summary>
            <p className="nota">{indice.explicacao}</p>
          </details>
        )}
      </Bloco>

      {dados.modelo === "nivel_rio" ? (
        <Bloco
          titulo="Cota do Rio Negro"
          fonte={rio?.disponivel ? <>Fonte: <a href={rio.fonte} rel="noopener noreferrer" target="_blank">{rio.fonte.includes("ana.gov") ? "ANA, telemetria (estação 14990000)" : "Porto de Manaus"}</a>, leitura de {rio.data_leitura}, consultada {haQuantoTempo(rio.coletado_em)}. Porto fluvial: sem maré.</> : "Porto fluvial: sem maré."}
        >
          {rio?.disponivel ? (
            <div className="metricas">
              <div><div className="rotulo">Cota agora</div><div className="valor">{fmt(rio.cota_m, 2, " m")}</div></div>
              <div><div className="rotulo">Variação em 24 h</div><div className="valor">{rio.variacao_cm != null ? `${rio.variacao_cm > 0 ? "+" : ""}${fmt(rio.variacao_cm, 0, " cm")}` : "sem dado"}</div>
                <div className="nota">{rio.tendencia ?? ""}</div></div>
            </div>
          ) : <p className="nota">Sem dado: a ANA e o site do Porto de Manaus não responderam. Tente de novo em alguns minutos.</p>}
        </Bloco>
      ) : (
        <Bloco titulo="Maré" fonte={mare ? `Fonte: ${mare.fonte ?? "tábua DHN"}. Hora de Brasília.` : undefined}>
          {mare ? (
            <>
              <div className="metricas tres">
                <div>
                  <div className="rotulo">Agora</div>
                  <div className="valor">
                    {fmt(mare.altura_m, 2, " m")}{" "}
                    {mare.subindo != null && <span aria-label={mare.subindo ? "subindo" : "descendo"}>{mare.subindo ? "↑" : "↓"}</span>}
                  </div>
                  <div className="nota">{mare.subindo == null ? "" : mare.subindo ? "enchendo" : "vazando"}</div>
                </div>
                <div>
                  <div className="rotulo">Próxima alta</div>
                  <div className="valor">{mare.proxima_alta ? horaCurta(mare.proxima_alta.horario) : "sem dado"}</div>
                  <div className="nota">{mare.proxima_alta ? fmt(mare.proxima_alta.altura_m, 2, " m") : ""}</div>
                </div>
                <div>
                  <div className="rotulo">Próxima baixa</div>
                  <div className="valor">{mare.proxima_baixa ? horaCurta(mare.proxima_baixa.horario) : "sem dado"}</div>
                  <div className="nota">{mare.proxima_baixa ? fmt(mare.proxima_baixa.altura_m, 2, " m") : ""}</div>
                </div>
              </div>
              <CurvaMare curva={mare.curva_hoje} horaAtual={mare.hora_atual} />
            </>
          ) : <p className="nota">Sem dado: não há tábua de maré para hoje neste porto.</p>}
        </Bloco>
      )}

      <Bloco
        titulo={dados.modelo === "nivel_rio" ? "Vento" : "Vento e ondas"}
        fonte={tempo ? `Fonte: ${tempo.fonte}, obtida ${haQuantoTempo(tempo.obtido_em)}.` : undefined}
      >
        {tempo ? (
          <>
            <div className="metricas">
              <div>
                <div className="rotulo">Vento agora</div>
                <div className="valor">{fmt(tempo.vento_kn, 0, " nós")}{tempo.vento_direcao ? `, ${tempo.vento_direcao}` : ""}</div>
                <div className="nota">{tempo.rajada_kn != null ? `rajadas de ${fmt(tempo.rajada_kn, 0, " nós")}` : ""}</div>
              </div>
              {dados.modelo === "mare" && (
                <div>
                  <div className="rotulo">Ondas agora</div>
                  <div className="valor">{fmt(tempo.onda_m, 1, " m")}{tempo.onda_direcao ? `, ${tempo.onda_direcao}` : ""}</div>
                  <div className="nota">{tempo.onda_periodo_s != null ? `período de ${fmt(tempo.onda_periodo_s, 0, " s")}` : ""}</div>
                </div>
              )}
            </div>
            {tempo.proximas_horas.length > 1 && (
              <div className="tabela-rolagem">
                <table className="tabela compacta">
                  <caption className="sr-only">Previsão para as próximas horas</caption>
                  <thead>
                    <tr><th scope="col">Hora</th><th scope="col">Vento</th><th scope="col">Rajada</th>{dados.modelo === "mare" && <th scope="col">Onda</th>}</tr>
                  </thead>
                  <tbody>
                    {tempo.proximas_horas.filter((_, i) => i % 3 === 0).slice(0, 5).map((h) => (
                      <tr key={h.hora}>
                        <td>{h.hora.replace(":", "h")}</td>
                        <td>{fmt(h.vento_kn, 0, " nós")}</td>
                        <td>{fmt(h.rajada_kn, 0, " nós")}</td>
                        {dados.modelo === "mare" && <td>{fmt(h.onda_m, 1, " m")}</td>}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : <p className="nota">Sem dado: o Open-Meteo não respondeu. Tente de novo em alguns minutos.</p>}
      </Bloco>

      {dados.modelo === "mare" && (
        <Bloco
          titulo="Barra"
          fonte={barra.disponivel && barra.situacao ? <>Fonte: <a href={barra.fonte ?? "#"} rel="noopener noreferrer" target="_blank">praticagem</a>, consultada {haQuantoTempo(barra.coletado_em)}{barra.desde ? ` (${barra.desde})` : ""}.</> : undefined}
        >
          {!barra.disponivel ? (
            <p><span className="valor vazio">Sem dado.</span> <span className="nota">Não há fonte pública da praticagem para este porto.</span></p>
          ) : barra.situacao ? (
            <p className="valor">{barra.fechada ? <span className="selo grave">Fechada</span> : <span className="selo normal">Aberta</span>} <span className="nota">“{barra.situacao}”</span></p>
          ) : <p className="nota">Sem dado: a página da praticagem não respondeu na última consulta.</p>}
        </Bloco>
      )}

      {(
        <Bloco titulo={dados.modelo === "nivel_rio" ? "Calado nos berços" : "Calado e limites"}>
          {calado ? (
            <>
              <p><span className="valor">Calado máximo {fmt(calado.calado_maximo_m, 2, " m")}</span></p>
              {calado.canal && <p className="nota">{calado.canal}</p>}
              {dados.modelo === "nivel_rio" && calado.bercos && <p className="nota">{calado.bercos}</p>}
              {calado.confianca && <p className="nota">Confiança: {calado.confianca}</p>}
              <p className="fonte">
                Fonte: {calado.fonte?.startsWith("http") ? <a href={calado.fonte} rel="noopener noreferrer" target="_blank">{dados.modelo === "nivel_rio" ? "Porto de Manaus" : "página oficial"}</a> : calado.fonte}
                {dados.modelo === "nivel_rio"
                  ? `, referente à leitura de ${dataCurta(calado.verificado_em)}. Muda com o nível do rio.`
                  : `, verificada em ${dataCurta(calado.verificado_em)}. Calado muda com dragagem.`}
              </p>
            </>
          ) : <p><span className="valor vazio">Sem dado.</span> <span className="nota">Nenhuma fonte pública de calado foi encontrada para este porto.</span></p>}
          {dados.limites.length > 0 && (
            <ul className="lista-simples">
              {dados.limites.map((l, i) => (
                <li key={i}>
                  <strong>{OPERACAO[l.operacao] ?? l.operacao}</strong>
                  {l.aplica_a && l.aplica_a !== "todos" ? ` (${l.aplica_a})` : ""}:{" "}
                  {[l.vento_kn != null && `vento até ${l.vento_kn} nós`, l.onda_hs_m != null && `onda até ${fmt(l.onda_hs_m, 1, " m")}`,
                    l.visibilidade_mn != null && `visibilidade mín. ${fmt(l.visibilidade_mn, 1, " MN")}`,
                    l.mare_minima_m != null && `maré mín. ${fmt(l.mare_minima_m, 1, " m")}`].filter(Boolean).join(", ")}
                  <div className="fonte">{l.documento}, {dataCurta(l.data_documento)}; confiança {l.confianca}.</div>
                </li>
              ))}
            </ul>
          )}
          {dados.modelo === "mare" && (
            <p className="nota">Calculadora de calado desligada: falta a profundidade do canal referida ao nível de redução.</p>
          )}
        </Bloco>
      )}

      <Bloco
        titulo="Navios"
        fonte={`Fonte: ${navios.fonte}. Raio de ${navios.raio_km} km da coordenada do porto; situação informada pelo próprio navio.`}
      >
        {totalArea + navios.a_caminho.length === 0 ? (
          <p className="nota">Nenhum navio com posição nas últimas 6 h perto do porto. A cobertura depende das antenas terrestres.</p>
        ) : (
          <>
            <div className="metricas">
              <div><div className="rotulo">Na área do porto</div><div className="valor">{totalArea}</div></div>
              <div><div className="rotulo">A caminho</div><div className="valor">{navios.a_caminho.length}</div></div>
            </div>
            <ListaNavios titulo="Atracados" navios={navios.atracados} onNavio={onNavio} />
            <ListaNavios titulo="Fundeados" navios={navios.fundeados} onNavio={onNavio} />
            <ListaNavios titulo="Parados" navios={navios.parados} onNavio={onNavio} />
            <ListaNavios titulo="Em movimento" navios={navios.em_movimento} onNavio={onNavio} />
            <ListaNavios titulo="A caminho (destino informado)" navios={navios.a_caminho} onNavio={onNavio}
              extra={(n) => `${fmt(n.distancia_km, 0, " km")}${n.eta_informada ? ` · ETA ${n.eta_informada.slice(3, 5)}/${n.eta_informada.slice(0, 2)} ${n.eta_informada.slice(6)} UTC` : ""}`} />
          </>
        )}
      </Bloco>

      <p className="aviso-navegacao" role="note">{AVISO_NAVEGACAO}</p>
    </div>
  );
}
