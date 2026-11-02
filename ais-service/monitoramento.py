"""
Monitoramento da saúde do próprio sistema — item da Sprint 6.

Antes, se um scraper de praticagem parasse de funcionar (site mudou
layout) ou o WebSocket do AIS caísse, ninguém saberia até notar
manualmente. Este módulo verifica periodicamente se cada fonte de dado
está respondendo dentro do esperado, e dispara alerta pro Telegram
quando não está — reaproveitando a mesma tabela/lógica de dedup dos
alertas operacionais (alertas_emitidos, porto="Sistema").
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config.port_operations_config import PORT_CONFIGS
from praticagem import porto_tem_fonte_de_praticagem
from storage import conexao, obter_ultima_barra_status
from tide_now import _eventos_de_hoje, hoje_brasilia  # reaproveita o parser de eventos do dia

PORTO_SISTEMA = "Sistema"  # usado como "porto" fake nas tabelas de alerta/histórico

# Janelas de tolerância — quanto tempo sem atualização é considerado problema
TOLERANCIA_AIS_MINUTOS = 20  # job de índice roda a cada 30min, então 20min de posição é razoável
TOLERANCIA_PRATICAGEM_MINUTOS = 45  # job roda a cada 15min


@dataclass
class ProblemaDetectado:
    fonte: str
    mensagem: str


def _checar_ais() -> ProblemaDetectado | None:
    # Comparação ISO com ISO (mesmo formato): usa o índice de timestamp_utc
    limite = (datetime.now(timezone.utc) - timedelta(minutes=TOLERANCIA_AIS_MINUTOS)).isoformat()
    with conexao() as conn:
        cursor = conn.execute("SELECT 1 FROM posicoes_navio WHERE timestamp_utc >= ? LIMIT 1", (limite,))
        tem_posicao_recente = cursor.fetchone() is not None

    if not tem_posicao_recente:
        return ProblemaDetectado(
            fonte="ais",
            mensagem=f"Nenhuma posição de navio recebida do AISstream nos últimos {TOLERANCIA_AIS_MINUTOS} min "
                      "— verificar conexão WebSocket / API key.",
        )
    return None


def _checar_praticagem() -> list[ProblemaDetectado]:
    problemas = []
    limite = datetime.now(timezone.utc) - timedelta(minutes=TOLERANCIA_PRATICAGEM_MINUTOS)

    for porto in ("Santos", "Rio Grande"):
        if not porto_tem_fonte_de_praticagem(porto):
            continue
        barra = obter_ultima_barra_status(porto)
        if barra is None:
            problemas.append(ProblemaDetectado(
                fonte=f"praticagem-{porto.lower().replace(' ', '-')}",
                mensagem=f"Nunca conseguimos coletar a condição de barra de {porto} — scraper pode estar quebrado.",
            ))
            continue
        coletado_em = datetime.fromisoformat(barra["coletado_em"])
        if coletado_em < limite:
            problemas.append(ProblemaDetectado(
                fonte=f"praticagem-{porto.lower().replace(' ', '-')}",
                mensagem=f"Praticagem de {porto} sem atualização há mais de {TOLERANCIA_PRATICAGEM_MINUTOS} min "
                          "— site pode ter mudado de layout.",
            ))
    return problemas


def _checar_mare() -> list[ProblemaDetectado]:
    problemas = []
    hoje = hoje_brasilia()
    for cfg in PORT_CONFIGS.values():
        if not cfg.dhn_id:
            continue
        eventos_hoje = _eventos_de_hoje(cfg.dhn_id, hoje)
        if not eventos_hoje:
            problemas.append(ProblemaDetectado(
                fonte=f"mare-{cfg.porto.lower().replace(' ', '-')}",
                mensagem=f"Tábua de maré de {cfg.porto} não tem evento pra hoje ainda — "
                          "importar a tábua oficial do ano ou gerar a previsão harmônica (tools/gerar_tabua_harmonica.py).",
            ))
    return problemas


def checar_saude_do_sistema() -> list[ProblemaDetectado]:
    problemas = []
    ais_problema = _checar_ais()
    if ais_problema:
        problemas.append(ais_problema)
    problemas.extend(_checar_praticagem())
    problemas.extend(_checar_mare())
    return problemas
