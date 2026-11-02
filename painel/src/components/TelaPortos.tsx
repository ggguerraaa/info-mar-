"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AVISO_NAVEGACAO, buscarJson, classeSituacao, fmt, type ResumoPorto } from "@/lib/api";
import { IconeBusca } from "./Icones";

const semAcento = (t: string) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export default function TelaPortos() {
  const [linhas, setLinhas] = useState<ResumoPorto[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [filtro, setFiltro] = useState("");

  useEffect(() => {
    const controle = new AbortController();
    buscarJson<ResumoPorto[]>("/api/portos/resumo", controle.signal)
      .then(setLinhas)
      .catch((e) => { if (e.name !== "AbortError") setErro(e.message); });
    return () => controle.abort();
  }, []);

  const visiveis = (linhas ?? []).filter((p) => semAcento(`${p.porto} ${p.estado}`).includes(semAcento(filtro.trim())));

  return (
    <div className="pagina">
      <div className="pagina-largura">
        <div className="cabecalho-pagina">
          <h1>Portos</h1>
          <div className="campo campo-filtro">
            <IconeBusca />
            <label htmlFor="filtro-portos" className="sr-only">Filtrar portos pelo nome</label>
            <input id="filtro-portos" type="search" placeholder="Filtrar portos" value={filtro} onChange={(e) => setFiltro(e.target.value)} />
          </div>
        </div>

        {erro && <p className="painel aviso-erro" role="alert">{erro}</p>}
        {!linhas && !erro && <p className="nota" role="status">Carregando os portos…</p>}

        {linhas && (
          <div className="painel tabela-rolagem tabela-portos">
            <table className="tabela">
              <caption className="sr-only">Portos monitorados: situação, maré agora, calado máximo e índice operacional</caption>
              <thead>
                <tr>
                  <th scope="col">Porto</th>
                  <th scope="col">Situação</th>
                  <th scope="col">Maré agora</th>
                  <th scope="col">Calado máx.</th>
                  <th scope="col">Índice</th>
                </tr>
              </thead>
              <tbody>
                {visiveis.map((p) => (
                  <tr key={p.slug}>
                    <th scope="row">
                      <Link href={`/porto/?p=${p.slug}`} className="nome-porto">{p.porto}</Link>
                      <span className="nota"> · {p.estado}</span>
                    </th>
                    <td><span className={classeSituacao(p.situacao.palavra)}>{p.situacao.palavra}</span></td>
                    <td>
                      {p.modelo === "nivel_rio"
                        ? (p.rio?.disponivel ? `cota ${fmt(p.rio.cota_m, 2, " m")}` : <span className="vazio">sem dado</span>)
                        : p.mare ? `${fmt(p.mare.altura_m, 2, " m")} ${p.mare.subindo == null ? "" : p.mare.subindo ? "↑" : "↓"}` : <span className="vazio">sem dado</span>}
                    </td>
                    <td>{p.calado_maximo_m != null ? fmt(p.calado_maximo_m, 1, " m") : <span className="vazio">sem dado</span>}</td>
                    <td>{p.indice.valor ?? <span className="vazio">sem dado</span>}</td>
                  </tr>
                ))}
                {visiveis.length === 0 && (
                  <tr><td colSpan={5} className="nota">Nenhum porto com esse nome.</td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
        <p className="fonte rodape-pagina">
          Maré: previsão astronômica (tábua DHN). Calado: páginas oficiais dos portos, com data em cada porto. Índice só
          onde há limites com fonte oficial; nos demais, “sem dado”.
        </p>
        <p className="aviso-navegacao">{AVISO_NAVEGACAO}</p>
      </div>
    </div>
  );
}
