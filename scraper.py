import requests
from bs4 import BeautifulSoup
import re
import warnings
import os
import json
import time
from datetime import datetime, timedelta, date
from bs4 import XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

# URL do proxy Cloudflare Workers — configurada via variável de ambiente ou config.json
# O proxy contorna bloqueios de IP de datacenter em sites como Catarse e Meeple Starter.
_PROXY_URL = None


def load_settings() -> dict:
    """Carrega as configurações do config.json (fallback para valores padrão)."""
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                return json.load(f).get('settings', {})
    except Exception:
        pass
    return {}


def _get_proxy_url() -> str:
    """
    Retorna a URL base do proxy Cloudflare Workers.
    Prioridade: variável de ambiente PROXY_URL > config.json > vazio (sem proxy).
    """
    global _PROXY_URL
    if _PROXY_URL is not None:
        return _PROXY_URL

    # 1. Variável de ambiente (GitHub Secret)
    _PROXY_URL = os.environ.get("PROXY_URL", "").strip().rstrip('/')

    # 2. Fallback: config.json
    if not _PROXY_URL:
        settings = load_settings()
        _PROXY_URL = settings.get("proxy_url", "").strip().rstrip('/')

    if _PROXY_URL:
        print(f"   -> Proxy configurado: {_PROXY_URL}")
    else:
        print("   -> AVISO: PROXY_URL não configurada. Tentando acesso direto (pode falhar em datacenter).")

    return _PROXY_URL


def _fetch_via_proxy(url: str, timeout: int = 15) -> requests.Response | None:
    """
    Faz uma requisição HTTP passando pela URL do proxy Cloudflare Workers.
    O proxy adiciona ?url=<target> e repassa a resposta com IP residencial.
    Retorna None em caso de falha.
    """
    proxy_base = _get_proxy_url()

    if proxy_base:
        proxy_url = f"{proxy_base}?url={requests.utils.quote(url, safe='')}"
        try:
            resp = requests.get(proxy_url, headers=HEADERS, timeout=timeout)
            if resp.status_code == 200:
                return resp
            print(f"   -> Proxy retornou {resp.status_code} para {url[:60]}")
        except Exception as e:
            print(f"   -> Falha no proxy: {e}")

    # Fallback: acesso direto
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        return resp
    except Exception as e:
        print(f"   -> Falha no acesso direto: {e}")
        return None


def clean_price(price_str: str) -> float:
    """Converte uma string de preço (ex: 'R$ 128,80') para float."""
    if not price_str:
        return 0.0
    cleaned = price_str.replace('R$', '').replace('.', '').replace(',', '.').strip()
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _parse_br_date(date_str: str) -> date | None:
    """
    Tenta parsear datas nos formatos comuns encontrados em sites BR.
    Retorna um objeto date ou None se não conseguir.
    """
    date_str = date_str.strip()
    # Mapeamento de meses em PT-BR
    meses = {
        'jan': 1, 'fev': 2, 'mar': 3, 'abr': 4, 'mai': 5, 'jun': 6,
        'jul': 7, 'ago': 8, 'set': 9, 'out': 10, 'nov': 11, 'dez': 12,
        'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4, 'maio': 5,
        'junho': 6, 'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10,
        'novembro': 11, 'dezembro': 12,
    }

    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y', '%d/%m/%y'):
        try:
            return datetime.strptime(date_str, fmt).date()
        except ValueError:
            pass

    # "15 de maio de 2025" ou "15 mai 2025"
    m = re.search(r'(\d{1,2})\s+(?:de\s+)?([a-záãéêíóôõú]+)\.?\s+(?:de\s+)?(\d{4})',
                  date_str, re.IGNORECASE)
    if m:
        dia, mes_str, ano = int(m.group(1)), m.group(2).lower().rstrip('.'), int(m.group(3))
        mes = meses.get(mes_str[:3])
        if mes:
            try:
                return date(ano, mes, dia)
            except ValueError:
                pass

    return None


# ─────────────────────────────────────────────
# LUDONEWS — Ludopedia
# ─────────────────────────────────────────────

def scrape_ludonews(days_window: int = 2) -> list:
    """
    Coleta notícias do canal LudoNews da Ludopedia.
    Retorna apenas notícias publicadas nos últimos `days_window` dias.

    A Ludopedia não oferece RSS para canais, então fazemos raspagem HTML
    da página de listagem do canal e acessamos cada artigo individualmente.
    """
    url = "https://ludopedia.com.br/canal/ludonews"
    print(f"Coletando LudoNews da Ludopedia ({url})...")

    cutoff = datetime.now().date() - timedelta(days=days_window)
    news_items = []

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
        if response.status_code != 200:
            print(f"   -> Erro HTTP {response.status_code} ao acessar LudoNews.")
            return []

        soup = BeautifulSoup(response.content, 'html.parser')

        # Cada notícia está em um card/artigo na listagem
        # Tenta seletores comuns de listagem de posts da Ludopedia
        cards = (
            soup.select('div.post-item') or
            soup.select('article') or
            soup.select('div.card') or
            soup.select('div.blog-post') or
            soup.select('li.item-post')
        )

        if not cards:
            # Fallback: coleta todos os links que parecem ser posts do canal
            all_links = soup.find_all('a', href=re.compile(r'/topico/|/post/|/noticia/'))
            cards_fallback = []
            seen = set()
            for a in all_links:
                href = a.get('href', '')
                if href not in seen and len(a.text.strip()) > 15:
                    seen.add(href)
                    cards_fallback.append({'link': href, 'title': a.text.strip()})
            print(f"   -> {len(cards_fallback)} links encontrados via fallback.")

            for item in cards_fallback[:10]:
                link = item['link']
                if not link.startswith('http'):
                    link = 'https://ludopedia.com.br' + link
                news_items.append({
                    'title': item['title'],
                    'link': link,
                    'content': item['title'],
                    'image': '',
                    'published_date': None,
                    'source': 'ludonews',
                })
            return news_items

        print(f"   -> {len(cards)} cards encontrados na listagem.")

        for card in cards[:15]:
            # Título e link
            title_tag = card.select_one('h1 a, h2 a, h3 a, a.post-title, a.titulo, .card-title a')
            if not title_tag:
                title_tag = card.find('a')
            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            link = title_tag.get('href', '')
            if not link.startswith('http'):
                link = 'https://ludopedia.com.br' + link

            # Data de publicação
            pub_date = None
            date_tag = card.select_one('time, .date, .post-date, .data, span.small')
            if date_tag:
                date_text = date_tag.get('datetime', '') or date_tag.get_text(strip=True)
                pub_date = _parse_br_date(date_text)

            # Filtra pela janela de tempo (se conseguiu parsear a data)
            if pub_date and pub_date < cutoff:
                continue

            # Snippet / resumo do card
            snippet_tag = card.select_one('p, .excerpt, .resumo, .card-text')
            content = snippet_tag.get_text(strip=True) if snippet_tag else title

            # Imagem do card
            img_tag = card.select_one('img')
            image = img_tag.get('src', '') if img_tag else ''

            news_items.append({
                'title': title,
                'link': link,
                'content': content,
                'image': image,
                'published_date': pub_date,
                'source': 'ludonews',
            })

        print(f"   -> {len(news_items)} notícia(s) recentes (últimos {days_window} dias).")

    except Exception as e:
        print(f"   -> Erro ao raspar LudoNews: {e}")

    return news_items


# ─────────────────────────────────────────────
# FINANCIAMENTO COLETIVO — Catarse
# ─────────────────────────────────────────────

def _get_selenium_driver():
    """
    Cria um driver Chrome headless para contornar proteções Cloudflare WAF
    que bloqueiam IPs de datacenter (GitHub Actions).
    Retorna None se o Selenium/Chrome não estiver disponível.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service

        options = Options()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-gpu')
        options.add_argument('--window-size=1280,800')
        options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                             'AppleWebKit/537.36 (KHTML, like Gecko) '
                             'Chrome/120.0.0.0 Safari/537.36')
        options.add_argument('--lang=pt-BR')

        driver = webdriver.Chrome(options=options)
        return driver
    except Exception as e:
        print(f"   -> Selenium indisponível: {e}")
        return None


def _selenium_get(url: str, wait_seconds: int = 4) -> str | None:
    """
    Abre uma URL com Chrome headless e retorna o HTML renderizado.
    Fecha o driver após uso.
    """
    driver = _get_selenium_driver()
    if driver is None:
        return None
    try:
        driver.get(url)
        time.sleep(wait_seconds)  # Aguarda JS renderizar
        return driver.page_source
    except Exception as e:
        print(f"   -> Erro Selenium ao acessar {url}: {e}")
        return None
    finally:
        try:
            driver.quit()
        except Exception:
            pass


# ─────────────────────────────────────────────
# FINANCIAMENTO COLETIVO — Catarse
# ─────────────────────────────────────────────

def scrape_catarse(days_window: int = 2) -> list:
    """
    Coleta projetos de jogos de tabuleiro lançados recentemente no Catarse.
    Usa Selenium (Chrome headless) para contornar o Cloudflare WAF.
    Retorna apenas projetos cujo início de campanha foi nos últimos `days_window` dias.
    """
    url = ("https://www.catarse.me/explore"
           "?ref=home_projects_we_love&mode=not_sub&category_id=14&filter=recent")
    print(f"Coletando projetos Catarse ({url})...")

    cutoff = datetime.now().date() - timedelta(days=days_window)
    projects = []

    html = _selenium_get(url, wait_seconds=5)
    if not html:
        print("   -> Selenium indisponível. Catarse ignorado.")
        return []

    soup = BeautifulSoup(html, 'html.parser')

    # Cards de projeto no Catarse
    cards = (
        soup.select('div.card-project') or
        soup.select('div[class*="project-card"]') or
        soup.select('div.w-col') or
        soup.select('article')
    )

    if not cards:
        print("   -> Nenhum card encontrado no Catarse após renderização JS.")
        # Debug: imprime primeiras 3000 chars do HTML para diagnóstico de seletores
        debug_soup = BeautifulSoup(html, 'html.parser')
        print("   -> DEBUG HTML (primeiros elementos com classe):")
        for tag in debug_soup.find_all(True, class_=True)[:30]:
            classes = ' '.join(tag.get('class', []))[:80]
            text = tag.get_text(' ', strip=True)[:60]
            print(f"      <{tag.name} class=\"{classes}\"> {text}")
        return []

    print(f"   -> {len(cards)} cards encontrados.")

    for card in cards:
        name_tag = card.select_one('h2, h3, .project-name, .title, strong, a')
        if not name_tag:
            print(f"      -> Card sem name_tag, pulando")
            continue
        name = name_tag.get_text(strip=True)
        if not name or len(name) < 3:
            print(f"      -> Card com nome vazio/curto: '{name}'")
            continue

        link_tag = card.find('a')
        link = link_tag.get('href', '') if link_tag else ''
        if link and not link.startswith('http'):
            link = 'https://www.catarse.me' + link

        img_tag = card.find('img')
        image = img_tag.get('src', img_tag.get('data-src', '')) if img_tag else ''

        # Datas
        end_date = None
        start_date = None
        for dt in card.select('time, .date, .expires, .deadline, span'):
            raw = dt.get('datetime', '') or dt.get_text(strip=True)
            parsed = _parse_br_date(raw)
            if parsed:
                if parsed >= datetime.now().date():
                    end_date = parsed
                else:
                    start_date = parsed

        print(f"      -> Card: '{name}' | start={start_date} | cutoff={cutoff}")

        if start_date and start_date < cutoff:
            print(f"      -> Ignorado por data de início antiga")
            continue

        desc_tag = card.select_one('p, .description, .excerpt')
        description = desc_tag.get_text(strip=True) if desc_tag else name

        # Filtra por jogo de tabuleiro
        combined = (name + ' ' + description).lower()
        keywords = ['tabuleiro', 'board game', 'jogo', 'cartas', 'rpg',
                    'dado', 'fichas', 'miniatura', 'estratégia', 'cooperativo']
        matched = [kw for kw in keywords if kw in combined]
        print(f"      -> Keywords encontradas: {matched}")
        if not matched:
            print(f"      -> Ignorado (não é jogo de tabuleiro): '{name}'")
            continue

        projects.append({
            'name': name,
            'link': link,
            'description': description,
            'image': image,
            'end_date': end_date.strftime('%d/%m/%Y') if end_date else 'A confirmar',
            'start_date': start_date,
            'platform': 'catarse',
        })

    print(f"   -> {len(projects)} projeto(s) recentes no Catarse.")
    return projects


# ─────────────────────────────────────────────
# FINANCIAMENTO COLETIVO — Meeple Starter
# ─────────────────────────────────────────────

def scrape_meeplestarter(days_window: int = 2) -> list:
    """
    Coleta projetos EM ANDAMENTO do Meeple Starter lançados recentemente.
    Usa Selenium (Chrome headless) para contornar o bloqueio 403 do Cloudflare.
    """
    url = "https://www.meeplestarter.com.br/projetos"
    print(f"Coletando projetos Meeple Starter ({url})...")

    cutoff = datetime.now().date() - timedelta(days=days_window)
    today = datetime.now().date()
    projects = []

    html = _selenium_get(url, wait_seconds=4)
    if not html:
        print("   -> Selenium indisponível. Meeple Starter ignorado.")
        return []

    soup = BeautifulSoup(html, 'html.parser')

    cards = (
        soup.select('div.project-card') or
        soup.select('div[class*="card"]') or
        soup.select('article') or
        soup.select('div[class*="project"]')
    )

    # Remove o card genérico "Conheça todos os nossos projetos"
    cards = [c for c in cards
             if 'conheça todos' not in c.get_text(strip=True).lower()]

    if not cards:
        print("   -> Nenhum card de projeto encontrado no Meeple Starter.")
        # Debug: imprime elementos com classe para diagnóstico
        debug_soup = BeautifulSoup(html, 'html.parser')
        print("   -> DEBUG HTML (primeiros elementos com classe):")
        for tag in debug_soup.find_all(True, class_=True)[:30]:
            classes = ' '.join(tag.get('class', []))[:80]
            text = tag.get_text(' ', strip=True)[:60]
            print(f"      <{tag.name} class=\"{classes}\"> {text}")
        return []

    print(f"   -> {len(cards)} cards encontrados.")

    for card in cards:
        name_tag = card.select_one('h2, h3, h4, .project-title, .title, strong')
        if not name_tag:
            name_tag = card.find('a')
        if not name_tag:
            continue
        name = name_tag.get_text(strip=True)
        if not name or len(name) < 3:
            continue

        link_tag = card.find('a')
        link = link_tag.get('href', '') if link_tag else ''
        if link and not link.startswith('http'):
            link = 'https://www.meeplestarter.com.br' + link

        img_tag = card.find('img')
        image = img_tag.get('src', img_tag.get('data-src', '')) if img_tag else ''

        card_text = card.get_text(' ', strip=True).lower()

        # Ignora finalizados e não iniciados
        if any(w in card_text for w in ['finalizado', 'encerrado', 'concluído']):
            print(f"   -> Ignorado (finalizado): '{name}'")
            continue
        if any(w in card_text for w in ['em breve', 'aguardando', 'não iniciado']):
            print(f"   -> Ignorado (não iniciado): '{name}'")
            continue

        # Datas
        end_date = None
        start_date = None
        all_dates = []
        for dt in card.select('time, .date, .prazo, .deadline, span, p'):
            raw = dt.get('datetime', '') or dt.get_text(strip=True)
            parsed = _parse_br_date(raw)
            if parsed:
                all_dates.append(parsed)

        if all_dates:
            future = [d for d in all_dates if d >= today]
            past = [d for d in all_dates if d < today]
            end_date = min(future) if future else None
            start_date = max(past) if past else None

        if start_date and start_date < cutoff:
            print(f"   -> Ignorado (início antigo): '{name}'")
            continue

        desc_tag = card.select_one('p, .description, .resumo')
        description = desc_tag.get_text(strip=True) if desc_tag else name

        projects.append({
            'name': name,
            'link': link,
            'description': description,
            'image': image,
            'end_date': end_date.strftime('%d/%m/%Y') if end_date else 'A confirmar',
            'platform': 'meeplestarter',
        })

    print(f"   -> {len(projects)} projeto(s) ativos recentes no Meeple Starter.")
    return projects


# ─────────────────────────────────────────────
# PLAYEASY — Pré-vendas
# ─────────────────────────────────────────────

def _parse_playeasy_products(html: str, mode: str) -> list:
    """
    Extrai produtos do HTML da PlayEasy (já renderizado pelo Selenium).
    mode: 'pre-sale' ou 'promotion'
    Tenta múltiplos seletores para ser resiliente a mudanças de layout.
    """
    soup = BeautifulSoup(html, 'html.parser')
    results = []

    # Tenta seletores em ordem de prioridade
    products = (
        soup.select('ul.products-grid li.item') or
        soup.select('li.item') or
        soup.select('div.product-item') or
        soup.select('div[class*="product-item"]') or
        soup.select('div.item') or
        soup.select('article.product')
    )

    if not products:
        print(f"   -> Nenhum produto encontrado com os seletores conhecidos.")
        # Debug: mostra primeiras tags com classe para diagnóstico
        for tag in soup.find_all(['li', 'div', 'article'], class_=True)[:5]:
            print(f"      <{tag.name} class=\"{' '.join(tag.get('class',[]))[:60]}\">")
        return []

    print(f"   -> {len(products)} produto(s) encontrados.")

    for product in products:
        # Nome e link
        name_tag = (
            product.select_one('h2.product-name a') or
            product.select_one('h2 a') or
            product.select_one('h3 a') or
            product.select_one('a.product-name') or
            product.select_one('.product-name a') or
            product.select_one('a[title]')
        )
        if not name_tag:
            continue
        name = name_tag.get('title', name_tag.get_text(strip=True)).strip()
        link = name_tag.get('href', '').strip()

        # Imagem
        img_tag = (
            product.select_one('a.product-image img') or
            product.select_one('img.product-image') or
            product.select_one('img')
        )
        img_url = img_tag.get('src', img_tag.get('data-src', '')) if img_tag else ''

        if mode == 'pre-sale':
            price = 0.0
            price_tag = (
                product.select_one('.regular-price .price') or
                product.select_one('.special-price .price') or
                product.select_one('.price-box .price') or
                product.select_one('[class*="price"]')
            )
            if price_tag:
                price = clean_price(price_tag.get_text())
            results.append({
                'name': name, 'link': link,
                'price': price, 'image': img_url,
                'type': 'pre-sale',
            })

        elif mode == 'promotion':
            price_from = 0.0
            price_to = 0.0
            old_tag = product.select_one('.old-price .price')
            special_tag = product.select_one('.special-price .price')

            if old_tag and special_tag:
                price_from = clean_price(old_tag.get_text())
                price_to = clean_price(special_tag.get_text())
            else:
                price_tag = (
                    product.select_one('.regular-price .price') or
                    product.select_one('.price-box .price')
                )
                if price_tag:
                    price_to = clean_price(price_tag.get_text())
                    price_from = price_to

            # Só inclui se tiver desconto real
            if price_from <= 0 or price_to <= 0 or price_from <= price_to:
                continue

            discount = int(round((1 - price_to / price_from) * 100))
            results.append({
                'name': name, 'link': link,
                'price_from': price_from, 'price_to': price_to,
                'discount': discount, 'image': img_url,
                'type': 'promotion',
            })

    return results


def scrape_playeasy_pre_sales(max_pages: int = 2) -> list:
    """
    Raspa os produtos em pré-venda da PlayEasy via Selenium.
    URL atualizada: /vitrine/pre-venda.html
    """
    base_url = "https://www.playeasy.com.br/vitrine/pre-venda.html"
    results = []

    for page in range(1, max_pages + 1):
        url = f"{base_url}?p={page}" if page > 1 else base_url
        print(f"Raspando pré-vendas: {url}")

        html = _selenium_get(url, wait_seconds=4)
        if not html:
            print("   -> Selenium indisponível. Pré-vendas ignoradas.")
            break

        page_results = _parse_playeasy_products(html, mode='pre-sale')
        if not page_results:
            break
        results.extend(page_results)

    return results


# ─────────────────────────────────────────────
# PLAYEASY — Promoções
# ─────────────────────────────────────────────

def scrape_playeasy_promotions(max_pages: int = 3) -> list:
    """
    Raspa os produtos em promoção da PlayEasy via Selenium.
    Retorna apenas itens COM desconto real (price_from > price_to).
    """
    base_url = "https://www.playeasy.com.br/promocoes.html"
    results = []

    for page in range(1, max_pages + 1):
        url = f"{base_url}?p={page}" if page > 1 else base_url
        print(f"Raspando promoções: {url}")

        html = _selenium_get(url, wait_seconds=4)
        if not html:
            print("   -> Selenium indisponível. Promoções ignoradas.")
            break

        page_results = _parse_playeasy_products(html, mode='promotion')
        if not page_results:
            break
        results.extend(page_results)

    return results
