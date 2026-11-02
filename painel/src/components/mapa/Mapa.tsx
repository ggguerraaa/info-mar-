"use client";

import "maplibre-gl/dist/maplibre-gl.css";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as MapaGL, MapLayerMouseEvent } from "maplibre-gl";
import { useEffect, useLayoutEffect, useRef } from "react";
import { buscarJson, ErroApi, ESTILO_MAPA_URL, type PortoMapa, type RespostaNavios } from "@/lib/api";
import { iconeNavio, iconePonto, iconePorto, ESCALA_ICONES } from "./icones";

// Mapa em WebGL (MapLibre): os navios são uma camada de símbolos, não
// marcadores no DOM — aguenta milhares sem travar. Base OpenFreeMap Positron,
// clareada para o tom do boletim (água espuma, terra gelo, poucos rótulos).

const COR = {
  gelo: "#EEEEEE", espuma: "#C3E4E9", nevoa: "#88B4BE", corrente: "#056C89", profundo: "#023653",
  texto2: "#41667D",
};
const ATUALIZAR_A_CADA_MS = 12_000;
const VELHO_S = 30 * 60;
const CENTRO_BRASIL: [number, number] = [-45, -16];

// Camadas do Positron que só fazem ruído num mapa de navegação.
const ESCONDER = /^(highway-name|highway-shield|road_shield|airport|label_other|label_village|railway|aeroway|building|waterway_line_label|boundary_3|highway_path|highway_minor|tunnel_)/;

let workerDefinido = false;

export interface MapaProps {
  navioSelecionado: string | null;
  portoSelecionado: string | null;
  salvos: string[];
  rastro: [number, number][] | null;
  centralizar: { lon: number; lat: number; zoom?: number; id: number } | null;
  mostrarNavios: boolean;
  mostrarPortos: boolean;
  onNavio: (mmsi: string) => void;
  onPorto: (slug: string) => void;
  onPortos: (portos: PortoMapa[]) => void;
  onAtualizado: (info: { naVisao: number; total: number; em: string } | null, erro: string | null) => void;
}

function clarearEstilo(mapa: MapaGL) {
  for (const camada of mapa.getStyle().layers ?? []) {
    const id = camada.id;
    try {
      if (ESCONDER.test(id)) mapa.setLayoutProperty(id, "visibility", "none");
      else if (id === "background") mapa.setPaintProperty(id, "background-color", COR.gelo);
      else if (id === "water") mapa.setPaintProperty(id, "fill-color", COR.espuma);
      else if (id === "waterway") mapa.setPaintProperty(id, "line-color", COR.espuma);
      else if (/^(park|landcover|landuse)/.test(id)) mapa.setPaintProperty(id, "fill-opacity", 0.35);
      else if (camada.type === "symbol" && id.startsWith("water_name")) mapa.setPaintProperty(id, "text-color", COR.corrente);
      else if (camada.type === "symbol") mapa.setPaintProperty(id, "text-color", COR.texto2);
      // rótulos em português quando o OpenStreetMap tem o nome traduzido
      if (camada.type === "symbol" && /^(label_|water_name)/.test(id)) {
        mapa.setLayoutProperty(id, "text-field", ["coalesce", ["get", "name:pt"], ["get", "name"]]);
      }
    } catch {
      // estilo diferente do Positron (URL configurável): segue sem ajustar
    }
  }
}

function adicionarIcones(mapa: MapaGL) {
  const opcoes = { pixelRatio: ESCALA_ICONES };
  mapa.addImage("navio", iconeNavio(COR.nevoa, COR.profundo, 14), opcoes);
  mapa.addImage("navio-salvo", iconeNavio(COR.corrente, "#ffffff", 20), opcoes);
  mapa.addImage("navio-sel", iconeNavio(COR.profundo, "#ffffff", 24), opcoes);
  mapa.addImage("ponto", iconePonto(COR.nevoa, COR.profundo, 8), opcoes);
  mapa.addImage("ponto-salvo", iconePonto(COR.corrente, "#ffffff", 12), opcoes);
  mapa.addImage("ponto-sel", iconePonto(COR.profundo, "#ffffff", 14), opcoes);
  mapa.addImage("porto", iconePorto(COR.profundo, false), opcoes);
  mapa.addImage("porto-sel", iconePorto(COR.corrente, true), opcoes);
}

const VAZIO: GeoJSON.FeatureCollection = { type: "FeatureCollection", features: [] };

function adicionarCamadas(mapa: MapaGL) {
  mapa.addSource("navios", { type: "geojson", data: VAZIO });
  mapa.addSource("portos", { type: "geojson", data: VAZIO });
  mapa.addSource("rastro", { type: "geojson", data: VAZIO });

  mapa.addLayer({
    id: "rastro", type: "line", source: "rastro",
    paint: { "line-color": COR.profundo, "line-width": 2, "line-opacity": 0.7, "line-dasharray": [1, 2] },
    layout: { "line-cap": "round", "line-join": "round" },
  });

  // Afastado, os navios encolhem em vez de agrupar.
  const tamanho = ["interpolate", ["linear"], ["zoom"], 3, 0.55, 6, 0.8, 10, 1.1] as const;
  const rotacao = ["coalesce", ["get", "r"], 0] as const;
  mapa.addLayer({
    id: "navios", type: "symbol", source: "navios",
    layout: {
      "icon-image": ["case", ["get", "p"], "ponto", "navio"],
      "icon-size": tamanho as unknown as number,
      "icon-rotate": rotacao as unknown as number,
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
    },
    paint: { "icon-opacity": ["case", ["get", "v"], 0.45, 1] },
  });
  mapa.addLayer({
    id: "navios-destaque", type: "symbol", source: "navios", filter: ["==", ["get", "m"], ""],
    layout: {
      "icon-image": ["case", ["get", "s"],
        ["case", ["get", "p"], "ponto-sel", "navio-sel"],
        ["case", ["get", "p"], "ponto-salvo", "navio-salvo"]],
      "icon-size": ["interpolate", ["linear"], ["zoom"], 3, 0.8, 8, 1],
      "icon-rotate": rotacao as unknown as number,
      "icon-rotation-alignment": "map",
      "icon-allow-overlap": true,
      "icon-ignore-placement": true,
      "symbol-sort-key": ["case", ["get", "s"], 2, 1],
    },
  });
  mapa.addLayer({
    id: "navio-rotulo", type: "symbol", source: "navios", filter: ["==", ["get", "m"], ""],
    layout: {
      "text-field": ["coalesce", ["get", "n"], ["concat", "MMSI ", ["get", "m"]]],
      "text-font": ["Noto Sans Bold"],
      "text-size": 12,
      "text-offset": [0, 1.4],
      "text-anchor": "top",
      "text-allow-overlap": true,
    },
    paint: { "text-color": COR.profundo, "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
  });

  mapa.addLayer({
    id: "portos", type: "symbol", source: "portos",
    layout: {
      "icon-image": ["case", ["get", "s"], "porto-sel", "porto"],
      "icon-anchor": "bottom",
      "icon-allow-overlap": true,
      "text-field": ["step", ["zoom"], "", 5, ["get", "nome"]],
      "text-font": ["Noto Sans Regular"],
      "text-size": 12,
      "text-offset": [0.9, -1.2],
      "text-anchor": "left",
      "text-optional": true,
    },
    paint: { "text-color": COR.profundo, "text-halo-color": "#ffffff", "text-halo-width": 1.5 },
  });
}

export default function Mapa(props: MapaProps) {
  const elemento = useRef<HTMLDivElement>(null);
  const mapaRef = useRef<MapaGL | null>(null);
  const pronto = useRef(false);
  const dadosNavios = useRef<RespostaNavios | null>(null);
  const portosRef = useRef<PortoMapa[]>([]);
  const propsRef = useRef(props);
  // última versão das props para os eventos do mapa (registrados uma vez)
  useLayoutEffect(() => {
    propsRef.current = props;
  });

  // Monta os GeoJSON a partir dos arrays compactos (marca selecionado/salvo)
  function redesenharNavios() {
    const mapa = mapaRef.current;
    const dados = dadosNavios.current;
    if (!mapa || !pronto.current || !dados) return;
    const { navioSelecionado } = propsRef.current;
    const features: GeoJSON.Feature[] = dados.navios.map(([m, lat, lon, vel, rumo, proa, status, nome, idade]) => ({
      type: "Feature",
      geometry: { type: "Point", coordinates: [lon, lat] },
      properties: {
        m, n: nome,
        r: proa ?? rumo ?? 0,
        p: vel === null ? status === 1 || status === 5 : vel < 0.5,
        v: idade > VELHO_S,
        s: m === navioSelecionado,
      },
    }));
    (mapa.getSource("navios") as GeoJSONSource).setData({ type: "FeatureCollection", features });
  }

  function aplicarFiltros() {
    const mapa = mapaRef.current;
    if (!mapa || !pronto.current) return;
    const { navioSelecionado, salvos, mostrarNavios, mostrarPortos } = propsRef.current;
    const destaque = navioSelecionado ? [...salvos, navioSelecionado] : salvos;
    mapa.setFilter("navios", ["!", ["in", ["get", "m"], ["literal", destaque]]]);
    mapa.setFilter("navios-destaque", ["in", ["get", "m"], ["literal", destaque]]);
    mapa.setFilter("navio-rotulo", ["==", ["get", "m"], navioSelecionado ?? ""]);
    for (const id of ["navios", "navios-destaque", "navio-rotulo", "rastro"]) {
      mapa.setLayoutProperty(id, "visibility", mostrarNavios ? "visible" : "none");
    }
    mapa.setLayoutProperty("portos", "visibility", mostrarPortos ? "visible" : "none");
  }

  function redesenharPortos() {
    const mapa = mapaRef.current;
    if (!mapa || !pronto.current) return;
    const sel = propsRef.current.portoSelecionado;
    (mapa.getSource("portos") as GeoJSONSource).setData({
      type: "FeatureCollection",
      features: portosRef.current.map((p) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [p.lon, p.lat] },
        properties: { slug: p.slug, nome: p.porto, s: p.slug === sel },
      })),
    });
  }

  // Criação do mapa (uma vez)
  useEffect(() => {
    if (!elemento.current) return;
    if (!workerDefinido) {
      maplibregl.setWorkerUrl(new URL("/maplibre/maplibre-gl-worker.mjs", window.location.href).href);
      workerDefinido = true;
    }
    const reduzirMovimento = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const mapa = new maplibregl.Map({
      container: elemento.current,
      style: ESTILO_MAPA_URL,
      center: CENTRO_BRASIL,
      zoom: window.innerWidth < 768 ? 2.6 : 3.6,
      minZoom: 2,
      maxZoom: 16,
      attributionControl: { compact: true, customAttribution: "Navios: AISstream.io" },
      dragRotate: false,
      pitchWithRotate: false,
      fadeDuration: reduzirMovimento ? 0 : 300,
    });
    mapa.touchZoomRotate.disableRotation();
    mapa.keyboard.enable();
    mapa.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    mapa.getCanvas().setAttribute("aria-label", "Mapa de navios e portos. Use a busca para encontrar um navio pelo teclado.");
    mapaRef.current = mapa;

    let temporizador: ReturnType<typeof setTimeout> | undefined;
    let controle: AbortController | null = null;

    async function atualizar() {
      if (document.hidden || !pronto.current) return;
      controle?.abort();
      controle = new AbortController();
      const b = mapa.getBounds();
      const margem = 0.2;
      const dLon = (b.getEast() - b.getWest()) * margem;
      const dLat = (b.getNorth() - b.getSouth()) * margem;
      const bbox = [
        Math.max(-180, b.getWest() - dLon), Math.max(-90, b.getSouth() - dLat),
        Math.min(180, b.getEast() + dLon), Math.min(90, b.getNorth() + dLat),
      ].map((v) => v.toFixed(3)).join(",");
      try {
        const dados = await buscarJson<RespostaNavios>(`/api/navios?bbox=${bbox}`, controle.signal);
        dadosNavios.current = dados;
        redesenharNavios();
        propsRef.current.onAtualizado({ naVisao: dados.navios.length, total: dados.total_memoria, em: dados.gerado_em }, null);
      } catch (e) {
        if ((e as Error).name === "AbortError") return;
        propsRef.current.onAtualizado(null, e instanceof ErroApi ? e.message : "Não foi possível atualizar os navios.");
      }
    }

    function agendar(ms: number) {
      clearTimeout(temporizador);
      temporizador = setTimeout(async () => {
        await atualizar();
        agendar(ATUALIZAR_A_CADA_MS);
      }, ms);
    }

    mapa.on("load", async () => {
      // celular: atribuição recolhida no botão "i" (continua acessível)
      if (window.innerWidth < 768) elemento.current?.querySelector(".maplibregl-ctrl-attrib")?.classList.remove("maplibregl-compact-show");
      clarearEstilo(mapa);
      adicionarIcones(mapa);
      adicionarCamadas(mapa);
      pronto.current = true;
      aplicarFiltros();
      agendar(0);
      try {
        portosRef.current = await buscarJson<PortoMapa[]>("/api/portos");
        redesenharPortos();
        propsRef.current.onPortos(portosRef.current);
      } catch {
        // portos sem resposta: o mapa de navios continua
      }
    });
    mapa.on("moveend", () => agendar(400));
    const aoVoltar = () => { if (!document.hidden) agendar(0); };
    document.addEventListener("visibilitychange", aoVoltar);

    mapa.on("click", "navios", (e: MapLayerMouseEvent) => { const m = e.features?.[0]?.properties?.m; if (m) propsRef.current.onNavio(String(m)); });
    mapa.on("click", "navios-destaque", (e: MapLayerMouseEvent) => { const m = e.features?.[0]?.properties?.m; if (m) propsRef.current.onNavio(String(m)); });
    mapa.on("click", "portos", (e: MapLayerMouseEvent) => { const s = e.features?.[0]?.properties?.slug; if (s) propsRef.current.onPorto(String(s)); });
    for (const id of ["navios", "navios-destaque", "portos"]) {
      mapa.on("mouseenter", id, () => { mapa.getCanvas().style.cursor = "pointer"; });
      mapa.on("mouseleave", id, () => { mapa.getCanvas().style.cursor = ""; });
    }

    return () => {
      clearTimeout(temporizador);
      controle?.abort();
      document.removeEventListener("visibilitychange", aoVoltar);
      pronto.current = false;
      mapa.remove();
      mapaRef.current = null;
    };
  }, []);

  useEffect(() => {
    redesenharNavios();
    aplicarFiltros();
  }, [props.navioSelecionado, props.salvos, props.mostrarNavios, props.mostrarPortos]);

  useEffect(() => {
    redesenharPortos();
  }, [props.portoSelecionado]);

  useEffect(() => {
    const mapa = mapaRef.current;
    if (!mapa || !pronto.current) return;
    const coords = props.rastro ?? [];
    (mapa.getSource("rastro") as GeoJSONSource).setData(
      coords.length > 1
        ? { type: "Feature", geometry: { type: "LineString", coordinates: coords }, properties: {} }
        : VAZIO,
    );
  }, [props.rastro]);

  useEffect(() => {
    const mapa = mapaRef.current;
    const alvo = props.centralizar;
    if (!mapa || !alvo) return;
    const reduzir = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const zoom = Math.max(mapa.getZoom(), alvo.zoom ?? 9);
    if (reduzir) mapa.jumpTo({ center: [alvo.lon, alvo.lat], zoom });
    else mapa.flyTo({ center: [alvo.lon, alvo.lat], zoom, duration: 900 });
  }, [props.centralizar]);

  return <div ref={elemento} className="mapa-gl" />;
}
