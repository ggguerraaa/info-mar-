"use client";

import { useEffect, useId, useRef, useState } from "react";
import { buscarJson, ErroApi, type PortoMapa, type ResultadoBusca } from "@/lib/api";
import { IconeBusca, IconeFechar } from "./Icones";

// Combobox: navios (nome, MMSI ou IMO, no servidor, a partir de 3 letras) e
// portos (pelo nome, na lista local). Setas, Enter e Esc funcionam.

type Opcao =
  | { tipo: "porto"; chave: string; titulo: string; sub: string; slug: string }
  | { tipo: "navio"; chave: string; titulo: string; sub: string; mmsi: string; nome: string | null; imo: string | null };

const semAcento = (t: string) => t.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export default function Busca({
  portos,
  onNavio,
  onPorto,
}: {
  portos: PortoMapa[];
  onNavio: (n: { mmsi: string; nome: string | null; imo: string | null }) => void;
  onPorto: (slug: string) => void;
}) {
  const [texto, setTexto] = useState("");
  // resposta guardada junto do termo: termo novo = ainda buscando
  const [resposta, setResposta] = useState<{ termo: string; navios: ResultadoBusca[]; erro: string | null } | null>(null);
  const [aberto, setAberto] = useState(false);
  const [ativo, setAtivo] = useState(-1);
  const id = useId();
  const caixa = useRef<HTMLDivElement>(null);

  const termo = texto.trim();
  const portosAchados = termo.length >= 2
    ? portos.filter((p) => semAcento(p.porto).includes(semAcento(termo))).slice(0, 4)
    : [];

  useEffect(() => {
    if (termo.length < 3) return;
    const controle = new AbortController();
    const espera = setTimeout(async () => {
      try {
        const navios = await buscarJson<ResultadoBusca[]>(`/api/navios/busca?q=${encodeURIComponent(termo)}`, controle.signal);
        setResposta({ termo, navios, erro: null });
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setResposta({ termo, navios: [], erro: e instanceof ErroApi ? e.message : "A busca falhou. Tente de novo." });
      }
    }, 300);
    return () => {
      clearTimeout(espera);
      controle.abort();
    };
  }, [termo]);

  const atual = termo.length >= 3 && resposta?.termo === termo ? resposta : null;
  const navios = atual?.navios ?? [];
  const estado: "" | "buscando" | "erro" = termo.length < 3 ? "" : !atual ? "buscando" : atual.erro ? "erro" : "";
  const erro = atual?.erro ?? "";

  const opcoes: Opcao[] = [
    ...portosAchados.map((p): Opcao => ({
      tipo: "porto", chave: `p-${p.slug}`, titulo: p.porto, sub: `Porto · ${p.estado}`, slug: p.slug,
    })),
    ...navios.map((n): Opcao => ({
      tipo: "navio", chave: `n-${n.mmsi}`, titulo: n.nome ?? `MMSI ${n.mmsi}`,
      sub: [`MMSI ${n.mmsi}`, n.imo ? `IMO ${n.imo}` : null, n.tipo, n.tem_posicao ? null : "sem posição recente"]
        .filter(Boolean).join(" · "),
      mmsi: n.mmsi, nome: n.nome, imo: n.imo,
    })),
  ];

  function escolher(o: Opcao) {
    if (o.tipo === "porto") onPorto(o.slug);
    else onNavio({ mmsi: o.mmsi, nome: o.nome, imo: o.imo });
    setAberto(false);
    setTexto("");
    setAtivo(-1);
  }

  function teclado(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setAberto(true);
      setAtivo((a) => Math.min(a + 1, opcoes.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setAtivo((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter" && aberto && opcoes[ativo >= 0 ? ativo : 0]) {
      e.preventDefault();
      escolher(opcoes[ativo >= 0 ? ativo : 0]);
    } else if (e.key === "Escape") {
      setAberto(false);
    }
  }

  useEffect(() => {
    const fora = (e: PointerEvent) => {
      if (caixa.current && !caixa.current.contains(e.target as Node)) setAberto(false);
    };
    document.addEventListener("pointerdown", fora);
    return () => document.removeEventListener("pointerdown", fora);
  }, []);

  const mostrarLista = aberto && termo.length >= 2;
  let mensagem = "";
  if (estado === "erro") mensagem = erro;
  else if (termo.length === 2 && !portosAchados.length) mensagem = "Digite pelo menos 3 letras para buscar navios.";
  else if (estado === "buscando" && !opcoes.length) mensagem = "Buscando…";
  else if (termo.length >= 3 && estado === "" && !opcoes.length)
    mensagem = "Nenhum navio ou porto com esse nome, MMSI ou IMO. Navios só aparecem depois de transmitir perto da costa.";

  return (
    <div className="busca" ref={caixa}>
      <div className="campo flutua-leve">
        <IconeBusca />
        <label htmlFor={`${id}-campo`} className="sr-only">Buscar navio (nome, MMSI ou IMO) ou porto</label>
        <input
          id={`${id}-campo`}
          type="search"
          role="combobox"
          aria-expanded={mostrarLista}
          aria-controls={`${id}-lista`}
          aria-autocomplete="list"
          aria-activedescendant={ativo >= 0 && opcoes[ativo] ? `${id}-${opcoes[ativo].chave}` : undefined}
          placeholder="Buscar navio ou porto"
          autoComplete="off"
          value={texto}
          onChange={(e) => {
            setTexto(e.target.value);
            setAberto(true);
            setAtivo(-1);
          }}
          onFocus={() => setAberto(true)}
          onKeyDown={teclado}
        />
        {texto && (
          <button type="button" className="icone-botao" aria-label="Limpar busca" onClick={() => setTexto("")}>
            <IconeFechar />
          </button>
        )}
      </div>
      {mostrarLista && (
        <div className="busca-resultados painel flutua">
          <ul id={`${id}-lista`} role="listbox" aria-label="Resultados da busca">
            {opcoes.map((o, i) => (
              <li
                key={o.chave}
                id={`${id}-${o.chave}`}
                role="option"
                aria-selected={i === ativo}
                className={i === ativo ? "ativo" : undefined}
                onPointerDown={(e) => e.preventDefault()}
                onClick={() => escolher(o)}
              >
                <span className="busca-titulo">{o.titulo}</span>
                <span className="busca-sub">{o.sub}</span>
              </li>
            ))}
          </ul>
          {mensagem && <p className="nota busca-mensagem" role="status">{mensagem}</p>}
        </div>
      )}
    </div>
  );
}
