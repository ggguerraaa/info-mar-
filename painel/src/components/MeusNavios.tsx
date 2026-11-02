"use client";

import { useEffect, useRef, useState } from "react";
import { buscarJson, fmt, idadeTexto, situacaoNavio, SINAL_RECENTE_S } from "@/lib/api";
import {
  armazenamentoDisponivel, exportarArquivo, importarArquivo, removerNavio, useNaviosSalvos,
} from "@/lib/naviosSalvos";
import { IconeFechar, IconeSeta } from "./Icones";

interface Situacao {
  mmsi: string;
  nome: string | null;
  imo: string | null;
  destino_informado: string | null;
  status_codigo: number | null;
  velocidade_nos: number | null;
  latitude: number | null;
  longitude: number | null;
  idade_s: number | null;
}

export default function MeusNavios({
  selecionado,
  onEscolher,
}: {
  selecionado: string | null;
  onEscolher: (mmsi: string, lon: number | null, lat: number | null) => void;
}) {
  const salvos = useNaviosSalvos();
  const [situacoes, setSituacoes] = useState<Record<string, Situacao>>({});
  const [recolhido, setRecolhido] = useState(false);
  const [aviso, setAviso] = useState("");
  const arquivo = useRef<HTMLInputElement>(null);
  const chave = salvos.map((n) => n.mmsi).join(",");

  useEffect(() => {
    if (!chave) return;
    const controle = new AbortController();
    async function carregar() {
      try {
        const lista = await buscarJson<Situacao[]>(`/api/navios/lote?mmsi=${chave}`, controle.signal);
        setSituacoes(Object.fromEntries(lista.map((s) => [s.mmsi, s])));
      } catch {
        // mantém a última situação conhecida; a idade continua visível
      }
    }
    carregar();
    const intervalo = setInterval(carregar, 30_000);
    return () => {
      controle.abort();
      clearInterval(intervalo);
    };
  }, [chave]);

  function exportar() {
    const url = URL.createObjectURL(exportarArquivo());
    const a = document.createElement("a");
    a.href = url;
    a.download = `meus-navios-${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    setAviso(`Lista exportada com ${salvos.length} navio(s).`);
  }

  async function importar(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0];
    e.target.value = "";
    if (!f) return;
    try {
      const novos = await importarArquivo(f);
      setAviso(novos ? `${novos} navio(s) importado(s).` : "Nenhum navio novo no arquivo: todos já estavam na lista.");
    } catch (erro) {
      setAviso((erro as Error).message);
    }
  }

  return (
    <section className="painel flutua doca-item" aria-labelledby="meus-navios-titulo">
      <header className="doca-cabeca">
        <div className="doca-titulo">
          <h2 id="meus-navios-titulo">Meus navios</h2>
          <p className="nota">{salvos.length ? `${salvos.length} salvo(s) neste navegador` : "Salvos neste navegador"}</p>
        </div>
        <button className="icone-botao" onClick={() => setRecolhido((r) => !r)} aria-expanded={!recolhido}
          aria-label={recolhido ? "Expandir Meus navios" : "Recolher Meus navios"}>
          <IconeSeta para={recolhido ? "baixo" : "cima"} />
        </button>
      </header>

      {!recolhido && (
        <div className="doca-corpo">
          {!armazenamentoDisponivel() && (
            <p className="nota" role="alert">
              Este navegador não deixa guardar dados (aba anônima ou bloqueio). A lista vale só nesta aba: exporte antes de fechar.
            </p>
          )}
          {salvos.length === 0 ? (
            <p className="nota">Busque um navio pelo nome, MMSI ou IMO e toque em “Salvar em Meus navios”.</p>
          ) : (
            <div className="tabela-rolagem">
              <table className="tabela">
                <caption className="sr-only">Navios salvos, com situação e idade da última posição</caption>
                <thead>
                  <tr>
                    <th scope="col">Navio</th>
                    <th scope="col">Situação</th>
                    <th scope="col">Destino</th>
                    <th scope="col"><span className="sr-only">Remover</span></th>
                  </tr>
                </thead>
                <tbody>
                  {salvos.map((n) => {
                    const s = situacoes[n.mmsi];
                    const semSinal = !s || s.idade_s == null || s.idade_s > SINAL_RECENTE_S;
                    const nome = s?.nome ?? n.nome ?? `MMSI ${n.mmsi}`;
                    return (
                      <tr key={n.mmsi} aria-current={selecionado === n.mmsi ? "true" : undefined}>
                        <td>
                          <button className="link-linha" onClick={() => onEscolher(n.mmsi, s?.longitude ?? null, s?.latitude ?? null)}>
                            {nome}
                          </button>
                          <div className="fonte">MMSI {n.mmsi} · IMO {s?.imo ?? n.imo ?? "—"}</div>
                        </td>
                        <td>
                          {!s ? <span className="vazio">carregando</span> : semSinal ? (
                            <span>{s.idade_s == null ? "Sem sinal" : `Sem sinal ${idadeTexto(s.idade_s)}`}</span>
                          ) : (
                            <>
                              {situacaoNavio(s.status_codigo, s.velocidade_nos)}
                              <div className="fonte">{fmt(s.velocidade_nos, 1, " nós")} · {idadeTexto(s.idade_s)}</div>
                            </>
                          )}
                        </td>
                        <td>{s?.destino_informado ?? <span className="vazio">—</span>}</td>
                        <td>
                          <button className="icone-botao" onClick={() => removerNavio(n.mmsi)} aria-label={`Remover ${nome} de Meus navios`}>
                            <IconeFechar />
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="acoes">
            <button className="botao" onClick={exportar} disabled={!salvos.length}>Exportar lista</button>
            <button className="botao" onClick={() => arquivo.current?.click()}>Importar lista</button>
            <input ref={arquivo} type="file" accept="application/json,.json" hidden onChange={importar} aria-hidden="true" tabIndex={-1} />
          </div>
          {aviso && <p className="nota" role="status">{aviso}</p>}
          <p className="fonte">Destino informado pela tripulação. Sem conta: a lista fica só neste navegador.</p>
        </div>
      )}
    </section>
  );
}
