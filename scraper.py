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
# SELENIUM — Chrome headless helper
# ─────────────────────────────────────────────

def _get_selenium_driver():
    """
    Cria um driver Chrome headless para contornar proteções Cloudflare WAF.
    Retorna None se Selenium/Chrome não estiver disponível.
    """
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options

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


def _selenium_get(url: str, wait_seconds: int = 4,
                  wait_for_selector: str = None) -> str | None:
    """
    Abre uma URL com Chrome headless e retorna o HTML renderizado.
    Se wait_for_selector for fornecido, aguarda o elemento aparecer.
    """
    driver = _get_selenium_driver()
    if driver is None:
        return None
    try:
        driver.get(url)
        if wait_for_selector:
            try:
                from selenium.webdriver.support.ui import WebDriverWait
                from selenium.webdriver.support import expected_conditions as EC
                from selenium.webdriver.common.by import By
                WebDriverWait(driver, wait_seconds).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, wait_for_selector))
                )
            except Exception:
                time.sleep(wait_seconds)
        else:
            time.sleep(wait_seconds)
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
    Coleta projetos de jogos de tabuleiro do Catarse via Selenium.
    Tenta múltiplos padrões de link pois o layout do SPA muda com frequência.
    """
    url = ("https://www.catarse.me/explore"
           "?ref=home_projects_we_love&mode=not_sub&category_id=14&filter=recent")
    print(f"Coletando projetos Catarse ({url})...")
    projects = []

    html = _selenium_get(url, wait_seconds=10)
    if not html:
        print("   -> Selenium indisponível. Catarse ignorado.")
        return []

    soup = BeautifulSoup(html, 'html.parser')
    all_links = soup.find_all('a', href=True)
    print(f"   -> {len(all_links)} links na página.")

    CATARSE_NAV = {
        'explore', 'login', 'start', 'pt', 'en', 'es',
        'about', 'terms', 'privacy', 'faq', 'blog', 'heroes',
    }

    seen = set()
    for a in all_links:
        href = a.get('href', '').strip()
        if not href:
            continue

        if href.startswith('/'):
            href_full = 'https://www.catarse.me' + href
        elif href.startswith('http') and 'catarse.me' in href:
            href_full = href
        else:
            continue

        path = href_full.split('catarse.me/')[-1].split('?')[0].split('/')[0]
        if not path or path in CATARSE_NAV or path in seen:
            continue
        if 'filter=' in href or 'city_name=' in href or 'category_id=' in href:
            continue
        if href_full in seen:
            continue

        seen.add(href_full)
        seen.add(path)

        container = a
        for _ in range(6):
            parent = container.parent
            if parent is None or parent.name in ['body', 'html']:
                break
            if parent.find('img'):
                container = parent
                break
            container = parent

        name_tag = container.find(['h1', 'h2', 'h3', 'h4', 'p', 'span'])
        name = name_tag.get_text(strip=True) if name_tag else a.get_text(strip=True)
        if not name or len(name) < 3:
            continue

        img_tag = container.find('img')
        image = img_tag.get('src', img_tag.get('data-src', '')) if img_tag else ''

        desc_tags = container.find_all(['p', 'span'])
        description = ' '.join(
            t.get_text(strip=True) for t in desc_tags
            if t.get_text(strip=True) and t.get_text(strip=True) != name
        )[:200] or name

        combined = (name + ' ' + description).lower()
        keywords = ['tabuleiro', 'board game', 'jogo', 'cartas', 'rpg',
                    'dado', 'fichas', 'miniatura', 'estratégia', 'cooperativo',
                    'dados', 'card game', 'tcg', 'lcg', 'jdr', 'wargame']
        if not any(kw in combined for kw in keywords):
            print(f"   -> Ignorado (não é jogo): '{name}'")
            continue

        end_date = None
        for tag in container.find_all(['span', 'p', 'div', 'time']):
            raw = tag.get('datetime', '') or tag.get_text(strip=True)
            parsed = _parse_br_date(raw)
            if parsed and parsed >= datetime.now().date():
                end_date = parsed
                break

        print(f"   -> Projeto: '{name}'")
        projects.append({
            'name':        name,
            'link':        href_full,
            'description': description,
            'image':       image,
            'end_date':    end_date.strftime('%d/%m/%Y') if end_date else 'A confirmar',
            'platform':    'catarse',
        })

    print(f"   -> {len(projects)} projeto(s) encontrados no Catarse.")
    return projects


# ─────────────────────────────────────────────
# FINANCIAMENTO COLETIVO — Meeple Starter
# ─────────────────────────────────────────────

def scrape_meeplestarter(days_window: int = 2) -> list:
    """
    Coleta projetos EM ANDAMENTO do Meeple Starter.
    Usa scroll infinito — rola até o fim antes de ler o HTML.
    """
    url = "https://www.meeplestarter.com.br/projetos"
    print(f"Coletando projetos Meeple Starter ({url})...")

    cutoff = datetime.now().date() - timedelta(days=days_window)
    today  = datetime.now().date()

    driver = _get_selenium_driver()
    if driver is None:
        print("   -> Selenium indisponível. Meeple Starter ignorado.")
        return []

    try:
        driver.get(url)

        try:
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            from selenium.webdriver.common.by import By
            WebDriverWait(driver, 15).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, 'div.loading'))
            )
            print("   -> Loading concluído.")
        except Exception:
            time.sleep(6)

        # Scroll infinito
        print("   -> Rolando página para carregar todos os projetos...")
        last_height = driver.execute_script("return document.body.scrollHeight")
        for _ in range(20):
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

        html = driver.page_source

    except Exception as e:
        print(f"   -> Erro Selenium: {e}")
        return []
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    soup = BeautifulSoup(html, 'html.parser')

    MS_NAV = {
        'projetos', 'conta', 'logout', 'envie-seu-projeto',
        'quem-somos', 'perguntas', 'contato', 'conta/apoios',
        'login', 'cadastrar', 'carrinho',
    }

    seen = set()
    projects = []

    for a in soup.find_all('a', href=re.compile(r'meeplestarter\.com\.br/')):
        href = a.get('href', '').strip().rstrip('/')
        if not href or href in seen:
            continue

        slug = href.split('meeplestarter.com.br/')[-1].split('?')[0]
        if not slug or slug in MS_NAV or '/' in slug:
            continue

        seen.add(href)

        container = a
        for _ in range(6):
            parent = container.parent
            if parent is None or parent.name in ['body', 'html']:
                break
            if parent.find('img') and len(parent.get_text(strip=True)) > 20:
                container = parent
                break
            container = parent

        name_tag = container.find(['h1', 'h2', 'h3', 'h4', 'strong'])
        name = name_tag.get_text(strip=True) if name_tag else a.get_text(strip=True)
        if not name or len(name) < 3:
            continue

        card_text = container.get_text(' ', strip=True).lower()
        if any(w in card_text for w in ['finalizado', 'encerrado', 'concluído']):
            print(f"   -> Ignorado (finalizado): '{name}'")
            continue
        if any(w in card_text for w in ['em breve', 'aguardando']):
            print(f"   -> Ignorado (não iniciado): '{name}'")
            continue

        img_tag = container.find('img')
        image = img_tag.get('src', img_tag.get('data-src', '')) if img_tag else ''

        end_date   = None
        start_date = None
        for tag in container.find_all(['span', 'p', 'div', 'time']):
            raw    = tag.get('datetime', '') or tag.get_text(strip=True)
            parsed = _parse_br_date(raw)
            if parsed:
                if parsed >= today:
                    if end_date is None or parsed < end_date:
                        end_date = parsed
                else:
                    if start_date is None or parsed > start_date:
                        start_date = parsed

        if start_date and start_date < cutoff:
            print(f"   -> Ignorado (início antigo): '{name}'")
            continue

        desc_tag = container.find('p')
        description = desc_tag.get_text(strip=True) if desc_tag else name

        print(f"   -> Projeto: '{name}'")
        projects.append({
            'name':        name,
            'link':        href,
            'description': description,
            'image':       image,
            'end_date':    end_date.strftime('%d/%m/%Y') if end_date else 'A confirmar',
            'platform':    'meeplestarter',
        })

    print(f"   -> {len(projects)} projeto(s) no Meeple Starter.")
    return projects


# ─────────────────────────────────────────────
# PLAYEASY — Pré-vendas
# ─────────────────────────────────────────────

def _parse_playeasy_products(html: str, mode: str) -> list:
    """
    Extrai produtos do HTML da PlayEasy renderizado pelo Selenium.
    O site usa links relativos (ex: /et-de-varginha.html) e Tailwind CSS.

    Estratégia:
    - Agrupa todos os <a> com mesmo href em product_map
    - Para cada produto: separa o link com nome do jogo, o link com preço e o link com imagem
    - Nome: link cujo texto NÃO contém R$, %, OFF, "Pré-venda", "Add ao carrinho"
    - Preço: extrai via regex R$ do link com texto de preço
    - Imagem: busca <img> dentro do <a> da imagem do produto (geralmente o primeiro link)
    """
    soup = BeautifulSoup(html, 'html.parser')
    results = []

    NAV_SLUGS = {
        'board-games', 'kits-covil', 'acessorios', 'rpg', 'editoras',
        'promocoes', 'vitrine', 'customer', 'wishlist',
        'cart', 'checkout', 'busca', 'search', 'login', 'conta',
        'institutional', 'contato', 'sobre', 'faq',
    }

    # Agrupa <a> por slug de produto
    product_map = {}
    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        if not href.endswith('.html') or not href.startswith('/'):
            continue
        slug = href.lstrip('/').split('.')[0].split('?')[0]
        if not slug or any(nav == slug for nav in NAV_SLUGS):
            continue
        if slug not in product_map:
            product_map[slug] = {'href': href, 'tags': []}
        product_map[slug]['tags'].append(a)

    if not product_map:
        print(f"   -> Nenhum link de produto encontrado.")
        return []

    print(f"   -> {len(product_map)} produto(s) únicos encontrados.")

    for slug, data in product_map.items():
        tags = data['tags']
        full_url = 'https://www.playeasy.com.br' + data['href']

        # 1. Imagem — primeiro <a> do grupo que contém <img>
        img_url = ''
        for a in tags:
            img = a.find('img')
            if img:
                img_url = img.get('src', img.get('data-src', ''))
                if img_url:
                    break

        # 2. Nome — link com texto que não é preço, desconto ou CTA
        SKIP_PATTERNS = ('r$', '%', 'off', 'pré-venda', 'add ao', 'carrinho',
                         'à vista', 'ou em', 'pixou', 'preorderconsentrequired')
        name = ''
        for a in tags:
            t = a.get_text(strip=True)
            tl = t.lower()
            if not t or any(p in tl for p in SKIP_PATTERNS):
                continue
            # Prefere o texto mais longo que parece nome de produto
            if len(t) > len(name):
                name = t

        # Limpa o nome: remove nome de editora colado no final
        # Ex: "ET de VarginhaBoard Game Bureau" -> "ET de Varginha"
        name = re.sub(
            r'([a-záéíóúàãõâêôçA-Z])'   # fim de palavra
            r'([A-Z][a-z])',              # início de nova palavra em maiúscula colada
            r'\1 \2', name
        )
        # Corta no primeiro padrão "EditoRA Nome" — editoras costumam ter 2+ palavras
        # Estratégia simples: pega apenas até o primeiro "bloco" de maiúsculas seguidas
        parts = re.split(r'(?<=[a-záéíóúàãõâêôç])\s+(?=[A-Z][a-záéíóúàãõâêôç]+\s+[A-Z])', name)
        name = parts[0].strip()

        if not name or len(name) < 3:
            continue

        # 3. Preços — todos os R$ encontrados nos textos do grupo
        all_price_text = ' '.join(a.get_text() for a in tags)
        price_values = sorted(set(
            clean_price(p)
            for p in re.findall(r'R\$\s*[\d.,]+', all_price_text)
            if clean_price(p) > 0
        ))

        if mode == 'pre-sale':
            price = price_values[0] if price_values else 0.0
            results.append({
                'name': name, 'link': full_url,
                'price': price, 'image': img_url,
                'type': 'pre-sale',
            })

        elif mode == 'promotion':
            if len(price_values) < 2:
                continue
            price_from = max(price_values)
            price_to   = min(price_values)
            if price_from <= price_to:
                continue
            discount = int(round((1 - price_to / price_from) * 100))
            if discount < 5:
                continue
            results.append({
                'name': name, 'link': full_url,
                'price_from': price_from, 'price_to': price_to,
                'discount': discount, 'image': img_url,
                'type': 'promotion',
            })

    print(f"   -> {len(results)} produto(s) extraídos com sucesso.")
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

        html = _selenium_get(url, wait_seconds=6, wait_for_selector='a[href*="playeasy"]')
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
        url = f"{base_url}?page={page}" if page > 1 else base_url
        print(f"Raspando promoções: {url}")

        html = _selenium_get(url, wait_seconds=6, wait_for_selector='a[href*="playeasy"]')
        if not html:
            print("   -> Selenium indisponível. Promoções ignoradas.")
            break

        page_results = _parse_playeasy_products(html, mode='promotion')
        if not page_results:
            break
        results.extend(page_results)

    return results
