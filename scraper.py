import requests
from bs4 import BeautifulSoup
import re
import warnings
import os
import json
import time
from datetime import datetime, timedelta
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}


def load_settings() -> dict:
    """Carrega as configurações do config.json (fallback para valores padrão)."""
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                return json.load(f).get('settings', {})
    except Exception:
        pass
    return {}


def clean_price(price_str: str) -> float:
    """Converte uma string de preço (ex: 'R$ 128,80') para float."""
    if not price_str:
        return 0.0
    cleaned = price_str.replace('R$', '').replace('.', '').replace(',', '.').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


# ─────────────────────────────────────────────
# INSTAGRAM — via instagrapi (login com credenciais do ambiente)
# ─────────────────────────────────────────────

def _get_instagrapi_client():
    """
    Cria e autentica um cliente instagrapi usando as credenciais
    configuradas nas variáveis de ambiente / GitHub Secrets.
    Retorna o cliente autenticado ou None em caso de falha.
    """
    username = os.environ.get("INSTAGRAM_USERNAME", "").strip()
    password = os.environ.get("INSTAGRAM_PASSWORD", "").strip()

    if not username or not password:
        print("AVISO: INSTAGRAM_USERNAME ou INSTAGRAM_PASSWORD não configurados.")
        print("Adicione-os como Secrets no GitHub (Settings → Secrets → Actions).")
        return None

    try:
        from instagrapi import Client
        cl = Client()
        # Define um delay aleatório entre requisições para simular comportamento humano
        cl.delay_range = [1, 3]
        print(f"Autenticando no Instagram como @{username}...")
        cl.login(username, password)
        print("✅ Login no Instagram realizado com sucesso.")
        return cl
    except Exception as e:
        print(f"❌ Erro ao autenticar no Instagram: {e}")
        return None


def scrape_instagram_posts(handle: str, publisher_name: str,
                           hours_window: int = 36, cl=None) -> list:
    """
    Coleta posts recentes do Instagram de uma editora usando instagrapi.

    - Recebe um cliente instagrapi já autenticado (cl) para reutilizar sessão.
    - Filtra posts dentro da janela de horas configurada.
    - Retorna no máximo 5 posts com título, link, conteúdo e imagem.
    """
    if not handle or cl is None:
        return []

    print(f"Coletando Instagram de {publisher_name} (@{handle})...")
    time_threshold = datetime.utcnow() - timedelta(hours=hours_window)
    posts = []

    try:
        user_id = cl.user_id_from_username(handle)
        medias = cl.user_medias(user_id, amount=12)  # Pega os 12 mais recentes para filtrar

        for media in medias:
            # Filtra pela janela de tempo (media.taken_at é timezone-aware)
            taken_at = media.taken_at.replace(tzinfo=None)
            if taken_at < time_threshold:
                break  # medias vêm em ordem cronológica decrescente

            caption = media.caption_text or ""
            if not caption:
                continue

            link = f"https://www.instagram.com/p/{media.code}/"
            display_title = caption[:70].strip() + ("..." if len(caption) > 70 else "")

            # Tenta obter URL da imagem (thumbnail ou primeira imagem do carrossel)
            image_url = ""
            if media.thumbnail_url:
                image_url = str(media.thumbnail_url)
            elif media.resources:
                image_url = str(media.resources[0].thumbnail_url or "")

            posts.append({
                'publisher': publisher_name,
                'title': f"Instagram: {display_title}",
                'link': link,
                'content': caption,
                'image': image_url,
                'source_type': 'instagram',
            })

            if len(posts) >= 5:
                break

        print(f"   -> {len(posts)} post(s) recentes nas últimas {hours_window}h para @{handle}")

    except Exception as e:
        print(f"   -> Erro ao coletar @{handle}: {e}")

    return posts


# ─────────────────────────────────────────────
# EDITORAS — somente Instagram
# ─────────────────────────────────────────────

def scrape_publishers_news(publishers: list) -> list:
    """
    Coleta notícias das editoras EXCLUSIVAMENTE via Instagram (instagrapi).
    Uma única sessão autenticada é compartilhada entre todas as editoras
    para evitar múltiplos logins e reduzir risco de bloqueio.
    """
    settings = load_settings()
    hours_window = settings.get('instagram_post_hours_window', 36)
    news_items = []

    # Login único compartilhado por todas as editoras
    cl = _get_instagrapi_client()
    if cl is None:
        print("Instagram indisponível: sem credenciais ou falha no login.")
        return []

    for pub in publishers:
        name = pub.get('name', '')
        instagram_handle = pub.get('instagram_handle', '')

        if not instagram_handle:
            print(f"[{name}] Sem instagram_handle configurado — ignorando.")
            continue

        ig_posts = scrape_instagram_posts(instagram_handle, name,
                                          hours_window=hours_window, cl=cl)
        news_items.extend(ig_posts)
        # Pausa entre perfis para não acionar rate limit
        time.sleep(2)

    return news_items


# ─────────────────────────────────────────────
# PLAYEASY — Pré-vendas
# ─────────────────────────────────────────────

def scrape_playeasy_pre_sales(max_pages: int = 2) -> list:
    """
    Raspa os produtos em pré-venda da PlayEasy.
    Retorna lista de dicts: name, link, price, image.
    """
    base_url = "https://www.playeasy.com.br/vitrine-nao-excluir/produtos-em-pre-venda.html"
    results = []

    for page in range(1, max_pages + 1):
        url = f"{base_url}?p={page}" if page > 1 else base_url
        print(f"Raspando pré-vendas: {url}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"Erro ao acessar {url}: Status {response.status_code}")
                break

            soup = BeautifulSoup(response.content, 'html.parser')
            products = soup.select('ul.products-grid li.item')

            if not products:
                print("Nenhum produto encontrado nesta página de pré-vendas.")
                break

            for product in products:
                name_tag = product.select_one('h2.product-name a')
                if not name_tag:
                    continue
                name = name_tag.get('title', name_tag.text).strip()
                link = name_tag.get('href', '').strip()

                img_tag = product.select_one('a.product-image img')
                img_url = img_tag.get('src', '') if img_tag else ''

                price = 0.0
                price_tag = product.select_one('.regular-price .price')
                if not price_tag:
                    price_tag = product.select_one('.price-box .price')
                if price_tag:
                    price = clean_price(price_tag.text)

                results.append({
                    'name': name,
                    'link': link,
                    'price': price,
                    'image': img_url,
                    'type': 'pre-sale',
                })

        except Exception as e:
            print(f"Erro ao raspar pré-vendas (página {page}): {e}")
            break

    return results


# ─────────────────────────────────────────────
# PLAYEASY — Promoções
# ─────────────────────────────────────────────

def scrape_playeasy_promotions(max_pages: int = 3) -> list:
    """
    Raspa os produtos em promoção da PlayEasy.
    Retorna lista de dicts: name, link, price_from, price_to, discount, image.
    Apenas itens COM desconto real (price_from > price_to) são retornados.
    """
    base_url = "https://www.playeasy.com.br/promocoes.html"
    results = []

    for page in range(1, max_pages + 1):
        url = f"{base_url}?p={page}" if page > 1 else base_url
        print(f"Raspando promoções: {url}")

        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"Erro ao acessar {url}: Status {response.status_code}")
                break

            soup = BeautifulSoup(response.content, 'html.parser')
            products = soup.select('ul.products-grid li.item')

            if not products:
                print("Nenhum produto encontrado nesta página de promoções.")
                break

            for product in products:
                name_tag = product.select_one('h2.product-name a')
                if not name_tag:
                    continue
                name = name_tag.get('title', name_tag.text).strip()
                link = name_tag.get('href', '').strip()

                img_tag = product.select_one('a.product-image img')
                img_url = img_tag.get('src', '') if img_tag else ''

                price_from = 0.0
                price_to = 0.0

                old_price_tag = product.select_one('.old-price .price')
                special_price_tag = product.select_one('.special-price .price')

                if old_price_tag and special_price_tag:
                    price_from = clean_price(old_price_tag.text)
                    price_to = clean_price(special_price_tag.text)
                else:
                    price_tag = (product.select_one('.regular-price .price')
                                 or product.select_one('.price-box .price'))
                    if price_tag:
                        price_to = clean_price(price_tag.text)
                        price_from = price_to

                # Só inclui se tiver desconto real
                if price_from <= 0 or price_to <= 0 or price_from <= price_to:
                    continue

                discount = int(round((1 - price_to / price_from) * 100))

                results.append({
                    'name': name,
                    'link': link,
                    'price_from': price_from,
                    'price_to': price_to,
                    'discount': discount,
                    'image': img_url,
                    'type': 'promotion',
                })

        except Exception as e:
            print(f"Erro ao raspar promoções (página {page}): {e}")
            break

    return results
