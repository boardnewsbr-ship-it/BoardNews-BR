import requests
import xml.etree.ElementTree as ET
import time
import urllib.parse
import re

BGG_SEARCH_URL = "https://boardgamegeek.com/xmlapi2/search"
BGG_THING_URL = "https://boardgamegeek.com/xmlapi2/thing"

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
        response = requests.get(BGG_SEARCH_URL, params=params, timeout=10)
        if response.status_code == 200:
            root = ET.fromstring(response.content)
            items = root.findall('item')
            if items:
                # Retorna o ID do primeiro resultado
                return items[0].get('id')
                
        # Se não achou com o nome limpo, tenta buscar apenas pela primeira palavra significativa (resiliência)
        words = cleaned_name.split()
        if len(words) > 1:
            params['query'] = words[0]
            response = requests.get(BGG_SEARCH_URL, params=params, timeout=10)
            if response.status_code == 200:
                root = ET.fromstring(response.content)
                items = root.findall('item')
                if items:
                    return items[0].get('id')
                    
    except Exception as e:
        print(f"Erro ao buscar ID do jogo '{game_name}' no BGG: {e}")
        
    return None

def fetch_bgg_game_details(bgg_id: str) -> dict:
    """Busca detalhes de um jogo por ID no BGG (imagem e quantidade de jogadores)."""
    if not bgg_id:
        return None
        
    params = {
        'id': bgg_id
    }
    
    try:
        response = requests.get(BGG_THING_URL, params=params, timeout=10)
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
                        
                return {
                    'image': image_url or thumbnail_url,
                    'players': players_str
                }
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
