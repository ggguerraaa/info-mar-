# Testes — Info-Maré

Comandos para Windows, a partir de `ais-service/` (Python do ambiente
virtual: `.\.venv\Scripts\python.exe`). Só um coletor por chave do AISstream:
pare o backend antes do teste 1.

## 1. AIS: tipos de mensagem e taxa reais

```powershell
.\.venv\Scripts\python.exe tools\verificar_ais.py 600
```

Sem filtro de tipo nem de navio, na caixa do coletor. Imprime amostras de cada
tipo, mensagens por segundo, navios por tipo e quantos têm nome e IMO.
Referência: [docs/medicao-ais-2026-11-02.md](docs/medicao-ais-2026-11-02.md).

## 2. Backend

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend_app:app --port 8000
```

Em outro terminal:

```powershell
foreach ($u in "/health", "/api/navios?bbox=-50,-30,-40,-20", "/api/navios/busca?q=MSC",
               "/api/portos", "/api/portos/santos/painel", "/api/portos/belem/painel",
               "/api/portos/manaus/painel", "/api/portos/resumo", "/api/sistema/saude") {
  "{0,-40} {1}" -f $u, (Invoke-WebRequest "http://localhost:8000$u" -SkipHttpErrorCheck).StatusCode
}
```

Esperado: todos 200. Conferências:
- `/api/navios/busca?q=AB` responde 422 (mínimo 3 caracteres); no máximo 20 resultados.
- `/api/portos/santos/painel`: maré com fonte, vento/onda com `obtido_em`, barra
  da praticagem, calado com fonte e data, navios por raio.
- `/api/portos/belem/painel`: `calado` nulo e índice "não calculado" — nunca número inventado.
- `/api/portos/manaus/painel`: `rio` com fonte da ANA, `mare` nulo.
- Mais de `LIMITE_REQ_POR_MIN` consultas em 1 min do mesmo IP → 429.

## 3. Painel

```powershell
cd ..\painel
npm install
npm run lint
npm run build      # o backend em :8000 passa a servir o painel
```

Em `http://localhost:8000/`:
- Navios aparecem em poucos segundos (medido: 2,5 s no desktop e 1,0 s em 360 px).
- Buscar por nome, MMSI e IMO; salvar; recarregar: o navio continua em "Meus
  navios". Exportar e importar o JSON.
- Clicar em Santos: maré, vento, ondas, barra e navios, cada um com fonte e idade.
- Clicar em Belém: calado "sem dado".
- Aviso de navegação e cobertura do AIS visíveis.
- Em 360 px de largura: sem rolagem lateral; painéis em folha por baixo do mapa.

Lighthouse (acessibilidade), 02/11/2026: Mapa 100, Resumo 100, Portos 100,
Porto 98 (corrigido depois: ordem dos títulos).

## 4. Reinício

Derrube o backend e suba de novo: o log mostra `Memória AIS reabastecida do
banco: N navios`, e o rastro de 24 h de um navio continua igual.
