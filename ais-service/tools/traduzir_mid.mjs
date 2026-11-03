// Acrescenta o nome em português a cada MID de config/mid_itu.json.
// O nome em inglês da ITU é casado com um código ISO 3166 pelo nome do
// Unicode CLDR (Intl.DisplayNames do Node, em inglês); o português vem do
// mesmo CLDR. Nomes que não casam sozinhos ficam em CASOS, com o código
// ISO escolhido à mão — o texto em português continua vindo do CLDR.
//
// Uso: node tools/traduzir_mid.mjs [--gravar]
import { readFileSync, writeFileSync } from "node:fs";

const ARQUIVO = new URL("../config/mid_itu.json", import.meta.url);
const dados = JSON.parse(readFileSync(ARQUIVO, "utf8"));
const en = new Intl.DisplayNames(["en"], { type: "region" });
const pt = new Intl.DisplayNames(["pt-BR"], { type: "region" });

const LETRAS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const normal = (s) => s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase()
  .replace(/\(.*?\)/g, " ").replace(/\b(the|of|and|republic|kingdom|state|states|federal|democratic|islamic|people'?s|plurinational|bolivarian|principality|grand duchy|sultanate|commonwealth|united|federative|socialist|union|independent|arab|lao)\b/g, " ")
  .replace(/[^a-z]+/g, " ").trim();

const porNome = new Map();
for (const a of LETRAS) for (const b of LETRAS) {
  const codigo = a + b;
  let nome;
  try { nome = en.of(codigo); } catch { continue; }
  if (!nome || nome === codigo) continue;
  porNome.set(normal(nome), codigo);
}

// Nomes da ITU que o casamento automático não resolve: código ISO 3166 à mão
// (o português continua vindo do CLDR). Açores e Madeira não têm código de
// país: texto fixo. Os territórios austrais franceses (Adélia, Crozet,
// Kerguelen, São Paulo e Amsterdã) ficam como TF, o território que os reúne.
const CASOS = {
  "Argentine Republic": "AR", "Brunei Darussalam": "BN", "Cabo Verde (Republic of)": "CV",
  "Hong Kong (Special Administrative Region of China)": "HK", "Macao (Special Administrative Region of China)": "MO",
  "Congo (Republic of the)": "CG", "Czech Republic": "CZ", "Democratic People's Republic of Korea": "KP",
  "Democratic Republic of the Congo": "República Democrática do Congo", "Adelie Land": "TF", "Crozet Archipelago": "TF",
  "Guiana (French Department of)": "GF", "Kerguelen Islands": "TF", "Saint Paul and Amsterdam Islands": "TF",
  "Saint Pierre and Miquelon (Territorial Collectivity of)": "PM", "Wallis and Futuna Islands": "WF",
  "Gabonese Republic": "GA", "Korea (Republic of)": "KR", "Kyrgyz Republic": "KG",
  "Bonaire, Sint Eustatius and Saba": "BQ", "Azores": "Portugal (Açores)", "Madeira": "Portugal (Madeira)",
  "Republic of Naoero": "NR", "Russian Federation": "RU", "Saint Kitts and Nevis (Federation of)": "KN",
  "Saint Lucia": "LC", "Saint Vincent and the Grenadines": "VC", "Slovak Republic": "SK",
  "State of Palestine (In accordance with Resolution 99 Rev. Dubai, 2018)": "PS", "Syrian Arab Republic": "SY",
  "Togolese Republic": "TG", "United Kingdom of Great Britain and Northern Ireland": "GB", "Pitcairn Island": "PN",
  "Saint Helena": "SH", "United States of America": "US", "Alaska (State of)": "US",
  "United States Virgin Islands": "VI", "Viet Nam (Socialist Republic of)": "VN", "Lao People's Democratic Republic": "LA",
};
const traduzir = (valor) => (/^[A-Z]{2}$/.test(valor) ? pt.of(valor) : valor);

const semCasar = new Set();
const resultado = {};
for (const [mid, nomeItu] of Object.entries(dados.mids)) {
  const partes = nomeItu.split(" / ").map((parte) => {
    // "Portugal - Azores": território depois do hífen
    const alvo = parte.includes(" - ") ? parte.split(" - ").pop() : parte;
    const chaveAuto = normal(alvo) ? porNome.get(normal(alvo)) : undefined; // nome vazio após limpar: não casa
    const codigo = CASOS[alvo] ?? CASOS[parte] ?? chaveAuto;
    if (!codigo) { semCasar.add(parte); return null; }
    if (process.argv.includes("--listar")) console.log(`${mid}	${parte}	-> ${traduzir(codigo)}`);
    return traduzir(codigo);
  });
  if (partes.every(Boolean)) resultado[mid] = [...new Set(partes)].join(" / ");
}

console.log(`casados: ${Object.keys(resultado).length} de ${Object.keys(dados.mids).length} MIDs`);
console.log(`sem casar (${semCasar.size}):`, [...semCasar].sort());

if (process.argv.includes("--gravar")) {
  dados.mids_pt = resultado;
  dados.nota_pt = "mids_pt: nome em português do Unicode CLDR (Intl do Node " + process.version +
    "), casado ao nome da ITU por tools/traduzir_mid.mjs. MID sem nome em português usa o nome da ITU.";
  writeFileSync(ARQUIVO, JSON.stringify(dados, null, 1) + "\n");
  console.log("gravado");
}
