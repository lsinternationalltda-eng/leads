"""
Blueprint do dashboard web — UI de auditoria de leads.

Dois níveis de acesso:
  - Admin (WEB_PASSWORD): vê tudo, gerencia clientes/unidades/BMs
  - Cliente (senha própria): vê só suas unidades e leads
"""

import logging
import os
from datetime import datetime, timezone
from functools import wraps

from werkzeug.security import generate_password_hash, check_password_hash
from flask import Blueprint, render_template, request, jsonify, session, redirect

from app.db import get_session
from app.models import Client, Unit, BMAccount, CampaignInsight, Lead, WhatsAppMessage, Divergence
from app.crypto import encrypt_token
from app.meta_api import get_client_for_bm
from app.reconciliation import run_reconciliation_for_all_bms

logger = logging.getLogger(__name__)
dashboard_bp = Blueprint("dashboard", __name__)

WEB_PASSWORD = os.getenv("WEB_PASSWORD") or os.getenv("ADMIN_TOKEN", "")


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logado"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "Não autorizado"}), 401
            return redirect("/")
        return f(*args, **kwargs)
    return decorated


def _is_admin():
    return session.get("role") == "admin"


def _client_id():
    return session.get("client_id")


def _unit_ids_for_session(db):
    """Retorna lista de unit_ids que o usuário logado pode ver."""
    if _is_admin():
        return [u.id for u in db.query(Unit).all()]
    cid = _client_id()
    if cid:
        return [u.id for u in db.query(Unit).filter(Unit.client_id == cid).all()]
    return []


def _bm_ids_for_session(db):
    unit_ids = _unit_ids_for_session(db)
    if not unit_ids:
        return []
    return [b.id for b in db.query(BMAccount).filter(BMAccount.unit_id.in_(unit_ids)).all()]


# ---------------------------------------------------------------------------
# Rotas de auth
# ---------------------------------------------------------------------------

@dashboard_bp.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        senha = request.form.get("senha", "")
        # Verificar admin
        if senha and senha == WEB_PASSWORD:
            session["logado"] = True
            session["role"] = "admin"
            return redirect("/")
        # Verificar clientes
        db = get_session()
        try:
            clientes = db.query(Client).filter(Client.ativo.is_(True)).all()
            for c in clientes:
                if c.web_password_hash and check_password_hash(c.web_password_hash, senha):
                    session["logado"] = True
                    session["role"] = "client"
                    session["client_id"] = c.id
                    session["client_name"] = c.name
                    return redirect("/")
        finally:
            db.close()
        return render_template("login.html", erro="Senha incorreta.")

    if not session.get("logado"):
        return render_template("login.html", erro=None)
    # Sessões antigas sem 'role' são tratadas como admin
    if not session.get("role"):
        session["role"] = "admin"
    return render_template("dashboard.html",
                           is_admin=_is_admin(),
                           client_name=session.get("client_name", "Admin"))


@dashboard_bp.route("/login", methods=["GET", "POST"])
def login():
    return redirect("/")


@dashboard_bp.route("/logout")
def logout():
    session.clear()
    return redirect("/")


# ---------------------------------------------------------------------------
# API — Stats
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/stats")
@login_required
def api_stats():
    from datetime import timedelta
    period = request.args.get("period", "last_7d")
    unit_id = request.args.get("unit_id", type=int)

    db = get_session()
    try:
        bm_ids = _bm_ids_for_session(db)
        if unit_id:
            unit_bms = [b.id for b in db.query(BMAccount).filter(BMAccount.unit_id == unit_id).all()]
            bm_ids = [b for b in bm_ids if b in unit_bms]

        # Leads
        total_leads = db.query(Lead).filter(Lead.bm_account_id.in_(bm_ids)).count() if bm_ids else 0
        # Form = veio via Meta Lead Ads webhook (tem leadgen_id)
        leads_form = db.query(Lead).filter(
            Lead.bm_account_id.in_(bm_ids), Lead.leadgen_id.isnot(None)
        ).count() if bm_ids else 0
        # Mensagem/WA = confirmado via WhatsApp (chegou como conversa)
        leads_mensagem = db.query(Lead).filter(
            Lead.bm_account_id.in_(bm_ids), Lead.confirmado_whatsapp_em.isnot(None)
        ).count() if bm_ids else 0
        conf_pl = db.query(Lead).filter(
            Lead.bm_account_id.in_(bm_ids), Lead.confirmado_planilha_em.isnot(None)
        ).count() if bm_ids else 0
        n_div = db.query(Divergence).filter(Divergence.bm_account_id.in_(bm_ids)).count() if bm_ids else 0

        if _is_admin():
            n_clientes = db.query(Client).filter(Client.ativo.is_(True)).count()
            n_units = db.query(Unit).filter(Unit.ativo.is_(True)).count()
        else:
            cid = _client_id()
            n_clientes = 1
            n_units = db.query(Unit).filter(Unit.client_id == cid, Unit.ativo.is_(True)).count()

        # Métricas de campanha para o período
        now = datetime.now(timezone.utc)
        dias = {"today": 1, "yesterday": 2, "last_7d": 7, "last_14d": 14, "last_30d": 30}.get(period, 7)
        start = (now - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)

        insights = db.query(CampaignInsight).filter(
            CampaignInsight.bm_account_id.in_(bm_ids),
            CampaignInsight.data_referencia >= start,
        ).all() if bm_ids else []

        total_gasto = sum(i.gasto for i in insights)
        total_leads_meta = sum(i.leads_reportados_meta for i in insights)
        cpl_geral = round(total_gasto / total_leads_meta, 2) if total_leads_meta > 0 else None
        campanhas_ids = {i.campaign_id for i in insights if i.campaign_id}

        return jsonify({
            "total_leads": total_leads,
            "leads_form": leads_form,
            "leads_mensagem": leads_mensagem,
            "confirmados_planilha": conf_pl,
            "divergencias": n_div,
            "clientes": n_clientes,
            "unidades": n_units,
            # Campanha
            "total_gasto": round(total_gasto, 2),
            "cpl_geral": cpl_geral,
            "campanhas_ativas": len(campanhas_ids),
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — Leads
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/leads")
@login_required
def api_leads():
    page = int(request.args.get("page", 1))
    per = min(int(request.args.get("per_page", 30)), 100)
    unit_filter = request.args.get("unit_id")

    db = get_session()
    try:
        bm_ids = _bm_ids_for_session(db)
        if unit_filter:
            unit_bm_ids = [b.id for b in db.query(BMAccount).filter(BMAccount.unit_id == int(unit_filter)).all()]
            bm_ids = [b for b in bm_ids if b in unit_bm_ids]

        q = db.query(Lead, BMAccount, Unit, Client)\
            .join(BMAccount, Lead.bm_account_id == BMAccount.id)\
            .join(Unit, BMAccount.unit_id == Unit.id)\
            .join(Client, Unit.client_id == Client.id)\
            .filter(Lead.bm_account_id.in_(bm_ids)) if bm_ids else None

        total = q.count() if q else 0
        rows = q.order_by(Lead.recebido_meta_em.desc()).offset((page-1)*per).limit(per).all() if q else []

        return jsonify({
            "total": total,
            "page": page,
            "per_page": per,
            "items": [
                {
                    "id": r.Lead.id,
                    "leadgen_id": r.Lead.leadgen_id,
                    "campaign_id": r.Lead.campaign_id,
                    "nome": r.Lead.nome,
                    "telefone": r.Lead.telefone,
                    "email": r.Lead.email,
                    "cliente": r.Client.name,
                    "unidade": r.Unit.name,
                    "cidade": r.Unit.city,
                    "recebido_em": r.Lead.recebido_meta_em.isoformat() if r.Lead.recebido_meta_em else None,
                    "conf_planilha": bool(r.Lead.confirmado_planilha_em),
                    "conf_whatsapp": bool(r.Lead.confirmado_whatsapp_em),
                }
                for r in rows
            ],
        })
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — Divergências
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/divergencias")
@login_required
def api_divergencias():
    db = get_session()
    try:
        bm_ids = _bm_ids_for_session(db)
        if not bm_ids:
            return jsonify([])

        rows = db.query(Divergence, BMAccount, Unit, Client)\
            .join(BMAccount, Divergence.bm_account_id == BMAccount.id)\
            .join(Unit, BMAccount.unit_id == Unit.id)\
            .join(Client, Unit.client_id == Client.id)\
            .filter(Divergence.bm_account_id.in_(bm_ids))\
            .order_by(Divergence.detectado_em.desc())\
            .limit(200).all()

        return jsonify([
            {
                "id": r.Divergence.id,
                "cliente": r.Client.name,
                "unidade": r.Unit.name,
                "campaign_id": r.Divergence.campaign_id,
                "data": r.Divergence.data_referencia.strftime("%d/%m/%Y") if r.Divergence.data_referencia else None,
                "meta": r.Divergence.leads_reportados_meta,
                "planilha": r.Divergence.leads_confirmados_planilha,
                "whatsapp": r.Divergence.leads_confirmados_whatsapp,
                "descricao": r.Divergence.descricao,
            }
            for r in rows
        ])
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — Clientes (admin only)
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/clients")
@login_required
def api_clients():
    if not _is_admin():
        return jsonify({"error": "Acesso restrito"}), 403
    db = get_session()
    try:
        clients = db.query(Client).order_by(Client.criado_em).all()
        result = []
        for c in clients:
            units = db.query(Unit).filter(Unit.client_id == c.id).all()
            result.append({
                "id": c.id,
                "name": c.name,
                "slug": c.slug,
                "ativo": c.ativo,
                "criado_em": c.criado_em.strftime("%d/%m/%Y") if c.criado_em else None,
                "tem_senha": bool(c.web_password_hash),
                "unidades": [
                    {
                        "id": u.id,
                        "name": u.name,
                        "city": u.city,
                        "spreadsheet_url": u.spreadsheet_url,
                        "ativo": u.ativo,
                        "bms": db.query(BMAccount).filter(BMAccount.unit_id == u.id).count(),
                    }
                    for u in units
                ],
            })
        return jsonify(result)
    finally:
        db.close()


@dashboard_bp.route("/api/clients/<int:client_id>/senha", methods=["PATCH"])
@login_required
def api_atualizar_senha_client(client_id):
    if not _is_admin():
        return jsonify({"error": "Acesso restrito"}), 403
    data = request.get_json(silent=True) or {}
    senha = data.get("senha", "").strip()
    if not senha:
        return jsonify({"error": "Senha não pode ser vazia"}), 400
    db = get_session()
    try:
        c = db.query(Client).filter(Client.id == client_id).first()
        if not c:
            return jsonify({"error": "Cliente não encontrado"}), 404
        c.web_password_hash = generate_password_hash(senha)
        db.commit()
        return jsonify({"ok": True})
    except Exception as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        db.close()


@dashboard_bp.route("/api/clients", methods=["POST"])
@login_required
def api_criar_client():
    if not _is_admin():
        return jsonify({"error": "Acesso restrito"}), 403
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    senha = data.get("senha", "").strip()
    if not name:
        return jsonify({"error": "Nome obrigatório"}), 400

    slug = name.lower().replace(" ", "-").replace("_", "-")
    db = get_session()
    try:
        c = Client(
            name=name,
            slug=slug,
            web_password_hash=generate_password_hash(senha) if senha else None,
        )
        db.add(c)
        db.commit()
        return jsonify({"id": c.id, "name": c.name, "slug": c.slug}), 201
    except Exception as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — Unidades
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/units")
@login_required
def api_units():
    db = get_session()
    try:
        unit_ids = _unit_ids_for_session(db)
        units = db.query(Unit, Client)\
            .join(Client, Unit.client_id == Client.id)\
            .filter(Unit.id.in_(unit_ids))\
            .order_by(Client.name, Unit.name).all()
        return jsonify([
            {
                "id": u.Unit.id,
                "name": u.Unit.name,
                "city": u.Unit.city,
                "client_id": u.Unit.client_id,
                "client_name": u.Client.name,
                "spreadsheet_url": u.Unit.spreadsheet_url,
                "ativo": u.Unit.ativo,
            }
            for u in units
        ])
    finally:
        db.close()


@dashboard_bp.route("/api/units", methods=["POST"])
@login_required
def api_criar_unit():
    if not _is_admin():
        return jsonify({"error": "Acesso restrito"}), 403
    data = request.get_json(silent=True) or {}
    client_id = data.get("client_id")
    name = data.get("name", "").strip()
    if not client_id or not name:
        return jsonify({"error": "client_id e name são obrigatórios"}), 400

    db = get_session()
    try:
        u = Unit(
            client_id=int(client_id),
            name=name,
            city=data.get("city", "").strip() or None,
            spreadsheet_url=data.get("spreadsheet_url", "").strip() or None,
        )
        db.add(u)
        db.commit()
        return jsonify({"id": u.id, "name": u.name}), 201
    except Exception as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — BM Accounts
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/bm-accounts", methods=["POST"])
@login_required
def api_criar_bm():
    if not _is_admin():
        return jsonify({"error": "Acesso restrito"}), 403
    data = request.get_json(silent=True) or {}
    unit_id = data.get("unit_id")
    bm_id = data.get("bm_id", "").strip()
    ad_account_id = data.get("ad_account_id", "").strip()
    token = data.get("system_user_token", "").strip()

    if not all([unit_id, bm_id, ad_account_id, token]):
        return jsonify({"error": "Campos obrigatórios: unit_id, bm_id, ad_account_id, system_user_token"}), 400

    if not ad_account_id.startswith("act_"):
        ad_account_id = f"act_{ad_account_id}"

    db = get_session()
    try:
        token_enc = encrypt_token(token)
        bm = BMAccount(
            unit_id=int(unit_id),
            bm_id=bm_id,
            ad_account_id=ad_account_id,
            system_user_token_encrypted=token_enc,
        )
        db.add(bm)
        db.commit()
        return jsonify({"id": bm.id, "ad_account_id": bm.ad_account_id}), 201
    except Exception as exc:
        db.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — Campanhas (insights agregados por período)
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/campaigns")
@login_required
def api_campaigns():
    from datetime import timedelta
    period = request.args.get("period", "last_7d")
    unit_id = request.args.get("unit_id", type=int)

    db = get_session()
    try:
        bm_ids = _bm_ids_for_session(db)
        if unit_id:
            unit_bms = [b.id for b in db.query(BMAccount).filter(BMAccount.unit_id == unit_id).all()]
            bm_ids = [b for b in bm_ids if b in unit_bms]
        if not bm_ids:
            return jsonify([])

        now = datetime.now(timezone.utc)
        dias = {"today": 1, "yesterday": 2, "last_7d": 7, "last_14d": 14, "last_30d": 30}.get(period, 7)
        start = (now - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)

        insights = db.query(CampaignInsight).filter(
            CampaignInsight.bm_account_id.in_(bm_ids),
            CampaignInsight.data_referencia >= start,
        ).all()

        camps: dict = {}
        for ins in insights:
            cid = ins.campaign_id or "?"
            if cid not in camps:
                camps[cid] = {
                    "campaign_id": cid,
                    "campaign_name": ins.campaign_name or cid,
                    "gasto": 0.0, "leads": 0, "cliques": 0, "impressoes": 0,
                }
            camps[cid]["gasto"] += ins.gasto
            camps[cid]["leads"] += ins.leads_reportados_meta
            camps[cid]["cliques"] += ins.cliques
            camps[cid]["impressoes"] += ins.impressoes

        result = []
        for c in camps.values():
            leads = c["leads"]
            gasto = c["gasto"]
            impr = c["impressoes"]
            c["cpl"] = round(gasto / leads, 2) if leads > 0 else None
            c["ctr"] = round(c["cliques"] / impr * 100, 2) if impr > 0 else 0.0
            c["gasto"] = round(gasto, 2)
            # Inferir tipo pelo nome
            nome = c["campaign_name"].lower()
            if any(x in nome for x in ["whatsapp", "wpp", "zap", "conversa", "clique"]):
                c["tipo"] = "WA"
            elif any(x in nome for x in ["form", "formulário", "lead gen", "instante"]):
                c["tipo"] = "Form"
            elif any(x in nome for x in ["conv", "compra", "vend", "pix"]):
                c["tipo"] = "Conv"
            else:
                c["tipo"] = "—"
            result.append(c)

        result.sort(key=lambda x: x["leads"], reverse=True)
        return jsonify(result)
    finally:
        db.close()


@dashboard_bp.route("/api/leads-timeline")
@login_required
def api_leads_timeline():
    from datetime import timedelta
    period = request.args.get("period", "last_30d")
    unit_id = request.args.get("unit_id", type=int)

    db = get_session()
    try:
        bm_ids = _bm_ids_for_session(db)
        if unit_id:
            unit_bms = [b.id for b in db.query(BMAccount).filter(BMAccount.unit_id == unit_id).all()]
            bm_ids = [b for b in bm_ids if b in unit_bms]
        if not bm_ids:
            return jsonify({"labels": [], "leads": [], "gasto": []})

        dias = {"today": 1, "yesterday": 2, "last_7d": 7, "last_14d": 14, "last_30d": 30}.get(period, 30)
        now = datetime.now(timezone.utc)
        start = (now - timedelta(days=dias)).replace(hour=0, minute=0, second=0, microsecond=0)

        insights = db.query(CampaignInsight).filter(
            CampaignInsight.bm_account_id.in_(bm_ids),
            CampaignInsight.data_referencia >= start,
        ).all()

        by_day: dict = {}
        for ins in insights:
            day = ins.data_referencia.strftime("%d/%m")
            by_day.setdefault(day, {"leads": 0, "gasto": 0.0})
            by_day[day]["leads"] += ins.leads_reportados_meta
            by_day[day]["gasto"] += ins.gasto

        labels, leads_data, gasto_data = [], [], []
        for i in range(dias):
            d = now - timedelta(days=dias - 1 - i)
            label = d.strftime("%d/%m")
            labels.append(label)
            leads_data.append(by_day.get(label, {}).get("leads", 0))
            gasto_data.append(round(by_day.get(label, {}).get("gasto", 0.0), 2))

        return jsonify({"labels": labels, "leads": leads_data, "gasto": gasto_data})
    finally:
        db.close()


@dashboard_bp.route("/api/alerts")
@login_required
def api_alerts():
    from datetime import timedelta
    unit_id = request.args.get("unit_id", type=int)

    db = get_session()
    try:
        bm_ids = _bm_ids_for_session(db)
        if unit_id:
            unit_bms = [b.id for b in db.query(BMAccount).filter(BMAccount.unit_id == unit_id).all()]
            bm_ids = [b for b in bm_ids if b in unit_bms]
        if not bm_ids:
            return jsonify([])

        alerts = []
        now = datetime.now(timezone.utc)

        # Divergências ativas
        n_div = db.query(Divergence).filter(Divergence.bm_account_id.in_(bm_ids)).count()
        if n_div > 0:
            alerts.append({"nivel": "error", "msg": f"{n_div} divergência(s) ativa(s) — leads Meta não chegaram no destino"})

        # Unidades sem leads nos últimos 7 dias
        unidade_ids_vistas = set()
        for bm_id in bm_ids:
            bm = db.query(BMAccount).filter(BMAccount.id == bm_id).first()
            if not bm or bm.unit_id in unidade_ids_vistas:
                continue
            unidade_ids_vistas.add(bm.unit_id)
            recente = db.query(Lead).filter(
                Lead.bm_account_id == bm_id,
                Lead.recebido_meta_em >= now - timedelta(days=7),
            ).count()
            if recente == 0:
                alerts.append({"nivel": "warn", "msg": f"Unidade '{bm.unit_name}' sem leads nos últimos 7 dias"})

        # CPL alto (>R$50 nos últimos 7 dias)
        insights = db.query(CampaignInsight).filter(
            CampaignInsight.bm_account_id.in_(bm_ids),
            CampaignInsight.data_referencia >= now - timedelta(days=7),
        ).all()
        camp_agg: dict = {}
        for ins in insights:
            cid = ins.campaign_id or "?"
            camp_agg.setdefault(cid, {"name": ins.campaign_name or cid, "gasto": 0.0, "leads": 0})
            camp_agg[cid]["gasto"] += ins.gasto
            camp_agg[cid]["leads"] += ins.leads_reportados_meta

        for c in camp_agg.values():
            if c["leads"] > 0:
                cpl = c["gasto"] / c["leads"]
                if cpl > 50:
                    alerts.append({"nivel": "warn", "msg": f"CPL alto em '{c['name'][:35]}': R${cpl:.2f}"})

        return jsonify(alerts)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API — Sync
# ---------------------------------------------------------------------------

@dashboard_bp.route("/api/sync", methods=["POST"])
@login_required
def api_sync():
    if not _is_admin():
        return jsonify({"error": "Acesso restrito"}), 403

    body = request.get_json(silent=True) or {}
    date_preset = body.get("date_preset", "yesterday")

    db = get_session()
    try:
        bm_accounts = db.query(BMAccount).filter(BMAccount.ativo.is_(True)).all()
    finally:
        db.close()

    data_ref = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0
    erros = []

    for bm in bm_accounts:
        try:
            client = get_client_for_bm(bm)
            insights = client.fetch_campaign_insights(date_preset=date_preset)
            db2 = get_session()
            try:
                for ins in insights:
                    ex = db2.query(CampaignInsight).filter_by(
                        bm_account_id=bm.id, campaign_id=ins["campaign_id"], data_referencia=data_ref,
                    ).first()
                    if ex:
                        for k, v in ins.items():
                            setattr(ex, k, v)
                    else:
                        db2.add(CampaignInsight(bm_account_id=bm.id, data_referencia=data_ref, **ins))
                db2.commit()
                total += len(insights)
            finally:
                db2.close()
        except Exception as exc:
            erros.append({"bm": bm.ad_account_id, "erro": str(exc)})

    divs = []
    try:
        divs = run_reconciliation_for_all_bms()
    except Exception:
        logger.exception("Reconciliação pós-sync")

    return jsonify({"insights": total, "divergencias": len(divs), "erros": erros})
