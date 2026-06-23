"""
Compara, por campanha e por dia, o que a Meta reportou vs. o que foi
confirmado na planilha/CRM vs. o que foi confirmado no WhatsApp.

Chamado periodicamente via APScheduler em main.py e também sob demanda
via POST /admin/sync.
"""

import logging
from datetime import datetime, timedelta, timezone

from app.config import Config
from app.db import get_session
from app.models import BMAccount, CampaignInsight, Lead, Divergence

logger = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    """Garante que o datetime seja timezone-aware (UTC) mesmo vindo do SQLite sem tz."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def run_reconciliation(bm_account_id: int, data_referencia: datetime) -> list[Divergence]:
    """
    Roda a comparação para uma BM e um dia específico.
    Cria/atualiza registros em Divergence quando os números não fecham.

    Usa DIVERGENCE_WINDOW_MINUTES para ignorar leads que ainda estão dentro
    da janela de tolerância (podem chegar na planilha/WhatsApp nos próximos minutos).
    """
    data_inicio = _aware(data_referencia).replace(hour=0, minute=0, second=0, microsecond=0)
    data_fim = data_inicio + timedelta(days=1)
    janela = timedelta(minutes=Config.DIVERGENCE_WINDOW_MINUTES)
    agora = datetime.now(timezone.utc)

    session = get_session()
    try:
        insights = (
            session.query(CampaignInsight)
            .filter(
                CampaignInsight.bm_account_id == bm_account_id,
                CampaignInsight.data_referencia >= data_inicio,
                CampaignInsight.data_referencia < data_fim,
            )
            .all()
        )

        resultados: list[Divergence] = []
        for insight in insights:
            leads_do_dia = (
                session.query(Lead)
                .filter(
                    Lead.bm_account_id == bm_account_id,
                    Lead.campaign_id == insight.campaign_id,
                    Lead.recebido_meta_em >= data_inicio,
                    Lead.recebido_meta_em < data_fim,
                )
                .all()
            )

            # Excluir leads ainda dentro da janela de tolerância
            leads_maduros = [
                l for l in leads_do_dia
                if (agora - _aware(l.recebido_meta_em)) >= janela
            ]

            confirmados_planilha = sum(1 for l in leads_maduros if l.confirmado_planilha_em)
            confirmados_whatsapp = sum(1 for l in leads_maduros if l.confirmado_whatsapp_em)
            reportados = insight.leads_reportados_meta

            houve_divergencia = (
                confirmados_planilha < reportados or confirmados_whatsapp < reportados
            )

            if not houve_divergencia:
                continue

            # Upsert: atualizar registro existente ou criar um novo
            existente = (
                session.query(Divergence)
                .filter(
                    Divergence.bm_account_id == bm_account_id,
                    Divergence.campaign_id == insight.campaign_id,
                    Divergence.data_referencia >= data_inicio,
                    Divergence.data_referencia < data_fim,
                )
                .first()
            )

            partes = []
            if confirmados_planilha < reportados:
                partes.append(f"Meta={reportados}, planilha={confirmados_planilha}")
            if confirmados_whatsapp < reportados:
                partes.append(f"Meta={reportados}, WhatsApp={confirmados_whatsapp}")
            descricao = " | ".join(partes)

            if existente:
                existente.leads_confirmados_planilha = confirmados_planilha
                existente.leads_confirmados_whatsapp = confirmados_whatsapp
                existente.descricao = descricao
                resultados.append(existente)
                logger.info("Divergência atualizada — BM %s, campanha %s, %s", bm_account_id, insight.campaign_id, descricao)
            else:
                divergencia = Divergence(
                    bm_account_id=bm_account_id,
                    campaign_id=insight.campaign_id,
                    data_referencia=data_inicio,
                    leads_reportados_meta=reportados,
                    leads_confirmados_planilha=confirmados_planilha,
                    leads_confirmados_whatsapp=confirmados_whatsapp,
                    descricao=descricao,
                )
                session.add(divergencia)
                resultados.append(divergencia)
                logger.warning("Nova divergência — BM %s, campanha %s: %s", bm_account_id, insight.campaign_id, descricao)

        session.commit()
        return resultados
    except Exception:
        session.rollback()
        logger.exception("Erro na reconciliação para BM %s em %s", bm_account_id, data_referencia)
        raise
    finally:
        session.close()


def run_reconciliation_for_all_bms(data_referencia: datetime | None = None) -> list[Divergence]:
    """Roda a reconciliação para todas as BMs ativas. Pensado para rodar via scheduler."""
    data_referencia = data_referencia or (datetime.now(timezone.utc) - timedelta(days=1))

    session = get_session()
    try:
        bm_ids = [bm.id for bm in session.query(BMAccount).filter(BMAccount.ativo.is_(True)).all()]
    finally:
        session.close()

    todos: list[Divergence] = []
    for bm_id in bm_ids:
        try:
            todos.extend(run_reconciliation(bm_id, data_referencia) or [])
        except Exception:
            logger.exception("Falha na reconciliação para BM ID %s — continuando para as demais.", bm_id)

    return todos
