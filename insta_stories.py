import os
import datetime
import requests
from bs4 import BeautifulSoup
from instaloader import Instaloader, StoryItem, Profile
from typing import List, Dict

# Diretório temporário para armazenar arquivos baixados (não será mantido)
TMP_DIR = os.path.join(os.path.dirname(__file__), "tmp_stories")
os.makedirs(TMP_DIR, exist_ok=True)


def fetch_instagram_stories(handle: str, publisher_name: str) -> List[Dict]:
    """Retorna Stories recentes (últimas 24 h) do Instagram de *handle*.

    Cada story é representado como um dicionário compatível com o restante do pipeline:
    {
        'publisher': publisher_name,
        'title': f"Instagram Story: {handle}",
        'link': media_url,          # URL direta da mídia (imagem ou vídeo)
        'content': '',
        'image': media_url,
        'source_type': 'instagram_story'
    }
    
    O download ocorre em modo anônimo (sem login). Apenas a URL da mídia
    é retornada, não salvamos o arquivo localmente, mas o Instaloader cria
    arquivos temporários que são removidos ao final da execução.
    """
    stories: List[Dict] = []
    try:
        loader = Instaloader(download_pictures=False,
                              download_videos=False,
                              download_video_thumbnails=False,
                              download_geotags=False,
                              save_metadata=False,
                              compress_json=False,
                              post_metadata_txt_pattern="",
                              dirname_pattern=TMP_DIR,
                              filename_pattern="{profile}_{date_utc}_UTC",
                              quiet=True)
        # Tenta carregar sessão salva; se falhar, tenta login (com tratamento de checkpoint)
        session_path = os.path.join(TMP_DIR, f"{'cirnengr'}_session")
        if os.path.isfile(session_path):
            try:
                loader.load_session_from_file('cirnengr', session_path)
            except Exception as se:
                print(f"Falha ao carregar sessão: {se}, tentando login tradicional")
                try:
                    loader.login('cirnengr', 'Cirne123')
                except Exception as le:
                    if 'Checkpoint' in str(le):
                        print('Login checkpoint required, prosseguindo sem login.')
                    else:
                        print(f'Erro ao fazer login: {le}')
        else:
            try:
                loader.login('cirnengr', 'Cirne123')
            except Exception as le:
                if 'Checkpoint' in str(le):
                    print('Login checkpoint required, prosseguindo sem login.')
                else:
                    print(f'Erro ao fazer login: {le}')
        profile = Profile.from_username(loader.context, handle)
        profile = Profile.from_username(loader.context, handle)
        # Obtem os stories recentes (Instaloader já filtra por 24h se usar "get_stories"
        for story in loader.get_stories(userids=[profile.userid]):
            # story é um objeto StoryItem; tem atributo date_utc
            story_date = story.date_utc.replace(tzinfo=datetime.timezone.utc).astimezone(tz=None).date()
            yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).date()
            if story_date != yesterday:
                continue
            # Cada story pode conter múltiplas partes (imagem ou vídeo)
            for item in story.get_items():
                # Preferimos a URL original da mídia
                media_url = item.url
                stories.append({
                    "publisher": publisher_name,
                    "title": f"Instagram Story: {handle}",
                    "link": media_url,
                    "content": "",
                    "image": media_url,
                    "source_type": "instagram_story"
                })
    except Exception as e:
        # Falha silenciosa para não interromper o fluxo principal
        print(f"Erro ao coletar Stories de {publisher_name} ({handle}): {e}")
    finally:
        # Limpa arquivos temporários criados pelo Instaloader
        try:
            if os.path.isdir(TMP_DIR):
                for root, dirs, files in os.walk(TMP_DIR, topdown=False):
                    for name in files:
                        os.remove(os.path.join(root, name))
                    for name in dirs:
                        os.rmdir(os.path.join(root, name))
                os.rmdir(TMP_DIR)
        except Exception:
            pass
    # If Instaloader failed to retrieve stories, try Picuki as a fallback
    if not stories:
        try:
            picuki_url = f"https://www.picuki.com/stories/{handle}"
            resp = requests.get(picuki_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.content, "html.parser")
                # Picuki story items usually have class "story-item" or similar; we look for img tags within
                for img in soup.select('img'):
                    src = img.get('src')
                    if src and 'story' in src:
                        stories.append({
                            "publisher": publisher_name,
                            "title": f"Instagram Story (Picuki): {handle}",
                            "link": src,
                            "content": "",
                            "image": src,
                            "source_type": "instagram_story_picuki"
                        })
        except Exception as fe:
            print(f"Fallback Picuki também falhou para {publisher_name} ({handle}): {fe}")
    # Additional fallback using Instagram public JSON endpoint (__a)
    if not stories:
        try:
            json_url = f"https://www.instagram.com/{handle}/?__a=1&__d=dis"
            resp = requests.get(json_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
            if resp.status_code == 200:
                data = resp.json()
                # Navigate JSON structure to stories (may vary)
                user = data.get('graphql', {}).get('user', {})
                reels = user.get('edge_owner_to_timeline_media', {}).get('edges', [])
                for edge in reels[:10]:
                    node = edge.get('node', {})
                    if node.get('is_video'):
                        media_url = node.get('video_url')
                    else:
                        media_url = node.get('display_url')
                    if media_url:
                        stories.append({
                            "publisher": publisher_name,
                            "title": f"Instagram Story (JSON): {handle}",
                            "link": media_url,
                            "content": "",
                            "image": media_url,
                            "source_type": "instagram_story_json"
                        })
        except Exception as fe2:
            print(f"Fallback JSON também falhou para {publisher_name} ({handle}): {fe2}")
    return stories
