"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { buscarJson, classeSituacao, type PainelPorto as Dados } from "@/lib/api";
import ConteudoPorto from "./ConteudoPorto";
import { IconeFechar, IconeSeta } from "./Icones";

export function usePainelPorto(slug: string | null) {
  const [estado, setEstado] = useState<{ slug: string; dados: Dados | null; erro: string | null } | null>(null);
  useEffect(() => {
    if (!slug) return;
    const alvo = slug;
    const controle = new AbortController();
    async function carregar() {
      try {
        setEstado({ slug: alvo, dados: await buscarJson<Dados>(`/api/portos/${alvo}/painel`, controle.signal), erro: null });
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        setEstado((atual) => (atual?.slug === alvo && atual.dados ? atual : { slug: alvo, dados: null, erro: (e as Error).message }));
      }
    }
    carregar();
    const intervalo = setInterval(carregar, 60_000);
    return () => {
      controle.abort();
      clearInterval(intervalo);
    };
  }, [slug]);
  return estado?.slug === slug ? estado : null;
}

export default function PainelPorto({ slug, onFechar, onNavio }: {
  slug: string; onFechar: () => void; onNavio: (mmsi: string) => void;
}) {
  const estado = usePainelPorto(slug);
  const [recolhido, setRecolhido] = useState(false);
  const dados = estado?.dados;
  const nome = dados ? dados.porto : "Porto";

  return (
    <section className="painel flutua doca-item" aria-labelledby={`porto-${slug}`}>
      <header className="doca-cabeca">
        <div className="doca-titulo">
          <h2 id={`porto-${slug}`}>{nome}{dados?.estado ? ` · ${dados.estado}` : ""}</h2>
          {dados && <p className="nota">{dados.situacao.motivo}</p>}
        </div>
        {dados && <span className={classeSituacao(dados.situacao.palavra)}>{dados.situacao.palavra}</span>}
        <button className="icone-botao" onClick={() => setRecolhido((r) => !r)} aria-expanded={!recolhido}
          aria-label={recolhido ? `Expandir painel de ${nome}` : `Recolher painel de ${nome}`}>
          <IconeSeta para={recolhido ? "baixo" : "cima"} />
        </button>
        <button className="icone-botao" onClick={onFechar} aria-label={`Fechar painel de ${nome}`}>
          <IconeFechar />
        </button>
      </header>
      {!recolhido && (
        <div className="doca-corpo">
          {!estado && <p className="nota" role="status">Carregando dados do porto…</p>}
          {estado?.erro && <p className="nota" role="alert">{estado.erro}</p>}
          {dados && (
            <>
              <ConteudoPorto dados={dados} onNavio={onNavio} />
              <Link href={`/porto/?p=${slug}`} className="link-acao">Abrir página do porto</Link>
            </>
          )}
        </div>
      )}
    </section>
  );
}
