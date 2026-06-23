import logging
import os
from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app import create_app
from app.db import get_session
from app.models import BMAccount, CampaignInsight
from app.meta_api import get_client_for_bm
from app.reconciliation import run_reconciliation_for_all_bms

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def collect_insights_job():
    """Job diário: coleta insights de ontem de todas as BMs ativas e persiste no banco."""
    logger.info("[scheduler] Iniciando coleta de insights...")
    session = get_session()
    try:
        bm_accounts = session.query(BMAccount).filter(BMAccount.ativo.is_(True)).all()
    finally:
        session.close()

    data_ref = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    for bm in bm_accounts:
        try:
            client = get_client_for_bm(bm)
            insights = client.fetch_campaign_insights(date_preset="yesterday")

            session2 = get_session()
            try:
                for ins in insights:
                    existente = session2.query(CampaignInsight).filter_by(
                        bm_account_id=bm.id,
                        campaign_id=ins["campaign_id"],
                        data_referencia=data_ref,
                    ).first()
                    if existente:
                        for k, v in ins.items():
                            setattr(existente, k, v)
                    else:
                        session2.add(CampaignInsight(
                            bm_account_id=bm.id,
                            data_referencia=data_ref,
                            **ins,
                        ))
                session2.commit()
                logger.info("[scheduler] BM '%s': %d insights coletados.", bm.client_name, len(insights))
            finally:
                session2.close()

        except Exception:
            logger.exception("[scheduler] Falha ao coletar insights para BM '%s'.", bm.client_name)


def reconciliation_job():
    """Job diário: reconcilia todas as BMs para ontem (roda após collect_insights_job)."""
    logger.info("[scheduler] Iniciando reconciliação...")
    try:
        divergencias = run_reconciliation_for_all_bms()
        logger.info("[scheduler] Reconciliação concluída. Divergências: %d.", len(divergencias))
    except Exception:
        logger.exception("[scheduler] Falha na reconciliação.")


app = create_app()

scheduler = BackgroundScheduler(timezone="UTC")
scheduler.add_job(collect_insights_job, "cron", hour=6, minute=0, id="collect_insights")
scheduler.add_job(reconciliation_job, "cron", hour=7, minute=0, id="reconciliation")
scheduler.start()

port = int(os.getenv("PORT", 5000))
try:
    app.run(debug=False, host="0.0.0.0", port=port)
finally:
    scheduler.shutdown()
