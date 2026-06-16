import requests
import xml.etree.ElementTree as ET
import time
import re
import os
import json

BGG_SEARCH_URL = "https://boardgamegeek.com/xmlapi2/search"
BGG_THING_URL  = "https://boardgamegeek.com/xmlapi2/thing"

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

_BGG_TOKEN_CHECKED = False
_BGG_TOKEN_VALUE   = None   # None = sem token = BGG desabilitado


def _check_bgg_token() -> str | None:
    """
    Retorna o token BGG configurado, ou None se não houver.
    Quando retorna None, todas as chamadas ao BGG são ignoradas silenciosamente.
    Imprime aviso apenas na primeira verificação.
    """
    global _BGG_TOKEN_CHECKED, _BGG_TOKEN_VALUE

    if _BGG_TOKEN_CHECKED:
        return _BGG_TOKEN_VALUE

    _BGG_TOKEN_CHECKED = True
    token = os.environ.get("BGG_API_TOKEN", "").strip()

    if not token:
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    token = (cfg.get('settings', {}).get('bgg_api_token') or
                             cfg.get('bgg_api_token', ''))
        except Exception:
            pass

    if token:
        _BGG_TOKEN_VALUE = token
        print(f"BGG: token configurado, enriquecimento ativo.")
    else:
        _BGG_TOKEN_VALUE = None
        print("BGG: BGG_API_TOKEN não configurada — enriquecimento desabilitado.")

    return _BGG_TOKEN_VALUE


def get_bgg_headers() -> dict:
    headers = HEADERS.copy()
    token = _check_bgg_token()
    if token:
        headers['Authorization'] = f"Bearer {token}"
    return headers


def clean_game_name(name: str) -> str:
    cleaned = re.sub(r'\(.*?\)|\[.*?\]', '', name)
    cleaned = re.sub(
        r'(?i)\b(pré-venda|pre-venda|jogo de tabuleiro|expansão|expansion|'
        r'board\s*game|card\s*game)\b', '', cleaned)
    cleaned = re.sub(r'[^\w\s\-:]', '', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()


def search_bgg_game_id(game_name: str) -> str | None:
    if not _check_bgg_token():
        return None

    cleaned = clean_game_name(game_name)
    if not cleaned:
        return None

    params = {'query': cleaned, 'type': 'boardgame'}

    try:
        r = requests.get(BGG_SEARCH_URL, params=params,
                         headers=get_bgg_headers(), timeout=10)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            items = root.findall('item')
            if items:
                bgg_id = items[0].get('id')
                print(f"   -> [BGG] ID {bgg_id} para '{cleaned}'")
                return bgg_id
        elif r.status_code == 401:
            return None
        else:
            print(f"BGG Search status {r.status_code} para '{cleaned}'")

        # Fallback via tradução Groq
        try:
            from generator import translate_game_name
            english = translate_game_name(game_name)
            cleaned_en = clean_game_name(english)
            if cleaned_en and cleaned_en.lower() != cleaned.lower():
                params['query'] = cleaned_en
                r2 = requests.get(BGG_SEARCH_URL, params=params,
                                  headers=get_bgg_headers(), timeout=10)
                if r2.status_code == 200:
                    root = ET.fromstring(r2.content)
                    items = root.findall('item')
                    if items:
                        return items[0].get('id')
        except Exception:
            pass

    except Exception as e:
        print(f"Erro BGG para '{game_name}': {e}")

    return None


def fetch_bgg_game_details(bgg_id: str) -> dict | None:
    if not bgg_id or not _check_bgg_token():
        return None

    try:
        r = requests.get(BGG_THING_URL, params={'id': bgg_id},
                         headers=get_bgg_headers(), timeout=10)
        if r.status_code == 200:
            root = ET.fromstring(r.content)
            item = root.find('item')
            if item is not None:
                image_tag = item.find('image')
                thumb_tag = item.find('thumbnail')
                image_url = (image_tag.text if image_tag is not None
                             else (thumb_tag.text if thumb_tag is not None else None))
                min_p = item.find('minplayers')
                max_p = item.find('maxplayers')
                mn = min_p.get('value') if min_p is not None else None
                mx = max_p.get('value') if max_p is not None else None
                players = None
                if mn and mx:
                    players = (f"{mn} jogador" if mn == mx == '1'
                               else f"{mn} jogadores" if mn == mx
                               else f"{mn}-{mx} jogadores")
                return {'image': image_url, 'players': players}
        elif r.status_code == 401:
            return None
    except Exception as e:
        print(f"Erro BGG details ID {bgg_id}: {e}")
    return None


def enrich_game_data(game_name: str) -> dict:
    """Enriquece dados do jogo via BGG. Retorna vazio se BGG indisponível."""
    if not _check_bgg_token():
        return {'image': None, 'players': None}

    print(f"Enriquecendo: {game_name}")
    bgg_id = search_bgg_game_id(game_name)
    if bgg_id:
        time.sleep(0.5)
        details = fetch_bgg_game_details(bgg_id)
        if details:
            return details
    return {'image': None, 'players': None}
