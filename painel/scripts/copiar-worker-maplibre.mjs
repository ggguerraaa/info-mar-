// O MapLibre procura o worker ao lado do próprio arquivo, o que não existe
// depois do bundle do Next. Copia o worker para public/ e o mapa aponta para
// ele com setWorkerUrl (ver src/components/mapa/Mapa.tsx).
import { copyFileSync, mkdirSync } from "node:fs";

mkdirSync("public/maplibre", { recursive: true });
copyFileSync("node_modules/maplibre-gl/dist/maplibre-gl-worker.mjs", "public/maplibre/maplibre-gl-worker.mjs");
