import requests
import xml.etree.ElementTree as ET
import time
import urllib.parse
import re

BGG_SEARCH_URL = "https://boardgamegeek.com/xmlapi2/search"
BGG_THING_URL = "https://boardgamegeek.com/xmlapi2/thing"

import os
import json

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def get_bgg_headers() -> dict:
    """Retorna os cabeçalhos HTTP apropriados para a API do BGG, incluindo o token se configurado."""
    headers = HEADERS.copy()
    token = os.environ.get("BGG_API_TOKEN", "")
    
    if not token:
        # Tenta carregar do config.json como fallback local
        try:
            if os.path.exists('config.json'):
                with open('config.json', 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    token = config.get('settings', {}).get('bgg_api_token') or config.get('bgg_api_token')
        except Exception:
            pass
            
    if token:
        headers['Authorization'] = f"Bearer {token.strip()}"
    else:
        print("AVISO: BGG_API_TOKEN não configurada no ambiente. As consultas ao BGG retornarão 401 (Não autorizado) de acordo com a política de julho de 2025 da plataforma.")
        print("DICA: Adicione a BGG_API_TOKEN como um Secret nas configurações do repositório no GitHub (crie o token em https://boardgamegeek.com/applications).")
        
    return headers

def clean_game_name(name: str) -> str:
    """Limpa o nome do jogo para melhorar a busca na API do BGG."""
    # Remove textos entre parênteses, colchetes ou termos como "Jogo de Tabuleiro", "Expansão", "Pré-venda"
    cleaned = re.sub(r'\(.*?\)|\[.*?\]', '', name)
    cleaned = re.sub(r'(?i)\b(pré-venda|pre-venda|jogo de tabuleiro|expansão|expansion|board\s*game|card\s*game)\b', '', cleaned)
    # Remove caracteres especiais mantendo letras, números e espaços básicos
    cleaned = re.sub(r'[^\w\s\-:]', '', cleaned)
    # Remove espaços duplos
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()
    return cleaned

def search_bgg_game_id(game_name: str) -> str:
    """Busca o jogo no BGG e retorna o ID do primeiro resultado (mais relevante)."""
    cleaned_name = clean_game_name(game_name)
    if not cleaned_name:
        return None
        
    params = {
        'query': cleaned_name,
        'type': 'boardgame'
    }
    
    try:
        # 1. Tenta a busca direta com o nome em português limpo
        response = requests.get(BGG_SEARCH_URL, params=params, headers=get_bgg_headers(), timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            items = root.findall('item')
            if items:
                bgg_id = items[0].get('id')
                print(f"   -> [BGG] Encontrado ID {bgg_id} na busca direta por '{cleaned_name}'")
                return bgg_id
        else:
            print(f"BGG Search retornou status {response.status_code} para '{cleaned_name}'")
            
        # 2. Se falhar, tenta usar o Groq/IA para traduzir o nome do jogo para o nome original em inglês / BGG
        try:
            from generator import translate_game_name
            english_name = translate_game_name(game_name)
            cleaned_english = clean_game_name(english_name)
            
            if cleaned_english and cleaned_english.lower() != cleaned_name.lower():
                print(f"-> Nome traduzido via Groq para busca BGG: '{cleaned_english}' (Nome original: '{game_name}')")
                params['query'] = cleaned_english
                response = requests.get(BGG_SEARCH_URL, params=params, headers=get_bgg_headers(), timeout=10)
                if response.status_code == 200:
                    root = ET.fromstring(response.content)
                    items = root.findall('item')
                    if items:
                        bgg_id = items[0].get('id')
                        print(f"   -> [BGG] Encontrado ID {bgg_id} após tradução inteligente por '{cleaned_english}'")
                        return bgg_id
        except Exception as gem_err:
            print(f"Falha na tentativa de tradução via Groq para BGG: {gem_err}")
                 
        # 3. Se ainda não achou, tenta buscar apenas pela primeira palavra significativa (resiliência final)
        words = cleaned_name.split()
        if len(words) > 1:
            params['query'] = words[0]
            response = requests.get(BGG_SEARCH_URL, params=params, headers=get_bgg_headers(), timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                items = root.findall('item')
                if items:
                    bgg_id = items[0].get('id')
                    print(f"   -> [BGG] Encontrado ID {bgg_id} no fallback resiliência rápida por '{words[0]}'")
                    return bgg_id
            else:
                print(f"BGG Search (fallback) retornou status {response.status_code} para '{words[0]}'")
                     
    except Exception as e:
        print(f"Erro ao buscar ID do jogo '{game_name}' no BGG: {e}")
        
    print(f"   -> [BGG] Nenhum ID encontrado para o jogo '{game_name}'")
    return None


def fetch_bgg_game_details(bgg_id: str) -> dict:
    """Busca detalhes de um jogo por ID no BGG (imagem e quantidade de jogadores)."""
    if not bgg_id:
        return None
        
    params = {
        'id': bgg_id
    }
    
    try:
        response = requests.get(BGG_THING_URL, params=params, headers=get_bgg_headers(), timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            item = root.find('item')
            if item is not None:
                # Imagem
                image_tag = item.find('image')
                image_url = image_tag.text if image_tag is not None else None
                
                # Thumbnail
                thumb_tag = item.find('thumbnail')
                thumbnail_url = thumb_tag.text if thumb_tag is not None else None
                
                # Número de jogadores
                min_players_tag = item.find('minplayers')
                max_players_tag = item.find('maxplayers')
                
                min_players = min_players_tag.get('value') if min_players_tag is not None else None
                max_players = max_players_tag.get('value') if max_players_tag is not None else None
                
                players_str = None
                if min_players and max_players:
                    if min_players == max_players:
                        players_str = f"{min_players} jogador" if min_players == "1" else f"{min_players} jogadores"
                    else:
                        players_str = f"{min_players}-{max_players} jogadores"
                
                print(f"   -> [BGG] Detalhes ID {bgg_id}: Imagem: {'Sim' if image_url or thumbnail_url else 'Não'}, Jogadores: {players_str or 'Não disponível'}")
                return {
                    'image': image_url or thumbnail_url,
                    'players': players_str
                }
        else:
            print(f"BGG Thing retornou status {response.status_code} para ID {bgg_id}")
    except Exception as e:
        print(f"Erro ao obter detalhes do jogo ID {bgg_id} no BGG: {e}")
        
    return None

def enrich_game_data(game_name: str) -> dict:
    """
    Função principal de enriquecimento: busca no BGG e retorna
    as informações adicionais necessárias (imagem e jogadores).
    """
    print(f"Enriquecendo dados para o jogo: {game_name}")
    bgg_id = search_bgg_game_id(game_name)
    if bgg_id:
        # Pausa leve para respeitar a API do BGG
        time.sleep(0.5)
        details = fetch_bgg_game_details(bgg_id)
        if details:
            return details
            
    return {'image': None, 'players': None}
