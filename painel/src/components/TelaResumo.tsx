"use client";

import Link from "next/link";
import { useEffect, useState, useSyncExternalStore } from "react";
import {
  AVISO_NAVEGACAO, buscarJson, classeSituacao, fmt, haQuantoTempo, type PortoMapa, type ResumoPorto,
} from "@/lib/api";
import { IconeFechar, IconeMais } from "./Icones";

// Resumo: um cartão por porto escolhido. A escolha fica neste navegador
// (localStorage, com try/catch; sem ele vale só nesta aba).

const CHAVE = "info-mare:resumo-portos";
const PADRAO = ["santos", "paranagua", "rio_grande", "itajai", "manaus"];
const ouvintes = new Set<() => void>();
let cache: string[] | null = null;

function lerEscolha(): string[] {
  if (cache) return cache;
  try {
    const bruto = window.localStorage.getItem(CHAVE);
    const lista = bruto ? JSON.parse(bruto) : PADRAO;
    cache = Array.isArray(lista) ? lista.filter((s) => typeof s === "string").slice(0, 20) : PADRAO;
  } catch {
    cache = PADRAO;
  }
  return cache;
}

function gravarEscolha(lista: string[]) {
  cache = lista;
  try {
    window.localStorage.setItem(CHAVE, JSON.stringify(lista));
  } catch {
    // sem armazenamento: vale só nesta aba
  }
  ouvintes.forEach((o) => o());
}

function useEscolha() {
  return useSyncExternalStore(
    (o) => { ouvintes.add(o); return () => ouvintes.delete(o); },
    lerEscolha,
    () => PADRAO,
  );
}

function Cartao({ p, onRemover }: { p: ResumoPorto; onRemover: () => void }) {
  const t = p.tempo;
  return (
    <article className="painel cartao" aria-labelledby={`resumo-${p.slug}`}>
      <div className="cartao-cabeca">
        <div>
          <h2 id={`resumo-${p.slug}`} className="cartao-nome">
            <Link href={`/porto/?p=${p.slug}`}>{p.porto}</Link>
          </h2>
          <p className="nota">{p.estado}{p.modelo === "nivel_rio" ? " · Rio Negro" : p.calado_maximo_m ? ` · calado máx. ${fmt(p.calado_maximo_m, 1, " m")}` : " · calado sem dado"}</p>
        </div>
        <span className={classeSituacao(p.situacao.palavra)}>{p.situacao.palavra}</span>
        <button className="icone-botao" onClick={onRemover} aria-label={`Tirar ${p.porto} do resumo`}><IconeFechar /></button>
      </div>
      <div className="metricas">
        {p.modelo === "nivel_rio" ? (
          <div><div className="rotulo">Cota do rio</div><div className="valor">{p.rio?.disponivel ? fmt(p.rio.cota_m, 2, " m") : "sem dado"}</div></div>
        ) : (
          <div><div className="rotulo">Maré agora</div><div className="valor">{p.mare ? `${fmt(p.mare.altura_m, 2, " m")} ${p.mare.subindo == null ? "" : p.mare.subindo ? "↑" : "↓"}` : "sem dado"}</div></div>
        )}
        <div><div className="rotulo">Vento</div><div className="valor">{t?.vento_kn != null ? `${fmt(t.vento_kn, 0, " nós")} ${t.vento_direcao ?? ""}` : "sem dado"}</div></div>
        {p.modelo === "nivel_rio" ? (
          <div><div className="rotulo">Variação 24 h</div><div className="valor">{p.rio?.variacao_cm != null ? fmt(p.rio.variacao_cm, 0, " cm") : "sem dado"}</div></div>
        ) : (
          <div><div className="rotulo">Ondas</div><div className="valor">{fmt(t?.onda_m, 1, " m")}</div></div>
        )}
        <div><div className="rotulo">Barra</div><div className={p.barra.situacao ? "valor" : "valor vazio"}>
          {!p.barra.disponivel ? (p.modelo === "nivel_rio" ? "não se aplica" : "sem dado") : p.barra.situacao ? (p.barra.fechada ? "Fechada" : "Aberta") : "sem dado"}
        </div></div>
      </div>
      <div>
        <div className="linha-titulo"><span className="rotulo">Índice operacional</span><span className="valor">{p.indice.valor ?? "sem dado"}</span></div>
        {p.indice.valor != null && <div className="barra-indice" aria-hidden="true"><div style={{ width: `${p.indice.valor}%` }} /></div>}
      </div>
      <p className="fonte cartao-rodape">
        {p.modelo === "nivel_rio"
          ? `Cota: ${p.rio?.fonte?.includes("ana.gov") ? "ANA" : "Porto de Manaus"}${p.rio?.data_leitura ? `, leitura de ${p.rio.data_leitura}` : ""}. `
          : p.mare ? "Maré: previsão astronômica (DHN). " : ""}
        {t ? `Vento e ondas: Open-Meteo, ${haQuantoTempo(t.obtido_em)}.` : "Vento e ondas: sem dado."}
        {p.barra.coletado_em ? ` Barra: praticagem, ${haQuantoTempo(p.barra.coletado_em)}.` : ""}
      </p>
    </article>
  );
}

export default function TelaResumo() {
  const escolha = useEscolha();
  const [portos, setPortos] = useState<PortoMapa[]>([]);
  const [linhas, setLinhas] = useState<ResumoPorto[] | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [adicionando, setAdicionando] = useState("");
  const chave = escolha.join(",");

  useEffect(() => {
    buscarJson<PortoMapa[]>("/api/portos").then(setPortos).catch(() => setPortos([]));
  }, []);

  useEffect(() => {
    if (!chave) return;
    const controle = new AbortController();
    async function carregar() {
      try {
        setLinhas(await buscarJson<ResumoPorto[]>(`/api/portos/resumo?slugs=${chave}`, controle.signal));
        setErro(null);
      } catch (e) {
        if ((e as Error).name !== "AbortError") setErro((e as Error).message);
      }
    }
    carregar();
    const intervalo = setInterval(carregar, 120_000);
    return () => { controle.abort(); clearInterval(intervalo); };
  }, [chave]);

  const disponiveis = portos.filter((p) => !escolha.includes(p.slug));
  const visiveis = (linhas ?? []).filter((l) => escolha.includes(l.slug));

  return (
    <div className="pagina">
      <div className="pagina-largura">
        <div className="cabecalho-pagina">
          <h1>Resumo dos portos</h1>
          <form className="adicionar" onSubmit={(e) => {
            e.preventDefault();
            if (adicionando) gravarEscolha([...escolha, adicionando]);
            setAdicionando("");
          }}>
            <label htmlFor="adicionar-porto" className="sr-only">Porto para adicionar ao resumo</label>
            <select id="adicionar-porto" className="seletor" value={adicionando} onChange={(e) => setAdicionando(e.target.value)}>
              <option value="">Escolha um porto</option>
              {disponiveis.map((p) => <option key={p.slug} value={p.slug}>{p.porto} · {p.estado}</option>)}
            </select>
            <button className="botao primario" type="submit" disabled={!adicionando}><IconeMais /> Adicionar porto</button>
          </form>
        </div>
        <p className="nota subtitulo">{escolha.length} porto(s) na tela. Sua seleção fica salva neste navegador.</p>

        {erro && <p className="painel aviso-erro" role="alert">{erro}</p>}
        {!linhas && !erro && <p className="nota" role="status">Carregando maré, vento e ondas dos portos…</p>}
        {escolha.length === 0 && <p className="nota">Nenhum porto escolhido. Use “Adicionar porto” para montar o seu resumo.</p>}

        <div className="grade-cartoes">
          {visiveis.map((p) => (
            <Cartao key={p.slug} p={p} onRemover={() => gravarEscolha(escolha.filter((s) => s !== p.slug))} />
          ))}
        </div>
        <p className="aviso-navegacao rodape-pagina">{AVISO_NAVEGACAO}</p>
      </div>
    </div>
  );
}
