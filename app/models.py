from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import relationship

from app.db import Base


def utcnow():
    return datetime.now(timezone.utc)


class Client(Base):
    """
    Um cliente da LS International (ex: Grupo RM, Centro de Visão).
    Pode ter múltiplas unidades/lojas.
    Tem senha própria para acessar o dashboard e ver só seus dados.
    """

    __tablename__ = "clients"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)                   # ex: "Grupo RM"
    slug = Column(String, nullable=False, unique=True)      # ex: "grupo-rm" (usado na URL)
    web_password_hash = Column(String, nullable=True)       # bcrypt hash da senha do cliente
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=utcnow)

    units = relationship("Unit", back_populates="client", cascade="all, delete-orphan")


class Unit(Base):
    """
    Uma unidade/loja dentro de um cliente (ex: Uberlândia, Feira de Santana).
    Cada unidade tem sua própria conta de anúncios (BMAccount) e
    seu próprio destino de leads (planilha ou CRM).
    """

    __tablename__ = "units"

    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False)

    name = Column(String, nullable=False)                   # ex: "Uberlândia"
    city = Column(String, nullable=True)                    # ex: "Uberlândia - MG"
    spreadsheet_url = Column(String, nullable=True)         # URL da planilha de destino
    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=utcnow)

    client = relationship("Client", back_populates="units")
    bm_accounts = relationship("BMAccount", back_populates="unit")


class BMAccount(Base):
    """Uma conta de anúncios dentro de uma Business Manager, vinculada a uma unidade."""

    __tablename__ = "bm_accounts"

    id = Column(Integer, primary_key=True)
    unit_id = Column(Integer, ForeignKey("units.id"), nullable=False)

    bm_id = Column(String, nullable=False)
    ad_account_id = Column(String, nullable=False, unique=True)  # formato act_XXXXXXXX

    # Token de longa duração do System User, criptografado via app/crypto.encrypt_token()
    system_user_token_encrypted = Column(String, nullable=False)

    ativo = Column(Boolean, default=True)
    criado_em = Column(DateTime, default=utcnow)

    unit = relationship("Unit", back_populates="bm_accounts")
    insights = relationship("CampaignInsight", back_populates="bm_account")
    leads = relationship("Lead", back_populates="bm_account")

    @property
    def client_name(self):
        return self.unit.client.name if self.unit and self.unit.client else "?"

    @property
    def unit_name(self):
        return self.unit.name if self.unit else "?"


class CampaignInsight(Base):
    """Métricas diárias de uma campanha, vindas da Meta Marketing API."""

    __tablename__ = "campaign_insights"

    id = Column(Integer, primary_key=True)
    bm_account_id = Column(Integer, ForeignKey("bm_accounts.id"), nullable=False)

    campaign_id = Column(String, nullable=False)
    campaign_name = Column(String)
    data_referencia = Column(DateTime, nullable=False)

    gasto = Column(Float, default=0)
    impressoes = Column(Integer, default=0)
    cliques = Column(Integer, default=0)
    leads_reportados_meta = Column(Integer, default=0)

    coletado_em = Column(DateTime, default=utcnow)

    bm_account = relationship("BMAccount", back_populates="insights")


class Lead(Base):
    """Um lead individual capturado via Instant Form."""

    __tablename__ = "leads"

    id = Column(Integer, primary_key=True)
    bm_account_id = Column(Integer, ForeignKey("bm_accounts.id"), nullable=True)

    leadgen_id = Column(String, nullable=False, unique=True)
    campaign_id = Column(String)
    nome = Column(String)
    telefone = Column(String)
    email = Column(String)

    recebido_meta_em = Column(DateTime, default=utcnow)
    confirmado_planilha_em = Column(DateTime, nullable=True)
    confirmado_whatsapp_em = Column(DateTime, nullable=True)

    bm_account = relationship("BMAccount", back_populates="leads")


class WhatsAppMessage(Base):
    """Mensagem entrante no WhatsApp Business API, possivelmente vinculada a um lead."""

    __tablename__ = "whatsapp_messages"

    id = Column(Integer, primary_key=True)
    bm_account_id = Column(Integer, ForeignKey("bm_accounts.id"), nullable=True)

    telefone_remetente = Column(String, nullable=False)
    referral_ad_id = Column(String, nullable=True)
    texto = Column(String)

    recebido_em = Column(DateTime, default=utcnow)


class Divergence(Base):
    """Registro gerado pela reconciliação quando os números não fecham."""

    __tablename__ = "divergences"

    id = Column(Integer, primary_key=True)
    bm_account_id = Column(Integer, ForeignKey("bm_accounts.id"), nullable=False)

    campaign_id = Column(String, nullable=False)
    data_referencia = Column(DateTime, nullable=False)

    leads_reportados_meta = Column(Integer, default=0)
    leads_confirmados_planilha = Column(Integer, default=0)
    leads_confirmados_whatsapp = Column(Integer, default=0)

    descricao = Column(String)
    detectado_em = Column(DateTime, default=utcnow)
