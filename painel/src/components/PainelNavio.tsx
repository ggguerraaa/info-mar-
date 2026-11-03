"use client";

import { useEffect, useState } from "react";
import {
  buscarJson, ErroApi, fmt, haQuantoTempo, idadeTexto, situacaoNavio, SINAL_RECENTE_S, type CardNavio,
} from "@/lib/api";
import { atualizarNavio, removerNavio, salvarNavio, useNaviosSalvos } from "@/lib/naviosSalvos";
import { IconeFechar, IconeSeta } from "./Icones";

// "MM-DD HH:MM" (UTC, sem ano: limitação do AIS) -> "18/11 06:00 UTC"
function etaTexto(eta: string | null): string | null {
  const m = eta?.match(/^(\d{2})-(\d{2}) (\d{2}:\d{2})$/);
  return m ? `${m[2]}/${m[1]} ${m[3]} UTC` : eta;
}

function Linha({ rotulo, children }: { rotulo: string; children: React.ReactNode }) {
  return (
    <div>
      <dt>{rotulo}</dt>
      <dd>{children}</dd>
    </div>
  );
}

const semDado = <span className="vazio">sem dado</span>;

export default function PainelNavio({
  mmsi,
  pontosRastro,
  onFechar,
  onCentralizar,
}: {
  mmsi: string;
  pontosRastro: number | null;
  onFechar: () => void;
  onCentralizar: (lon: number, lat: number) => void;
}) {
  const [estado, setEstado] = useState<{ mmsi: string; card: CardNavio | null; erro: string | null } | null>(null);
  const [recolhido, setRecolhido] = useState(false);
  const [dadosAbertos, setDadosAbertos] = useState(true);
  const salvos = useNaviosSalvos();
  const salvo = salvos.some((n) => n.mmsi === mmsi);

  useEffect(() => {
    const controle = new AbortController();
    async function carregar() {
      try {
        const card = await buscarJson<CardNavio>(`/api/navios/${mmsi}`, controle.signal);
        setEstado({ mmsi, card, erro: null });
        atualizarNavio({ mmsi, nome: card.nome, imo: card.imo });
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        const msg = e instanceof ErroApi && e.status === 404
          ? "Este navio ainda não foi visto pelas antenas do AIS. Ele aparece quando transmitir perto da costa."
          : (e as Error).message;
        setEstado((atual) => (atual?.mmsi === mmsi && atual.card ? atual : { mmsi, card: null, erro: msg }));
      }
    }
    carregar();
    const intervalo = setInterval(carregar, 30_000);
    return () => {
      controle.abort();
      clearInterval(intervalo);
    };
  }, [mmsi]);

  const atual = estado?.mmsi === mmsi ? estado : null;
  const card = atual?.card ?? null;
  const p = card?.posicao ?? null;
  const situacao = p ? situacaoNavio(p.status_codigo, p.velocidade_nos) : "Sem dado";
  const semSinal = p?.idade_s != null && p.idade_s > SINAL_RECENTE_S;
  const titulo = card?.nome ?? `MMSI ${mmsi}`;

  return (
    <section className="painel flutua doca-item" aria-labelledby={`navio-${mmsi}`}>
      <header className="doca-cabeca">
        <div className="doca-titulo">
          <h2 id={`navio-${mmsi}`}>{titulo}</h2>
          <p className="nota">MMSI {mmsi}{card?.tipo ? ` · ${card.tipo}` : ""}</p>
        </div>
        <span className={situacao === "Em rota" ? "selo normal" : "selo"}>{semSinal ? "Sem sinal" : situacao}</span>
        <button className="icone-botao" onClick={() => setRecolhido((r) => !r)} aria-expanded={!recolhido}
          aria-label={recolhido ? `Expandir painel de ${titulo}` : `Recolher painel de ${titulo}`}>
          <IconeSeta para={recolhido ? "baixo" : "cima"} />
        </button>
        <button className="icone-botao" onClick={onFechar} aria-label={`Fechar painel de ${titulo}`}>
          <IconeFechar />
        </button>
      </header>

      {!recolhido && (
        <div className="doca-corpo">
          {!atual && <p className="nota" role="status">Carregando dados do navio…</p>}
          {atual?.erro && <p className="nota" role="alert">{atual.erro}</p>}
          {card && (
            <>
              <div className="metricas tres">
                <div><div className="rotulo">Velocidade</div><div className="valor">{p ? fmt(p.velocidade_nos, 1, " nós") : "sem dado"}</div></div>
                <div><div className="rotulo">Rumo</div><div className="valor">{p?.rumo != null ? `${Math.round(p.rumo)}°` : "sem dado"}</div></div>
                <div><div className="rotulo">Posição</div><div className="valor">{p ? idadeTexto(p.idade_s) : "sem dado"}</div></div>
              </div>

              <dl className="linhas">
                <Linha rotulo="Status de navegação">{p?.status ?? semDado}</Linha>
                <Linha rotulo="Destino (tripulação)">{card.destino_informado ?? semDado}</Linha>
                <Linha rotulo="ETA (tripulação)">{etaTexto(card.eta_informada) ?? semDado}</Linha>
                <Linha rotulo="Rastro de 24 h">
                  {pontosRastro == null ? "carregando" : pontosRastro > 1 ? `${pontosRastro} posições no mapa` : "sem posições gravadas"}
                </Linha>
              </dl>

              {semSinal && (
                <p className="nota">Sem sinal {idadeTexto(p?.idade_s)}. O navio pode estar longe das antenas terrestres ou com o AIS desligado.</p>
              )}

              <div className="secao">
                <button className="dobra" onClick={() => setDadosAbertos((a) => !a)} aria-expanded={dadosAbertos}>
                  <h3>Dados do navio</h3>
                  <IconeSeta para={dadosAbertos ? "cima" : "baixo"} />
                </button>
                {dadosAbertos && (
                  <dl className="linhas">
                    <Linha rotulo="IMO">{card.imo ?? "—"}</Linha>
                    <Linha rotulo="Indicativo">{card.indicativo ?? "—"}</Linha>
                    <Linha rotulo="Tipo">{card.tipo ?? semDado}</Linha>
                    <Linha rotulo="Dimensões">
                      {card.comprimento_m ? `${fmt(card.comprimento_m, 0)} × ${fmt(card.boca_m, 0)} m` : semDado}
                    </Linha>
                    <Linha rotulo="Calado informado">{card.calado_max_m ? fmt(card.calado_max_m, 1, " m") : semDado}</Linha>
                    <Linha rotulo="Bandeira (MID do MMSI)">{card.bandeira ?? semDado}</Linha>
                    <Linha rotulo="Armador">
                      {card.armador.nome ? <span title={`Fonte: ${card.armador.fonte}`}>{card.armador.nome}</span> : "não informado"}
                    </Linha>
                  </dl>
                )}
              </div>

              <div className="acoes">
                <button
                  className={salvo ? "botao" : "botao acao"}
                  onClick={() => (salvo ? removerNavio(mmsi) : salvarNavio({ mmsi, nome: card.nome, imo: card.imo }))}
                  aria-pressed={salvo}
                >
                  {salvo ? "Remover de Meus navios" : "Salvar em Meus navios"}
                </button>
                {p && (
                  <button className="botao" onClick={() => onCentralizar(p.longitude, p.latitude)}>Centralizar</button>
                )}
              </div>

              <p className="fonte">
                Fonte: {card.fonte}, posição {p ? haQuantoTempo(p.timestamp_utc) : "sem dado"}. Destino e ETA são
                digitados pela tripulação e podem estar desatualizados. Bandeira pela tabela MID da ITU, com o nome em português do Unicode CLDR.
              </p>
            </>
          )}
        </div>
      )}
    </section>
  );
}
