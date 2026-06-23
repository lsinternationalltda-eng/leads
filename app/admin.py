"""
Blueprint de administração interna — cadastro de BMs e trigger manual de sync.
Protegido por token via header X-Admin-Token (definido em .env como ADMIN_TOKEN).

Rotas:
  GET  /admin/bm-accounts         — lista todas as BMs cadastradas
  POST /admin/bm-accounts         — cadastra nova BM (criptografa o token)
  POST /admin/sync                — coleta insights + reconcilia agora (todas as BMs ativas)
"""

import logging
import os
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from app.db import get_session
from app.models import BMAccount, CampaignInsight
from app.crypto import encrypt_token
from app.meta_api import get_client_for_bm
from app.reconciliation import run_reconciliation_for_all_bms

logger = logging.getLogger(__name__)
admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

_ADMIN_TOKEN = os.getenv("ADMIN_TOKEN")


def _require_admin():
    if not _ADMIN_TOKEN:
        return jsonify({"error": "ADMIN_TOKEN não configurado no servidor."}), 500
    if request.headers.get("X-Admin-Token") != _ADMIN_TOKEN:
        return jsonify({"error": "Não autorizado"}), 401
    return None


@admin_bp.route("/bm-accounts", methods=["GET"])
def listar_bms():
    err = _require_admin()
    if err:
        return err

    session = get_session()
    try:
        bms = session.query(BMAccount).order_by(BMAccount.criado_em).all()
        return jsonify([
            {
                "id": bm.id,
                "bm_id": bm.bm_id,
                "ad_account_id": bm.ad_account_id,
                "client_name": bm.client_name,
                "ativo": bm.ativo,
                "criado_em": bm.criado_em.isoformat() if bm.criado_em else None,
            }
            for bm in bms
        ])
    finally:
        session.close()


@admin_bp.route("/bm-accounts", methods=["POST"])
def criar_bm():
    err = _require_admin()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    bm_id = data.get("bm_id")
    ad_account_id = data.get("ad_account_id")
    client_name = data.get("client_name")
    system_user_token = data.get("system_user_token")

    if not all([bm_id, ad_account_id, client_name, system_user_token]):
        return jsonify({"error": "Campos obrigatórios: bm_id, ad_account_id, client_name, system_user_token"}), 400

    if not str(ad_account_id).startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    session = get_session()
    try:
        token_cifrado = encrypt_token(system_user_token)
        bm = BMAccount(
            bm_id=bm_id,
            ad_account_id=ad_account_id,
            client_name=client_name,
            system_user_token_encrypted=token_cifrado,
        )
        session.add(bm)
        session.commit()
        logger.info("BM cadastrada: %s (%s)", client_name, ad_account_id)
        return jsonify({"id": bm.id, "client_name": bm.client_name, "ad_account_id": bm.ad_account_id}), 201
    except Exception as exc:
        session.rollback()
        logger.exception("Falha ao cadastrar BM")
        return jsonify({"error": str(exc)}), 500
    finally:
        session.close()


@admin_bp.route("/sync", methods=["POST"])
def sync_agora():
    """Coleta insights de todas as BMs ativas e roda a reconciliação em seguida."""
    err = _require_admin()
    if err:
        return err

    body = request.get_json(silent=True) or {}
    date_preset = body.get("date_preset", "yesterday")

    session = get_session()
    try:
        bm_accounts = session.query(BMAccount).filter(BMAccount.ativo.is_(True)).all()
    finally:
        session.close()

    data_ref = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total_insights = 0
    erros: list[dict] = []

    for bm in bm_accounts:
        try:
            client = get_client_for_bm(bm)
            insights = client.fetch_campaign_insights(date_preset=date_preset)

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
                total_insights += len(insights)
                logger.info("Sync BM '%s': %d insights.", bm.client_name, len(insights))
            finally:
                session2.close()

        except Exception as exc:
            logger.exception("Falha no sync da BM %s", bm.client_name)
            erros.append({"bm": bm.client_name, "erro": str(exc)})

    divergencias = []
    try:
        divs = run_reconciliation_for_all_bms()
        divergencias = [
            {
                "bm_account_id": d.bm_account_id,
                "campaign_id": d.campaign_id,
                "descricao": d.descricao,
            }
            for d in divs
        ]
    except Exception:
        logger.exception("Falha na reconciliação pós-sync")

    return jsonify({
        "insights_sincronizados": total_insights,
        "divergencias_detectadas": len(divergencias),
        "divergencias": divergencias,
        "erros": erros,
    })
