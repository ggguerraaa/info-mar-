"use client";

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { AVISO_COBERTURA, AVISO_NAVEGACAO, BASE_PATH, buscarJson, MODO_ESTATICO, haQuantoTempo, type PortoMapa, type Trajetoria } from "@/lib/api";
import { useNaviosSalvos } from "@/lib/naviosSalvos";
import Busca from "./Busca";
import MeusNavios from "./MeusNavios";
import PainelNavio from "./PainelNavio";
import PainelPorto from "./PainelPorto";
import { IconeSeta } from "./Icones";

// Mapa só no navegador (WebGL); enquanto carrega, o fundo já tem a cor da terra.
const Mapa = dynamic(() => import("./mapa/Mapa"), { ssr: false, loading: () => <div className="mapa-gl" /> });

export default function TelaMapa() {
  const router = useRouter();
  const parametros = useSearchParams();
  const [navio, setNavio] = useState<string | null>(parametros.get("navio"));
  const [porto, setPorto] = useState<string | null>(parametros.get("porto"));
  const [portos, setPortos] = useState<PortoMapa[]>([]);
  const [rastro, setRastro] = useState<{ mmsi: string; coords: [number, number][] } | null>(null);
  const [centralizar, setCentralizar] = useState<{ lon: number; lat: number; zoom?: number; id: number } | null>(null);
  const [camadas, setCamadas] = useState({ navios: true, portos: true });
  const [status, setStatus] = useState<{ naVisao: number; total: number; em: string } | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [folhaAberta, setFolhaAberta] = useState(true);
  const contador = useRef(0);
  const salvos = useNaviosSalvos();
  const mmsisSalvos = salvos.map((n) => n.mmsi);

  const irPara = useCallback((lon: number, lat: number, zoom?: number) => {
    contador.current += 1;
    setCentralizar({ lon, lat, zoom, id: contador.current });
  }, []);

  // URL acompanha a seleção (dá para compartilhar o link do navio ou porto)
  useEffect(() => {
    const q = new URLSearchParams();
    if (navio) q.set("navio", navio);
    if (porto) q.set("porto", porto);
    const destino = q.toString() ? `/?${q}` : "/";
    if (`${BASE_PATH}${destino}` !== `${window.location.pathname}${window.location.search}`) router.replace(destino, { scroll: false });
  }, [navio, porto, router]);

  // Rastro de 24 h do navio selecionado
  useEffect(() => {
    if (!navio) return;
    const controle = new AbortController();
    buscarJson<Trajetoria>(`/api/navios/${navio}/trajetoria?horas=24`, controle.signal)
      .then((t) => setRastro({ mmsi: navio, coords: t.coordinates }))
      .catch(() => setRastro({ mmsi: navio, coords: [] }));
    return () => controle.abort();
  }, [navio]);

  const escolherNavio = useCallback((mmsi: string, lon?: number | null, lat?: number | null) => {
    setNavio(mmsi);
    setFolhaAberta(true);
    if (lon != null && lat != null) irPara(lon, lat, 10);
  }, [irPara]);

  async function escolherNavioDaBusca(mmsi: string) {
    escolherNavio(mmsi);
    try {
      const card = await buscarJson<{ posicao: { longitude: number; latitude: number } | null }>(`/api/navios/${mmsi}`);
      if (card.posicao) irPara(card.posicao.longitude, card.posicao.latitude, 10);
    } catch {
      // o painel do navio mostra o erro
    }
  }

  const escolherPorto = useCallback((slug: string) => {
    setPorto(slug);
    setFolhaAberta(true);
    const p = portos.find((x) => x.slug === slug);
    if (p) irPara(p.lon, p.lat, 9);
  }, [portos, irPara]);

  const aoAtualizar = useCallback((info: { naVisao: number; total: number; em: string } | null, e: string | null) => {
    if (info) setStatus(info);
    setErro(e);
  }, []);

  const rastroAtual = rastro && rastro.mmsi === navio ? rastro.coords : null;
  const temPainel = Boolean(navio || porto) || salvos.length > 0;

  return (
    <div className="tela-mapa">
      <Mapa
        navioSelecionado={navio}
        portoSelecionado={porto}
        salvos={mmsisSalvos}
        rastro={rastroAtual}
        centralizar={centralizar}
        mostrarNavios={camadas.navios}
        mostrarPortos={camadas.portos}
        onNavio={(m) => escolherNavio(m)}
        onPorto={escolherPorto}
        onPortos={setPortos}
        onAtualizado={aoAtualizar}
      />

      <div className="mapa-topo">
        <h1 className="mapa-titulo">Info-Maré</h1>
        <Busca portos={portos} onNavio={(n) => escolherNavioDaBusca(n.mmsi)} onPorto={escolherPorto} />
        <div className="chips" role="group" aria-label="Camadas do mapa">
          {(["navios", "portos"] as const).map((c) => (
            <button key={c} className={camadas[c] ? "chip ligado" : "chip"} aria-pressed={camadas[c]}
              onClick={() => setCamadas((atual) => ({ ...atual, [c]: !atual[c] }))}>
              {c === "navios" ? "Navios" : "Portos"}
            </button>
          ))}
        </div>
      </div>

      {erro && <p className="mapa-erro painel flutua" role="alert">{erro}</p>}

      <aside className={`doca ${temPainel ? "" : "vazia"} ${folhaAberta ? "aberta" : "fechada"}`} aria-label="Painéis">
        <button className="folha-alca" onClick={() => setFolhaAberta((a) => !a)} aria-expanded={folhaAberta}>
          <span className="folha-traco" aria-hidden="true" />
          <span>{folhaAberta ? "Recolher painéis" : "Mostrar painéis"}</span>
          <IconeSeta para={folhaAberta ? "baixo" : "cima"} />
        </button>
        <div className="doca-rolagem">
          {navio && (
            <PainelNavio
              key={navio}
              mmsi={navio}
              pontosRastro={rastro?.mmsi === navio ? rastro.coords.length : null}
              onFechar={() => { setNavio(null); setRastro(null); }}
              onCentralizar={(lon, lat) => irPara(lon, lat, 10)}
            />
          )}
          {porto && <PainelPorto key={porto} slug={porto} onFechar={() => setPorto(null)} onNavio={(m) => escolherNavioDaBusca(m)} />}
          <MeusNavios selecionado={navio} onEscolher={escolherNavio} />
        </div>
      </aside>

      <div className="mapa-rodape">
        <div className="legenda painel" aria-label="Legenda">
          <span><i className="leg leg-sel" aria-hidden="true" />Selecionado</span>
          <span><i className="leg leg-salvo" aria-hidden="true" />Meus navios</span>
          <span><i className="leg leg-outro" aria-hidden="true" />Outros</span>
          <span><i className="leg leg-parado" aria-hidden="true" />Parado</span>
        </div>
        <p className="cobertura painel">
          {AVISO_COBERTURA}{" "}
          {status ? `${status.naVisao} navios nesta área, ${status.total} no total. Atualizado ${haQuantoTempo(status.em)}${MODO_ESTATICO ? " (nova leitura a cada ~30 min)" : ""}.` : "Carregando navios…"}
        </p>
        <p className="aviso-navegacao">{AVISO_NAVEGACAO}</p>
      </div>
    </div>
  );
}
