"""
Jobs agendados (usados pelo backend_app.py; também roda sozinho).

- Recálculo do índice operacional por porto (a cada 30 min) — maré
  (tábua DHN) + vento/onda (Open-Meteo)
- Geração de alertas (ressaca/chuva/vento/neblina/maré excepcional),
  deduplicados por janela de 3h e gravados no banco (o painel lê de lá)

Uso standalone:
    python scheduler.py
"""

from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler

from alerts import montar_alertas
from config.port_operations_config import PORT_CONFIGS
from port_operations import (
    CondicoesAtuais,
    classificar_status_com_override_barra,
    computar_indice_operacional,
)
from praticagem import atualizar_barra_de_todos_os_portos_disponiveis, porto_tem_fonte_de_praticagem
from monitoramento import PORTO_SISTEMA, checar_saude_do_sistema
from sea_conditions import buscar_condicoes_operacionais
from storage import (
    alerta_ja_emitido_recentemente,
    gravar_alerta,
    gravar_indice_operacional,
    inicializar_banco,
    obter_ultima_barra_status,
)
from tide_now import altura_mare_agora
from tide_utils import coeficiente_por_amplitude_real, coeficiente_por_fase_lunar, idade_da_lua

scheduler = BlockingScheduler(timezone="UTC")


def _calcular_coeficiente_mare(dhn_id: str) -> float | None:
    """TODO: hoje usa só o fallback por fase lunar, já que ainda não
    convertemos os eventos do JSON da DHN pra EventoMare (tide_utils).
    Suficiente pra alertas de "maré excepcional", que são raros
    (coeficiente >=100 ou <=25) — refinar com amplitude real depois."""
    return coeficiente_por_fase_lunar(idade_da_lua())


def job_atualizar_praticagem() -> None:
    atualizar_barra_de_todos_os_portos_disponiveis()


def job_monitorar_saude_do_sistema() -> None:
    agora = datetime.now(timezone.utc).isoformat()
    problemas = checar_saude_do_sistema()
    for problema in problemas:
        if alerta_ja_emitido_recentemente(PORTO_SISTEMA, problema.fonte, janela_horas=3):
            continue  # já avisou esse mesmo problema recentemente
        gravar_alerta(PORTO_SISTEMA, problema.fonte, problema.mensagem, "warning", agora)
        print(f"[{agora}] PROBLEMA DE SISTEMA [{problema.fonte}] {problema.mensagem}")


def job_recalcular_indice_operacional() -> None:
    agora = datetime.now(timezone.utc).isoformat()

    for slug, cfg in PORT_CONFIGS.items():
        mare_altura_m = altura_mare_agora(cfg.dhn_id)
        if mare_altura_m is None:
            print(f"[{agora}] PULANDO {cfg.porto} — sem tábua de maré para hoje em data/mare/ "
                  f"(ver tools/gerar_tabua_harmonica.py)")
            continue

        condicoes_op = buscar_condicoes_operacionais(cfg.lat, cfg.lon)

        # Índice só onde TODOS os parâmetros têm fonte (ver config). Sem isso
        # o painel mostra "sem dado" — mas os alertas abaixo seguem valendo.
        if cfg.indice_calculavel:
            condicoes = CondicoesAtuais(
                mare_altura_m=mare_altura_m,
                vento_kmh=condicoes_op.weather.vento_kmh,
                onda_altura_m=condicoes_op.onda_altura_m,
            )
            indice = computar_indice_operacional(condicoes, cfg)

            # override: se a praticagem confirma barra fechada/impraticável,
            # o status vira 'restrita', independente do índice calculado.
            barra_fechada = None
            if porto_tem_fonte_de_praticagem(cfg.porto):
                barra = obter_ultima_barra_status(cfg.porto)
                barra_fechada = bool(barra["fechada"]) if barra else None

            status = classificar_status_com_override_barra(indice, barra_fechada)
            gravar_indice_operacional(cfg.porto, indice, status, agora)
            print(f"[{agora}] {cfg.porto}: índice={indice} status={status} "
                  f"(maré={mare_altura_m:.2f}m vento={condicoes_op.weather.vento_kmh} "
                  f"onda={condicoes_op.onda_altura_m} barra_fechada={barra_fechada})")

        coeficiente = _calcular_coeficiente_mare(cfg.dhn_id)
        alertas = montar_alertas(condicoes_op.onda_altura_m, condicoes_op.weather, coeficiente, cfg)

        for alerta in alertas:
            if alerta_ja_emitido_recentemente(cfg.porto, alerta.id, janela_horas=3):
                continue  # já avisamos esse mesmo alerta pra esse porto recentemente
            gravar_alerta(cfg.porto, alerta.id, alerta.mensagem, alerta.severidade, agora)
            print(f"[{agora}] ALERTA NOVO [{cfg.porto}] {alerta.id}: {alerta.mensagem}")


if __name__ == "__main__":
    inicializar_banco()

    scheduler.add_job(job_atualizar_praticagem, "interval", minutes=15, next_run_time=datetime.now(timezone.utc))
    scheduler.add_job(
        job_recalcular_indice_operacional, "interval", minutes=30, next_run_time=datetime.now(timezone.utc)
    )
    scheduler.add_job(job_monitorar_saude_do_sistema, "interval", minutes=30, next_run_time=datetime.now(timezone.utc))

    print("Scheduler iniciado. Ctrl+C para parar.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
