import requests
from bs4 import BeautifulSoup
import urllib.parse
import time

import re
import warnings
from datetime import datetime, timedelta
from bs4 import XMLParsedAsHTMLWarning

# Ignora o aviso do BeautifulSoup ao fazer parse de feeds RSS (XML) usando html.parser
warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def clean_price(price_str: str) -> float:
    """Converte uma string de preço (ex: 'R$ 128,80') para float."""
    if not price_str:
        return 0.0
    # Remove R$, espaços, pontos de milhar e substitui vírgula por ponto
    cleaned = price_str.replace('R$', '').replace('.', '').replace(',', '.').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0

def scrape_playeasy_pre_sales(max_pages=2) -> list:
    """
    Raspa os produtos em pré-venda da PlayEasy.
    Retorna uma lista de dicionários contendo: nome, link, preco, imagem.
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
                if price_tag:
                    price = clean_price(price_tag.text)
                else:
                    price_tag = product.select_one('.price-box .price')
                    if price_tag:
                        price = clean_price(price_tag.text)

                results.append({
                    'name': name,
                    'link': link,
                    'price': price,
                    'image': img_url,
                    'type': 'pre-sale'
                })

            time.sleep(1)

        except Exception as e:
            print(f"Erro ao raspar página {page} de pré-vendas: {e}")
            break

    return results

def scrape_playeasy_promotions(max_pages=3) -> list:
    """
    Raspa os produtos em promoção da PlayEasy.
    Retorna uma lista de dicionários contendo: nome, link, preco_de, preco_por, desconto, imagem.
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
                    price_tag = product.select_one('.regular-price .price') or product.select_one('.price-box .price')
                    if price_tag:
                        price_to = clean_price(price_tag.text)
                        price_from = price_to

                discount = 0
                if price_from > 0 and price_to > 0 and price_from > price_to:
                    discount = int(round((1 - price_to / price_from) * 100))

                results.append({
                    'name': name,
                    'link': link,
                    'price_from': price_from,
                    'price_to': price_to,
                    'discount': discount,
                    'image': img_url,
                    'type': 'promotion'
                })

            time.sleep(1)

        except Exception as e:
            print(f"Erro ao raspar página {page} de promoções: {e}")
            break

    return results

def scrape_instagram_posts(handle: str, publisher_name: str) -> list:
    """Scrapes recent Instagram posts from Picuki and returns news items from yesterday.

    The function fetches the public Picuki profile page, parses elements with the
    `.box-photo` class, extracts the post date (if available), and only keeps
    posts whose date matches yesterday's date. It returns a list of dictionaries
    compatible with the rest of the pipeline.
    """
    if not handle:
        return []

    url = f"https://www.picuki.com/profile/{handle}"
    instagram_news = []
    yesterday = (datetime.now() - timedelta(days=1)).date()

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            return []
        soup = BeautifulSoup(response.content, "html.parser")
        posts = soup.select('.box-photo')
        for post in posts:
            date_str = None
            time_tag = post.select_one('time')
            if time_tag and time_tag.has_attr('datetime'):
                date_str = time_tag['datetime'][:10]
            if not date_str:
                continue
            try:
                post_date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                continue
            if post_date != yesterday:
                continue

            caption_elem = post.select_one('.photo-description')
            caption = caption_elem.get_text(strip=True) if caption_elem else ""

            img_elem = post.select_one('img')
            img_url = img_elem['src'] if img_elem and img_elem.has_attr('src') else ""

            link_elem = post.select_one('a')
            link = link_elem['href'] if link_elem and link_elem.has_attr('href') else f"https://www.instagram.com/{handle}/"

            instagram_news.append({
                'publisher': publisher_name,
                'title': f"Instagram: {caption[:50]}...",
                'link': link,
                'content': caption,
                'image': img_url,
                'source_type': 'instagram'
            })
        return instagram_news
    except Exception as e:
        print(f"Erro ao raspar Instagram de {publisher_name} via Picuki: {e}")
        # Fallback Pixwox
        try:
            fallback_url = f"https://pixwox.com/@{handle}"
            resp = requests.get(fallback_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                soup_fb = BeautifulSoup(resp.content, "html.parser")
                posts_fb = soup_fb.select('.post')
                for post_fb in posts_fb:
                    date_str_fb = post_fb.get('data-date')
                    if not date_str_fb:
                        continue
                    try:
                        post_date_fb = datetime.strptime(date_str_fb[:10], "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    if post_date_fb != yesterday:
                        continue
                    caption_fb = post_fb.select_one('.caption')
                    caption_text = caption_fb.get_text(strip=True) if caption_fb else ""
                    img_fb = post_fb.select_one('img')
                    img_url_fb = img_fb['src'] if img_fb and img_fb.has_attr('src') else ""
                    link_fb = post_fb.select_one('a')
                    link_href = link_fb['href'] if link_fb and link_fb.has_attr('href') else f"https://www.instagram.com/{handle}/"
                    instagram_news.append({
                        'publisher': publisher_name,
                        'title': f"Instagram: {caption_text[:50]}...",
                        'link': link_href,
                        'content': caption_text,
                        'image': img_url_fb,
                        'source_type': 'instagram'
                    })
                if instagram_news:
                    return instagram_news
        except Exception as fe_pixwox:
            print(f"Fallback Pixwox falhou: {fe_pixwox}")
        # Fallback Imginn
        try:
            imginn_url = f"https://imginn.com/{handle}"
            resp_imginn = requests.get(imginn_url, headers=HEADERS, timeout=15)
            if resp_imginn.status_code == 200:
                soup_imginn = BeautifulSoup(resp_imginn.content, "html.parser")
                for post_img in soup_imginn.select('.post, .media'):
                    ts = post_img.get('data-time')
                    if ts:
                        try:
                            post_date = datetime.fromtimestamp(int(ts)).date()
                        except Exception:
                            continue
                        if post_date != yesterday:
                            continue
                    else:
                        continue
                    caption_el = post_img.select_one('.caption, .description')
                    caption_text = caption_el.get_text(strip=True) if caption_el else ""
                    img_el = post_img.select_one('img')
                    img_url = img_el['src'] if img_el and img_el.has_attr('src') else ""
                    link_el = post_img.select_one('a')
                    link = link_el['href'] if link_el and link_el.has_attr('href') else f"https://www.instagram.com/{handle}/"
                    instagram_news.append({
                        'publisher': publisher_name,
                        'title': f"Instagram: {caption_text[:50]}...",
                        'link': link,
                        'content': caption_text,
                        'image': img_url,
                        'source_type': 'instagram'
                    })
                if instagram_news:
                    return instagram_news
        except Exception as fe_imginn:
            print(f"Fallback Imginn também falhou: {fe_imginn}")
        return []

def scrape_publishers_news(publishers: list) -> list:
    """Coleta notícias dos blogs/sites, feeds ou redes sociais das editoras configuradas.
    Retorna uma lista de candidatos de notícias para filtragem por IA.
    """
    news_items = []
    for pub in publishers:
        name = pub.get('name')
        feed_url = pub.get('feed_url')
        url = pub.get('url')
        instagram_handle = pub.get('instagram_handle')
        has_blog_success = False

        # 1. RSS Feed
        if feed_url:
            try:
                response = requests.get(feed_url, headers=HEADERS, timeout=15)
                if response.status_code == 200:
                    feed_text = response.text
                    items_raw = re.findall(r'<item>.*?</item>', feed_text, re.DOTALL)
                    if items_raw:
                        print(f"Coletando notícias RSS de: {name} (Encontrados {len(items_raw)} posts)")
                        for item_raw in items_raw[:5]:
                            link_match = re.search(r'<link[^>]*>(.*?)</link>', item_raw, re.DOTALL)
                            link_text = ""
                            if link_match:
                                link_text = link_match.group(1).strip()
                                link_text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', link_text).strip()
                            item_soup = BeautifulSoup(item_raw, 'html.parser')
                            title = item_soup.find('title')
                            desc = item_soup.find('description') or item_soup.find('content:encoded')
                            title_text = title.text.strip() if title else ""
                            desc_text = desc.text.strip() if desc else ""
                            if not link_text:
                                guid_tag = item_soup.find('guid')
                                link_text = guid_tag.text.strip() if guid_tag else ""
                            desc_clean = BeautifulSoup(desc_text, 'html.parser').get_text()
                            desc_clean = re.sub(r'\s+', ' ', desc_clean).strip()[:1000]
                            news_items.append({
                                'publisher': name,
                                'title': title_text,
                                'link': link_text,
                                'content': desc_clean,
                                'source_type': 'rss'
                            })
                        has_blog_success = True
            except Exception as e:
                print(f"Erro ao ler feed RSS para {name}: {e}. Tentando raspagem direta da página...")

        # 2. HTML fallback
        if not has_blog_success and url:
            try:
                response = requests.get(url, headers=HEADERS, timeout=15)
                if response.status_code == 200:
                    print(f"Coletando notícias HTML de: {name}")
                    soup = BeautifulSoup(response.content, 'html.parser')
                    articles = []
                    for article in soup.select('article, .post, .item-post, .news-item')[:5]:
                        title_tag = article.select_one('h1 a, h2 a, h3 a, .entry-title a, .post-title a')
                        if title_tag:
                            title_text = title_tag.text.strip()
                            link_text = title_tag.get('href', '')
                            if link_text and not link_text.startswith('http'):
                                link_text = urllib.parse.urljoin(url, link_text)
                            desc_tag = article.select_one('.entry-content, .entry-summary, .post-content, p')
                            desc_clean = desc_tag.text.strip() if desc_tag else ""
                            desc_clean = re.sub(r'\s+', ' ', desc_clean).strip()[:1000]
                            articles.append({
                                'publisher': name,
                                'title': title_text,
                                'link': link_text,
                                'content': desc_clean,
                                'source_type': 'html'
                            })
                    if not articles:
                        for a_tag in soup.select('a')[:100]:
                            href = a_tag.get('href', '')
                            text = a_tag.text.strip()
                            if len(text) > 20 and href and ('blog' in href or 'noticias' in href or 'artigo' in href or 'posts' in href or re.search(r'/\d{4}/\d{2}/', href)):
                                if not href.startswith('http'):
                                    href = urllib.parse.urljoin(url, href)
                                articles.append({
                                    'publisher': name,
                                    'title': text,
                                    'link': href,
                                    'content': "",
                                    'source_type': 'html-links'
                                })
                    news_items.extend(articles)
            except Exception as e:
                print(f"Erro ao raspar HTML de {name}: {e}")

        # 3. Instagram recent posts
        if instagram_handle:
            ig_posts = scrape_instagram_posts(instagram_handle, name)
            news_items.extend(ig_posts)

    return news_items
