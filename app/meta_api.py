"""
Cliente da Meta Marketing API, desenhado para operar sobre várias contas de
anúncio (uma por BM de cliente), cada uma com seu próprio token de System User.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

META_API_VERSION = "v19.0"
META_API_BASE = f"https://graph.facebook.com/{META_API_VERSION}"

# Códigos de erro da Meta que indicam rate limit — devem ser tratados com retry.
RATE_LIMIT_CODES = {17, 32, 613, 80004}
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2  # segundos; espera = BASE^(tentativa)


class RateLimitError(Exception):
    pass


class MetaAdsClient:
    def __init__(self, ad_account_id: str, access_token: str):
        """
        ad_account_id: formato 'act_XXXXXXXXXXXX'
        access_token: token de longa duração do System User com acesso a essa conta
        """
        self.ad_account_id = ad_account_id
        self.access_token = access_token

    def _get(self, path: str, params: dict | None = None) -> dict:
        params = params or {}
        params["access_token"] = self.access_token
        url = f"{META_API_BASE}/{path}"

        for attempt in range(MAX_RETRIES):
            resp = requests.get(url, params=params, timeout=30)
            data = resp.json()

            error_code = (data.get("error") or {}).get("code")
            if error_code in RATE_LIMIT_CODES:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                logger.warning("Rate limit Meta (código %s). Tentativa %d/%d — aguardando %ss.",
                               error_code, attempt + 1, MAX_RETRIES, wait)
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return data

        raise RateLimitError(f"Rate limit persistente após {MAX_RETRIES} tentativas.")

    def _get_paginated(self, path: str, params: dict | None = None) -> list[dict]:
        """Busca todos os registros percorrendo os cursores de paginação da Meta API."""
        params = params or {}
        params["access_token"] = self.access_token
        url = f"{META_API_BASE}/{path}"
        resultados: list[dict] = []

        while url:
            for attempt in range(MAX_RETRIES):
                resp = requests.get(url, params=params, timeout=30)
                data = resp.json()

                error_code = (data.get("error") or {}).get("code")
                if error_code in RATE_LIMIT_CODES:
                    wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                    logger.warning("Rate limit Meta (código %s) na paginação. Aguardando %ss.", error_code, wait)
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                resultados.extend(data.get("data", []))
                # A URL de 'next' já carrega todos os parâmetros, incluindo o cursor
                url = data.get("paging", {}).get("next")
                params = {}  # não reenviar params para evitar conflito com cursor embutido
                break
            else:
                raise RateLimitError(f"Rate limit persistente após {MAX_RETRIES} tentativas durante paginação.")

        return resultados

    def fetch_campaign_insights(self, date_preset: str = "yesterday") -> list[dict]:
        """
        Busca insights de todas as campanhas da conta para o período informado,
        percorrendo todas as páginas de resultado.

        date_preset aceita os valores padrão da Meta API: 'today', 'yesterday',
        'last_7d', 'last_30d', etc.
        """
        fields = "campaign_id,campaign_name,spend,impressions,clicks,actions"
        rows = self._get_paginated(
            f"{self.ad_account_id}/insights",
            params={
                "level": "campaign",
                "fields": fields,
                "date_preset": date_preset,
            },
        )

        resultados = []
        for row in rows:
            leads = 0
            for action in row.get("actions", []):
                if action.get("action_type") == "lead":
                    leads = int(action.get("value", 0))
                    break

            resultados.append(
                {
                    "campaign_id": row.get("campaign_id"),
                    "campaign_name": row.get("campaign_name"),
                    "gasto": float(row.get("spend", 0)),
                    "impressoes": int(row.get("impressions", 0)),
                    "cliques": int(row.get("clicks", 0)),
                    "leads_reportados_meta": leads,
                }
            )
        return resultados

    def fetch_lead_details(self, leadgen_id: str) -> dict:
        """Busca os dados completos de um lead a partir do leadgen_id recebido via webhook."""
        return self._get(leadgen_id, params={"fields": "field_data,created_time"})


def get_client_for_bm(bm_account) -> MetaAdsClient:
    """
    Recebe um registro BMAccount (do banco) e devolve um MetaAdsClient pronto para
    uso, com o token descriptografado em memória (nunca exposto em log).
    """
    from app.crypto import decrypt_token
    token = decrypt_token(bm_account.system_user_token_encrypted)
    return MetaAdsClient(ad_account_id=bm_account.ad_account_id, access_token=token)
