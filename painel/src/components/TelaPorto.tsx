"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { classeSituacao, fmt } from "@/lib/api";
import ConteudoPorto from "./ConteudoPorto";
import { IconeSeta } from "./Icones";
import { usePainelPorto } from "./PainelPorto";

export default function TelaPorto() {
  const slug = useSearchParams().get("p") ?? "";
  const router = useRouter();
  const estado = usePainelPorto(slug || null);
  const dados = estado?.dados;

  useEffect(() => {
    if (dados) document.title = `${dados.porto} · Info-Maré`;
  }, [dados]);

  return (
    <div className="pagina">
      <div className="pagina-largura">
        <Link href="/portos/" className="voltar"><IconeSeta para="esquerda" /> Todos os portos</Link>
        {!slug && <p className="nota">Escolha um porto na <Link href="/portos/">lista de portos</Link>.</p>}
        {slug && !estado && <p className="nota" role="status">Carregando dados do porto…</p>}
        {slug && estado?.erro && (
          <p className="painel aviso-erro" role="alert">
            {estado.erro === "Não encontrado." ? "Este porto não está na lista do Info-Maré." : estado.erro}
          </p>
        )}
        {dados && (
          <>
            <div className="cabecalho-pagina">
              <div>
                <h1>Porto de {dados.porto}</h1>
                <p className="nota subtitulo">
                  {dados.estado} · {fmt(dados.lat, 2)}, {fmt(dados.lon, 2)}
                  {dados.calado ? ` · calado máx. ${fmt(dados.calado.calado_maximo_m, 1, " m")}` : ""}
                </p>
              </div>
              <span className={classeSituacao(dados.situacao.palavra)}>{dados.situacao.palavra}</span>
            </div>
            <div className="porto-detalhe painel">
              <h2 className="sr-only">Condições agora</h2>
              <ConteudoPorto dados={dados} onNavio={(mmsi) => router.push(`/?navio=${mmsi}`)} />
            </div>
            <p className="rodape-pagina">
              <Link href={`/?porto=${dados.slug}`} className="link-acao">Ver {dados.porto} no mapa</Link>
            </p>
          </>
        )}
      </div>
    </div>
  );
}
