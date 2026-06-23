"""
Rotas de webhook. Duas integrações distintas chegam aqui:

  1. /webhooks/meta-leads   -> notificação de novo Instant Form preenchido
  2. /webhooks/whatsapp     -> mensagens entrantes no WhatsApp Business API

Ambas seguem o padrão Meta de verificação: GET para validar o endpoint na
hora de cadastrar o webhook no painel, POST para receber os eventos reais.
"""

import logging
import re
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify

from app.config import Config
from app.db import get_session
from app.models import BMAccount, Lead, WhatsAppMessage
from app.meta_api import get_client_for_bm

logger = logging.getLogger(__name__)
webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _verify_challenge():
    """Lógica comum de verificação usada pelos dois webhooks no GET."""
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == Config.WEBHOOK_VERIFY_TOKEN:
        return challenge, 200
    return "Token de verificação inválido", 403


def _extrair_campo(field_data: list[dict], *nomes: str) -> str | None:
    """Extrai o primeiro valor de um campo pelo nome, tentando vários aliases em sequência."""
    for campo in field_data:
        if campo.get("name") in nomes:
            valores = campo.get("values", [])
            return valores[0] if valores else None
    return None


def _normalizar_telefone(telefone: str | None) -> str | None:
    """
    Remove caracteres não-numéricos e garante prefixo +55 para números brasileiros.
    Retorna None se o telefone for nulo ou inválido.
    """
    if not telefone:
        return None
    digits = re.sub(r"\D", "", telefone)
    if not digits:
        return None
    # Número brasileiro sem código de país (10 ou 11 dígitos)
    if len(digits) in (10, 11):
        digits = "55" + digits
    return "+" + digits


# ---------------------------------------------------------------------------
# Webhook de Lead Ads
# ---------------------------------------------------------------------------

@webhooks_bp.route("/meta-leads", methods=["GET"])
def verify_meta_leads_webhook():
    return _verify_challenge()


@webhooks_bp.route("/meta-leads", methods=["POST"])
def receive_meta_lead():
    payload = request.get_json(silent=True) or {}

    session = get_session()
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                leadgen_id = value.get("leadgen_id")
                ad_account_id = value.get("ad_account_id")
                campaign_id = value.get("campaign_id")

                if not leadgen_id:
                    continue

                # Evitar duplicatas — Meta pode reenviar o mesmo evento
                if session.query(Lead).filter_by(leadgen_id=leadgen_id).first():
                    logger.debug("Lead %s já existe, ignorando.", leadgen_id)
                    continue

                # Meta às vezes omite o prefixo 'act_'
                if ad_account_id and not str(ad_account_id).startswith("act_"):
                    ad_account_id = f"act_{ad_account_id}"

                bm_account = (
                    session.query(BMAccount)
                    .filter(BMAccount.ad_account_id == ad_account_id)
                    .first()
                ) if ad_account_id else None

                # Buscar field_data completo via Graph API para obter nome/telefone/email
                nome = email = telefone = None
                if bm_account:
                    try:
                        client = get_client_for_bm(bm_account)
                        lead_data = client.fetch_lead_details(leadgen_id)
                        field_data = lead_data.get("field_data", [])
                        nome = _extrair_campo(field_data, "full_name", "name", "nome")
                        email = _extrair_campo(field_data, "email", "e-mail")
                        telefone = _normalizar_telefone(
                            _extrair_campo(
                                field_data,
                                "phone_number", "phone", "telefone", "celular", "whatsapp",
                            )
                        )
                    except Exception:
                        logger.exception("Falha ao buscar field_data para lead %s — salvo sem dados de contato.", leadgen_id)

                lead = Lead(
                    bm_account_id=bm_account.id if bm_account else None,
                    leadgen_id=leadgen_id,
                    campaign_id=campaign_id,
                    nome=nome,
                    telefone=telefone,
                    email=email,
                )
                session.add(lead)
                logger.info("Lead %s recebido (cliente: %s, nome: %s).",
                            leadgen_id, bm_account.client_name if bm_account else "?", nome)

        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Erro ao processar webhook de lead")
        raise
    finally:
        session.close()

    return jsonify({"status": "ok"}), 200


# ---------------------------------------------------------------------------
# Webhook do WhatsApp Business API
# ---------------------------------------------------------------------------

@webhooks_bp.route("/whatsapp", methods=["GET"])
def verify_whatsapp_webhook():
    return _verify_challenge()


@webhooks_bp.route("/whatsapp", methods=["POST"])
def receive_whatsapp_message():
    payload = request.get_json(silent=True) or {}

    session = get_session()
    try:
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    referral = msg.get("referral", {})  # presente em Click-to-WhatsApp
                    telefone_remetente = msg.get("from")
                    telefone_normalizado = _normalizar_telefone(telefone_remetente)

                    whatsapp_msg = WhatsAppMessage(
                        telefone_remetente=telefone_remetente,
                        referral_ad_id=referral.get("source_id"),
                        texto=msg.get("text", {}).get("body"),
                    )

                    # Tentar casar com lead existente pelo telefone normalizado
                    lead_match = None
                    if telefone_normalizado:
                        lead_match = (
                            session.query(Lead)
                            .filter(
                                Lead.telefone == telefone_normalizado,
                                Lead.confirmado_whatsapp_em.is_(None),
                            )
                            .order_by(Lead.recebido_meta_em.desc())
                            .first()
                        )

                    if lead_match:
                        lead_match.confirmado_whatsapp_em = _utcnow()
                        whatsapp_msg.bm_account_id = lead_match.bm_account_id
                        logger.info(
                            "Lead %s confirmado via WhatsApp (telefone %s).",
                            lead_match.leadgen_id, telefone_normalizado,
                        )

                    session.add(whatsapp_msg)

        session.commit()
    except Exception:
        session.rollback()
        logger.exception("Erro ao processar webhook do WhatsApp")
        raise
    finally:
        session.close()

    return jsonify({"status": "ok"}), 200
