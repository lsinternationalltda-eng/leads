# Plataforma Unificada de Campanhas — LS International

Plataforma central para consolidar dados de múltiplas contas do Meta Business
Manager (BMs distintas), cruzar com os destinos reais dos leads (planilhas/CRM
e WhatsApp Business API) e expor um dashboard único de auditoria por cliente.

## O problema que isso resolve

Cada cliente/conta vive numa BM diferente. Hoje, validar se "o que a Meta
reportou" realmente bateu com "o que chegou na planilha" ou "o que chegou no
WhatsApp" é manual. Esta plataforma automatiza essa conferência.

## Arquitetura (visão geral)

```
[BM 1] [BM 2] [BM 3] ...
   \      |      /
    Camada de integração (Meta Marketing API via System User)
                |
        Banco de dados central
           /          \
   Planilhas/CRM    WhatsApp Business API
           \          /
         Dashboard único (divergências e alertas)
```

Detalhes em `docs/ARCHITECTURE.md`.

## Estrutura do projeto

```
meta-leads-platform/
├── app/
│   ├── __init__.py      # factory da aplicação Flask
│   ├── config.py        # configuração (variáveis de ambiente)
│   ├── db.py            # conexão SQLAlchemy
│   ├── models.py        # tabelas: BMAccount, CampaignInsight, Lead, WhatsAppMessage
│   ├── meta_api.py      # cliente da Meta Marketing API (multi-BM)
│   ├── reconciliation.py# lógica de cruzamento/divergência
│   └── webhooks.py      # rotas que recebem leads e mensagens de WhatsApp
├── docs/
│   ├── ARCHITECTURE.md
│   └── SETUP.md
├── main.py              # ponto de entrada
├── requirements.txt
└── .env.example
```

## Status atual

Isto é um **esqueleto funcional**, não o produto final. Os módulos têm a
estrutura, os modelos de dados e os pontos de integração definidos, mas
precisam ser ligados às credenciais reais (token de System User por BM,
IDs das contas de anúncio, endpoint da planilha/CRM, número do WhatsApp
Business). Esse é o próximo passo a continuar dentro do Claude Code.

## Próximos passos sugeridos (em ordem)

1. Preencher `.env` com as credenciais reais (ver `docs/SETUP.md`)
2. Rodar as migrações e validar conexão com 1 BM só
3. Implementar a busca de insights (`app/meta_api.py::fetch_campaign_insights`)
4. Conectar o webhook de Lead Ads de uma conta de teste
5. Conectar o webhook de mensagens do WhatsApp Business API
6. Implementar a lógica de divergência em `app/reconciliation.py`
7. Só depois disso, construir o dashboard (frontend)

Peça ao Claude Code para seguir esse roteiro item por item — cada módulo já
tem comentários `# TODO` marcando exatamente o que falta.
