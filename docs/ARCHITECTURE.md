# Arquitetura

## 1. Por que "BMs distintas" não é um problema técnico

Cada Business Manager de cliente concede acesso de **parceiro/admin** a um
System User que pertence à BM "mestre" (LS International). Isso gera um único
access token de longa duração por BM, sem precisar logar com nenhum perfil
pessoal. A camada de integração guarda, por BM, um registro:

```
BMAccount
├── bm_id            (ID da Business Manager do cliente)
├── ad_account_id     (ID da conta de anúncios, formato act_XXXXXXXX)
├── system_user_token (token de longa duração, criptografado em repouso)
├── client_name       (ex: "Centro de Visão", "Alliance Optometria")
└── ativo             (bool)
```

Cada chamada à Meta Marketing API é feita "em nome" do BMAccount certo —
não existe limite técnico para quantas BMs você adiciona, só limite de rate
da própria API (que é por app, então o sistema deve respeitar isso com
fila/retry).

## 2. Fluxo de dados

1. **Coleta de insights** (`meta_api.py`): job periódico (cron ou
   APScheduler) varre todas as `BMAccount` ativas e busca insights de
   campanha/conjunto/anúncio via `/act_<id>/insights`. Grava em
   `CampaignInsight`.

2. **Leads** (`webhooks.py`): a Meta envia um webhook em tempo real quando um
   Instant Form é submetido. O endpoint `/webhooks/meta-leads` recebe o
   evento, busca o lead completo via `/<leadgen_id>` e grava em `Lead` com
   status inicial `recebido_meta`.

3. **Confirmação na planilha/CRM**: um segundo processo (ou webhook do
   Google Sheets / Apps Script, ou polling da API do Sheets) marca o lead
   como `confirmado_planilha` quando ele aparece no destino real. Se um lead
   passa N minutos sem confirmação, isso é uma divergência.

4. **WhatsApp**: para campanhas Click-to-WhatsApp, o clique no anúncio gera
   uma conversa identificável (referral payload). O webhook do WhatsApp
   Business API (`/webhooks/whatsapp`) recebe a mensagem entrante e tenta
   casar com o lead/clique de origem, marcando `confirmado_whatsapp`.

5. **Reconciliação** (`reconciliation.py`): rotina que compara, por
   campanha e por dia: leads reportados pela Meta vs. leads confirmados na
   planilha vs. conversas confirmadas no WhatsApp. Gera registros de
   divergência quando os números não fecham.

6. **Dashboard**: consome as tabelas acima e mostra, por cliente/BM, os
   três números lado a lado + alertas.

## 3. Modelo de dados (resumo)

- `BMAccount` — uma linha por BM/conta de cliente
- `CampaignInsight` — métricas diárias por campanha (gasto, leads reportados, CPL)
- `Lead` — um lead individual, com timestamps de cada etapa de confirmação
- `WhatsAppMessage` — mensagens entrantes vinculadas a uma campanha/clique
- `Divergence` — registros de inconsistência detectada pela reconciliação

## 4. Decisões deliberadas (e por quê)

- **Um único banco para todas as BMs**: simplifica comparação cross-cliente
  e dashboard único. Isolamento lógico é por `bm_id`, não por banco físico.
- **Webhooks em vez de polling para leads/WhatsApp**: menor latência para
  detectar "o lead não chegou".
- **Tokens criptografados em repouso**: mesmo sendo um projeto interno, são
  credenciais de acesso a contas de clientes — tratar como segredo.
