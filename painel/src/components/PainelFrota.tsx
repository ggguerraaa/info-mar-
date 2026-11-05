"use client";

import { useState } from "react";
import {
  fmt, idadeTexto, situacaoNavio, type Armador, type NavioFrota, type PortoMapa, type RespostaFrota,
} from "@/lib/api";
import { IconeFechar, IconeSeta } from "./Icones";

// Navios do armador escolhido (ou de toda a frota), inclusive os sem sinal:
// cabotagem passa longe das antenas, então a última posição pode ter dias.

function distanciaKm(lat1: number, lon1: number, lat2: number, lon2: number) {
  const r = (g: number) => (g * Math.PI) / 180;
  const a = Math.sin(r(lat2 - lat1) / 2) ** 2 + Math.cos(r(lat1)) * Math.cos(r(lat2)) * Math.sin(r(lon2 - lon1) / 2) ** 2;
  return 2 * 6371 * Math.asin(Math.sqrt(a));
}

function ondeEsta(n: NavioFrota, portos: PortoMapa[]): string | null {
  if (!n.posicao || !portos.length) return null;
  const { lat, lon } = n.posicao;
  const [perto] = portos
    .map((p) => ({ p, d: distanciaKm(lat, lon, p.lat, p.lon) }))
    .sort((a, b) => a.d - b.d);
  if (perto.d <= 20) return `em ${perto.p.porto}`;
  return `a ${fmt(perto.d, 0)} km de ${perto.p.porto}`;
}

export default function PainelFrota({
  frota, armador, portos, selecionado, onEscolher, onFechar,
}: {
  frota: RespostaFrota;
  armador: string;
  portos: PortoMapa[];
  selecionado: string | null;
  onEscolher: (mmsi: string, lon: number | null, lat: number | null) => void;
  onFechar: () => void;
}) {
  const [recolhido, setRecolhido] = useState(false);
  const cores = new Map<string, Armador>(frota.armadores.map((a) => [a.id, a]));
  const lista = frota.navios
    .filter((n) => armador === "frota" || n.armador === armador)
    .sort((a, b) => (a.idade_s ?? Infinity) - (b.idade_s ?? Infinity) || a.nome.localeCompare(b.nome));
  const titulo = armador === "frota" ? "Frota em destaque" : cores.get(armador)?.nome ?? armador;
  const comSinal = lista.filter((n) => n.posicao).length;

  return (
    <section className="painel flutua doca-item" aria-labelledby="titulo-frota">
      <div className="doca-cabeca">
        <div className="doca-titulo">
          <h2 id="titulo-frota">{titulo}</h2>
          <p className="nota">{lista.length} navios · {comSinal} com posição nos últimos {frota.retencao_dias} dias</p>
        </div>
        <button className="icone-botao" onClick={() => setRecolhido((r) => !r)} aria-expanded={!recolhido}
          aria-label={recolhido ? "Mostrar a lista" : "Recolher a lista"}>
          <IconeSeta para={recolhido ? "baixo" : "cima"} />
        </button>
        <button className="icone-botao" onClick={onFechar} aria-label="Voltar a todos os navios"><IconeFechar /></button>
      </div>
      {!recolhido && (
        <div className="doca-corpo">
          <ul className="lista-frota">
            {lista.map((n) => {
              const cor = cores.get(n.armador)?.cor;
              const conteudo = (
                <>
                  <i className="cor-armador" style={{ background: cor }} aria-hidden="true" />
                  <span className="frota-texto">
                    <span className="frota-nome">{n.nome}</span>
                    <span className="nota">
                      {!n.mmsi
                        ? `IMO ${n.imo} · ainda não ouvido pelo AIS`
                        : !n.posicao
                          ? `sem posição em ${frota.retencao_dias} dias`
                          : [
                              situacaoNavio(n.posicao.status, n.posicao.sog),
                              ondeEsta(n, portos),
                              idadeTexto(n.idade_s),
                            ].filter(Boolean).join(" · ")}
                    </span>
                    {n.destino_informado && <span className="fonte">Destino (tripulação): {n.destino_informado}</span>}
                  </span>
                </>
              );
              return (
                <li key={n.imo}>
                  {n.mmsi ? (
                    <button className="frota-item" aria-current={n.mmsi === selecionado ? "true" : undefined}
                      onClick={() => onEscolher(n.mmsi!, n.posicao?.lon ?? null, n.posicao?.lat ?? null)}>
                      {conteudo}
                    </button>
                  ) : (
                    <div className="frota-item sem-mmsi">{conteudo}</div>
                  )}
                </li>
              );
            })}
          </ul>
          {frota.fonte && <p className="fonte">Armador: {frota.fonte}. Inclui navios próprios e afretados.</p>}
        </div>
      )}
    </section>
  );
}
