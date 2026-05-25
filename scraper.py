import requests
from bs4 import BeautifulSoup
import re
import warnings
import os
import json
from datetime import datetime, timedelta
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# Instâncias públicas do RSSHub em ordem de prioridade.
# O RSSHub converte feeds do Instagram em RSS sem necessidade de login,
# contornando os bloqueios do Instaloader em ambientes de servidor/CI.
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://hub.slarker.me",
]


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
# INSTAGRAM — via RSSHub (sem login, sem Instaloader)
# ─────────────────────────────────────────────

def _fetch_instagram_rss(handle: str, rsshub_base: str, timeout: int = 15) -> list:
    """
    Busca os posts recentes de um perfil do Instagram via RSSHub.
    Retorna lista de blocos <item> brutos do RSS ou [] em caso de falha.
    """
    url = f"{rsshub_base.rstrip('/')}/instagram/user/{handle}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code != 200:
            return []
        return re.findall(r'<item\b[^>]*>.*?</item>', resp.text, re.DOTALL | re.IGNORECASE)
    except Exception:
        return []


def _parse_instagram_rss_item(item_raw: str, publisher_name: str, time_threshold: datetime) -> dict | None:
    """
    Faz parse de um bloco <item> do RSS do Instagram retornado pelo RSSHub.
    Retorna None se o post for mais antigo que o threshold ou não tiver conteúdo.
    """
    soup = BeautifulSoup(item_raw, 'html.parser')

    # Título / caption (primeira linha do post)
    title_tag = soup.find('title')
    title_text = title_tag.text.strip() if title_tag else ""
    title_text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', title_text).strip()

    if not title_text or title_text.lower() == 'instagram':
        return None

    # Link do post
    link_tag = soup.find('link')
    link_text = ""
    if link_tag:
        link_text = link_tag.text.strip() or link_tag.get('href', '').strip()
    link_text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', link_text).strip()

    # Data de publicação — filtra pela janela de tempo
    pub_date_tag = soup.find('pubdate')
    if pub_date_tag:
        try:
            from email.utils import parsedate_to_datetime
            pub_dt = parsedate_to_datetime(pub_date_tag.text.strip()).replace(tzinfo=None)
            if pub_dt < time_threshold:
                return None
        except Exception:
            pass  # Se não parsear a data, inclui o post por segurança

    # Descrição / caption completo
    desc_tag = soup.find('description') or soup.find('content:encoded')
    desc_text = desc_tag.text.strip() if desc_tag else title_text
    desc_text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', desc_text).strip()
    desc_clean = BeautifulSoup(desc_text, 'html.parser').get_text()
    desc_clean = re.sub(r'\s+', ' ', desc_clean).strip()

    # Imagem do post
    image_url = ""
    enclosure = soup.find('enclosure')
    if enclosure:
        image_url = enclosure.get('url', '')
    if not image_url:
        media = soup.find('media:content') or soup.find(re.compile(r'media:content', re.I))
        if media:
            image_url = media.get('url', '')

    display_title = desc_clean[:70].strip() + ("..." if len(desc_clean) > 70 else "")

    return {
        'publisher': publisher_name,
        'title': f"Instagram: {display_title}",
        'link': link_text,
        'content': desc_clean,
        'image': image_url,
        'source_type': 'instagram_rss',
    }


def scrape_instagram_posts(handle: str, publisher_name: str, hours_window: int = 36) -> list:
    """
    Coleta posts recentes do Instagram de uma editora usando RSSHub como proxy RSS.

    - Testa instâncias RSSHub em cascata até obter resposta.
    - Filtra posts dentro da janela de tempo configurada.
    - Retorna no máximo 5 posts, sem login, sem risco de ban.
    """
    if not handle:
        return []

    settings = load_settings()
    timeout = settings.get('request_timeout_seconds', 15)
    custom_instance = settings.get('instagram_rsshub_instance', '')

    instances = []
    if custom_instance:
        instances.append(custom_instance)
    for inst in RSSHUB_INSTANCES:
        if inst not in instances:
            instances.append(inst)

    print(f"Coletando Instagram de {publisher_name} (@{handle}) via RSSHub...")

    time_threshold = datetime.utcnow() - timedelta(hours=hours_window)
    items_raw = []

    for instance in instances:
        items_raw = _fetch_instagram_rss(handle, instance, timeout=timeout)
        if items_raw:
            print(f"   -> {len(items_raw)} itens obtidos via {instance}")
            break
        else:
            print(f"   -> Falha em {instance}, tentando próxima instância...")

    if not items_raw:
        print(f"   -> Nenhuma instância RSSHub respondeu para @{handle}.")
        return []

    posts = []
    for item_raw in items_raw:
        parsed = _parse_instagram_rss_item(item_raw, publisher_name, time_threshold)
        if parsed:
            posts.append(parsed)
        if len(posts) >= 5:
            break

    print(f"   -> {len(posts)} post(s) recentes nas últimas {hours_window}h para @{handle}")
    return posts


# ─────────────────────────────────────────────
# EDITORAS — somente Instagram
# ─────────────────────────────────────────────

def scrape_publishers_news(publishers: list) -> list:
    """
    Coleta notícias das editoras EXCLUSIVAMENTE via Instagram (RSSHub).
    RSS de blog e raspagem HTML foram removidos — o Instagram é a fonte
    principal de anúncios das editoras brasileiras de jogos de tabuleiro.
    """
    settings = load_settings()
    hours_window = settings.get('instagram_post_hours_window', 36)
    news_items = []

    for pub in publishers:
        name = pub.get('name', '')
        instagram_handle = pub.get('instagram_handle', '')

        if not instagram_handle:
            print(f"[{name}] Sem instagram_handle configurado — ignorando.")
            continue

        ig_posts = scrape_instagram_posts(instagram_handle, name, hours_window=hours_window)
        news_items.extend(ig_posts)

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
    Apenas itens COM desconto real (price_from > price_to) são retornados,
    evitando que produtos sem desconto apareçam na seção de promoções.
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
