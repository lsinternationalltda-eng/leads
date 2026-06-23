# Setup

## 1. Pré-requisitos na Meta for Developers

1. Crie (ou use) um App no [Meta for Developers](https://developers.facebook.com/).
2. Adicione os produtos: **Marketing API** e **Webhooks**.
3. No Business Manager mestre (LS International), crie um **System User**
   com papel de admin.
4. Para cada BM de cliente: peça para ser adicionado como parceiro/admin
   da conta de anúncios, e atribua o System User a essa conta dentro do
   Business Manager mestre (Configurações do negócio > Usuários > Usuários
   do sistema > Adicionar ativos).
5. Gere um token de longa duração para o System User com as permissões:
   `ads_read`, `leads_retrieval`, `pages_messaging` (se for usar webhook do
   WhatsApp pela mesma estrutura).

## 2. Variáveis de ambiente

Copie `.env.example` para `.env` e preencha:

```
DATABASE_URL=sqlite:///local.db          # troque por Postgres em produção
META_APP_ID=
META_APP_SECRET=
WEBHOOK_VERIFY_TOKEN=                    # string que você escolhe, usada na verificação do webhook
WHATSAPP_BUSINESS_TOKEN=
WHATSAPP_PHONE_NUMBER_ID=
GOOGLE_SHEETS_CREDENTIALS_PATH=          # caminho do JSON de service account, se for usar Sheets API
```

Os tokens por BM (`system_user_token` de cada conta) **não** vão no `.env`
— eles são cadastrados via a tabela `BMAccount`, um por cliente, depois que
o banco estiver de pé (ver próximo passo).

## 3. Rodando localmente

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

Isso sobe o servidor Flask em `localhost:5000` com as rotas de webhook e a
API interna.

## 4. Cadastrando a primeira BM de teste

Depois que o banco estiver criado (`main.py` cria as tabelas automaticamente
no primeiro boot), insira uma `BMAccount` de teste — o Claude Code pode te
ajudar a escrever esse script de seed quando você tiver o primeiro token em
mãos.

## 5. Expondo os webhooks publicamente (dev)

Para a Meta conseguir chamar `/webhooks/meta-leads` e `/webhooks/whatsapp`
durante o desenvolvimento, use um túnel (ngrok ou similar) e registre a URL
pública no painel do App em Webhooks.
