"""
sentinelhub.py
==============
Autenticação e consulta à Statistical API do Sentinel Hub, no Copernicus
Data Space Ecosystem.

Conta gratuita: cadastro em dataspace.copernicus.eu, depois um cliente OAuth
em Settings → OAuth clients. As credenciais entram como variáveis de
ambiente SH_CLIENT_ID e SH_CLIENT_SECRET — nunca no código.

A camada gratuita tem cota mensal de unidades de processamento. Como este
sistema pede apenas estatísticas agregadas sobre polígonos pequenos, e não
imagens, o consumo por requisição é baixo: o custo cresce com o número de
setores × execuções, não com o tamanho da série.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import time
from typing import Dict, Iterable, List, Optional

import requests

log = logging.getLogger(__name__)

TOKEN_URL = ("https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
             "protocol/openid-connect/token")
STATS_URL = "https://sh.dataspace.copernicus.eu/api/v1/statistics"

MAX_RETRIES = 4
BACKOFF_BASE = 2.0
TIMEOUT = 180


class SentinelHubError(RuntimeError):
    pass


# ── autenticação ───────────────────────────────────────────────────────────

def get_token() -> str:
    cid = os.environ.get("SH_CLIENT_ID")
    secret = os.environ.get("SH_CLIENT_SECRET")
    if not cid or not secret:
        raise SentinelHubError(
            "Defina SH_CLIENT_ID e SH_CLIENT_SECRET. Em execução local use "
            "variáveis de ambiente; no GitHub Actions, secrets do repositório."
        )
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "client_credentials",
              "client_id": cid, "client_secret": secret},
        timeout=60,
    )
    if not resp.ok:
        raise SentinelHubError(
            f"Falha na autenticação ({resp.status_code}). "
            "Verifique se o cliente OAuth ainda existe e não expirou."
        )
    return resp.json()["access_token"]


# ── geometria ──────────────────────────────────────────────────────────────

def utm_epsg(lon: float, lat: float) -> int:
    """EPSG UTM/WGS84 adequado ao ponto. Processar em UTM mantém o pixel
    métrico e quadrado, condição para converter contagem em hectares."""
    zona = int((lon + 180) // 6) + 1
    return (32700 if lat < 0 else 32600) + zona


def centroide(geom: dict) -> tuple:
    """Centroide aproximado do primeiro anel — suficiente para escolher a
    zona UTM, sem exigir shapely como dependência."""
    anel = geom["coordinates"][0]
    xs = [p[0] for p in anel]
    ys = [p[1] for p in anel]
    return sum(xs) / len(xs), sum(ys) / len(ys)


def reprojetar_utm(geom: dict) -> tuple:
    """Converte um Polygon em WGS84 para a zona UTM correspondente.

    A API interpreta resx/resy na unidade do CRS declarado. Enviar a
    geometria em graus e pedir resolução 10 produziria pixels de 10 GRAUS —
    daí a reprojeção ser obrigatória, e não um refinamento.
    """
    from pyproj import Transformer

    lon, lat = centroide(geom)
    epsg = utm_epsg(lon, lat)
    tr = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)

    def anel(coords):
        return [list(tr.transform(x, y)) for x, y in coords]

    return (
        {"type": "Polygon", "coordinates": [anel(r) for r in geom["coordinates"]]},
        epsg,
    )


def area_pixel_ha(resolucao_m: int) -> float:
    """Hectares por pixel — converte contagem de pixels em área."""
    return (resolucao_m ** 2) / 10_000.0


# ── consulta ───────────────────────────────────────────────────────────────

def _post_com_retry(url: str, headers: dict, payload: dict) -> dict:
    ultimo = None
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=TIMEOUT)
        except requests.RequestException as exc:
            ultimo = str(exc)
        else:
            if r.ok:
                return r.json()
            # 429 e 5xx são transitórios; 4xx restantes não adianta repetir.
            if r.status_code != 429 and r.status_code < 500:
                raise SentinelHubError(f"HTTP {r.status_code}: {r.text[:300]}")
            ultimo = f"HTTP {r.status_code}"
        espera = BACKOFF_BASE ** tentativa
        log.warning("Tentativa %d/%d falhou (%s); aguardando %.0f s",
                    tentativa, MAX_RETRIES, ultimo, espera)
        time.sleep(espera)
    raise SentinelHubError(f"Esgotadas as tentativas: {ultimo}")


def consultar(token: str, geometria: dict, evalscript: str,
              inicio: dt.date, fim: dt.date, saidas: Iterable[str],
              colecao: str = "sentinel-2-l2a", resolucao: int = 10) -> List[dict]:
    """Uma requisição estatística para um polígono e um intervalo de datas.

    Retorna a lista bruta de intervalos devolvida pela API, um por data com
    observação disponível.
    """
    geom_utm, epsg = reprojetar_utm(geometria)

    calculos = {s: {"statistics": {"default": {}}} for s in saidas}

    payload = {
        "input": {
            "bounds": {
                "geometry": geom_utm,
                "properties": {
                    "crs": f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"
                },
            },
            "data": [{"type": colecao}],
        },
        "aggregation": {
            "timeRange": {
                "from": f"{inicio.isoformat()}T00:00:00Z",
                "to": f"{fim.isoformat()}T23:59:59Z",
            },
            "aggregationInterval": {"of": "P1D"},
            "resx": resolucao,
            "resy": resolucao,
            "evalscript": evalscript,
        },
        "calculations": calculos,
    }
    headers = {"Authorization": f"Bearer {token}",
               "Content-Type": "application/json"}

    dados = _post_com_retry(STATS_URL, headers, payload)
    return dados.get("data", [])


def extrair(intervalo: dict, saida: str) -> Optional[dict]:
    """Estatísticas de uma saída do evalscript, ou None se ausente."""
    return (intervalo.get("outputs", {})
                     .get(saida, {})
                     .get("bands", {})
                     .get("B0", {})
                     .get("stats"))
