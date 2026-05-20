import requests
from bs4 import BeautifulSoup
import urllib.parse
import time
import re
import warnings
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
                # Extração do nome e link do produto
                name_tag = product.select_one('h2.product-name a')
                if not name_tag:
                    continue
                name = name_tag.get('title', name_tag.text).strip()
                link = name_tag.get('href', '').strip()
                
                # Extração da imagem
                img_tag = product.select_one('a.product-image img')
                img_url = img_tag.get('src', '') if img_tag else ''
                
                # Extração do preço
                price = 0.0
                price_tag = product.select_one('.regular-price .price')
                if price_tag:
                    price = clean_price(price_tag.text)
                else:
                    # Tenta fallback para a vista ou qualquer tag de preço
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
                
            # Evita sobrecarregar o servidor
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
                
                # Preços De/Por
                price_from = 0.0
                price_to = 0.0
                
                old_price_tag = product.select_one('.old-price .price')
                special_price_tag = product.select_one('.special-price .price')
                
                if old_price_tag and special_price_tag:
                    price_from = clean_price(old_price_tag.text)
                    price_to = clean_price(special_price_tag.text)
                else:
                    # Caso haja apenas um preço mas esteja listado em promoção
                    price_tag = product.select_one('.regular-price .price') or product.select_one('.price-box .price')
                    if price_tag:
                        price_to = clean_price(price_tag.text)
                        price_from = price_to  # Sem desconto aparente
                
                # Calcula a porcentagem de desconto
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
                
            # Evita sobrecarregar o servidor
            time.sleep(1)
            
        except Exception as e:
            print(f"Erro ao raspar página {page} de promoções: {e}")
            break
            
    return results

def scrape_instagram_posts(handle: str, publisher_name: str) -> list:
    """Scrapes recent Instagram posts using Pixwox (primary) and Imginn (fallback).
    Returns a list of candidate news items.
    """
    if not handle:
        return []
    source_urls = [
        ("pixwox", f"https://www.pixwox.com/profile/{handle}/"),
        ("imginn", f"https://imginn.com/{handle}/")
    ]
    instagram_news = []
    for source_name, url in source_urls:
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            if response.status_code != 200:
                print(f"Cannot access {source_name} for {publisher_name} (@{handle}). Status: {response.status_code}")
                continue
            soup = BeautifulSoup(response.content, 'html.parser')
            # Detect active stories if possible (heuristic: presence of story indicator)
            has_active_stories = bool(soup.select('.stories, .story, .story-thumbnail'))
            # Find recent posts: look for image tags within anchor links
            posts = []
            for a in soup.select('a'):
                img = a.find('img')
                if img and img.get('src'):
                    posts.append((a, img))
                if len(posts) >= 6:
                    break
            print(f"Found {len(posts)} posts on {source_name} for @{handle}")
            for a, img in posts:
                img_url = img.get('src')
                link_url = a.get('href')
                if link_url and not link_url.startswith('http'):
                    link_url = urllib.parse.urljoin(url, link_url)
                # Caption: try alt attribute then surrounding text
                caption = img.get('alt', '').strip()
                if not caption:
                    # fallback: next sibling text
                    caption = a.text.strip()
                # Simple recent filter: assume posts are recent as they appear first
                title_text = caption[:70].strip() + ("..." if len(caption) > 70 else "")
                content_text = caption
                if has_active_stories:
                    content_text += " [Nota: Esta editora possui Stories ativos hoje no Instagram]"
                instagram_news.append({
                    'publisher': publisher_name,
                    'title': f"Instagram: {title_text}",
                    'link': link_url or f"https://www.instagram.com/{handle}/",
                    'content': content_text,
                    'image': img_url,
                    'source_type': 'instagram'
                })
            # If we got posts from primary source, break
            if instagram_news:
                break
        except Exception as e:
            print(f"Erro ao raspar {source_name} para {publisher_name} (@{handle}): {e}")
    return instagram_news


def scrape_publishers_news(publishers: list) -> list:
    """
    Coleta notícias dos blogs/sites, feeds ou redes sociais das editoras configuradas.
    Retorna uma lista de candidatos de notícias para filtragem por IA.
    """
    news_items = []
    
    for pub in publishers:
        name = pub.get('name')
        feed_url = pub.get('feed_url')
        url = pub.get('url')
        instagram_handle = pub.get('instagram_handle')
        
        has_blog_success = False
        
        # 1. Tenta RSS Feed se disponível (Altamente estável)
        if feed_url:
            try:
                response = requests.get(feed_url, headers=HEADERS, timeout=15)
                if response.status_code == 200:
                    # Extrai os blocos <item> usando regex do texto bruto para evitar que o html.parser descarte o link
                    feed_text = response.text
                    items_raw = re.findall(r'<item>.*?</item>', feed_text, re.DOTALL)
                    
                    if items_raw:
                        print(f"Coletando notícias RSS de: {name} (Encontrados {len(items_raw)} posts)")
                        for item_raw in items_raw[:5]:  # Pega os 5 posts mais recentes
                            # Extrai o link via regex do XML bruto do item
                            link_match = re.search(r'<link[^>]*>(.*?)</link>', item_raw, re.DOTALL)
                            link_text = ""
                            if link_match:
                                link_text = link_match.group(1).strip()
                                # Remove CDATA se houver
                                link_text = re.sub(r'<!\[CDATA\[(.*?)\]\]>', r'\1', link_text).strip()
                                
                            # Usa BeautifulSoup para o resto de forma tolerante
                            item_soup = BeautifulSoup(item_raw, 'html.parser')
                            title = item_soup.find('title')
                            desc = item_soup.find('description') or item_soup.find('content:encoded')
                            
                            title_text = title.text.strip() if title else ""
                            desc_text = desc.text.strip() if desc else ""
                            
                            # Se por acaso o link_text via regex falhar, tenta o guid
                            if not link_text:
                                guid_tag = item_soup.find('guid')
                                link_text = guid_tag.text.strip() if guid_tag else ""
                                
                            # Limpa HTML da descrição
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
        
        # 2. Fallback: Raspagem HTML direta da página de notícias
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
                                if not any(item['link'] == href for item in articles):
                                    if not href.startswith('http'):
                                        href = urllib.parse.urljoin(url, href)
                                    articles.append({
                                        'publisher': name,
                                        'title': text,
                                        'link': href,
                                        'content': "",
                                        'source_type': 'html-links'
                                    })
                                    
                    news_items.extend(articles[:5])
            except Exception as e:
                print(f"Erro ao raspar blog HTML de {name}: {e}")
                
        # 3. Sempre coleta o Instagram se o handle estiver disponível (mesmo que o blog ou RSS funcione!)
        if instagram_handle:
            ig_posts = scrape_instagram_posts(instagram_handle, name)
            news_items.extend(ig_posts)
            
        time.sleep(1)
        
    return news_items

