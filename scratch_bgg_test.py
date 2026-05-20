import requests
import xml.etree.ElementTree as ET

BGG_SEARCH_URL = "https://boardgamegeek.com/xmlapi2/search"
BGG_THING_URL = "https://boardgamegeek.com/xmlapi2/thing"
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def test_bgg(game_name):
    print(f"Buscando jogo: '{game_name}'")
    params = {'query': game_name, 'type': 'boardgame'}
    r = requests.get(BGG_SEARCH_URL, params=params, headers=HEADERS, timeout=10)
    print(f"Status da busca: {r.status_code}")
    if r.status_code == 200:
        root = ET.fromstring(r.content)
        items = root.findall('item')
        print(f"Encontrados {len(items)} itens.")
        if items:
            bgg_id = items[0].get('id')
            primary_name = items[0].find('name').get('value') if items[0].find('name') is not None else "N/A"
            print(f"Primeiro item ID: {bgg_id}, Nome no BGG: {primary_name}")
            
            # Detalhes
            print(f"Buscando detalhes do ID: {bgg_id}")
            r_details = requests.get(BGG_THING_URL, params={'id': bgg_id}, headers=HEADERS, timeout=10)
            print(f"Status dos detalhes: {r_details.status_code}")
            if r_details.status_code == 200:
                root_d = ET.fromstring(r_details.content)
                item = root_d.find('item')
                if item is not None:
                    min_players_tag = item.find('minplayers')
                    max_players_tag = item.find('maxplayers')
                    min_players = min_players_tag.get('value') if min_players_tag is not None else None
                    max_players = max_players_tag.get('value') if max_players_tag is not None else None
                    print(f"minplayers value: {min_players}, maxplayers value: {max_players}")
                    
                    image_tag = item.find('image')
                    image_url = image_tag.text if image_tag is not None else None
                    print(f"image text: {image_url}")

test_bgg("Everdell")
test_bgg("Wingspan")
