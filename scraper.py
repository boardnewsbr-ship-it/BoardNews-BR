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


def _extract_img_url(img_tag) -> str:
    """
    Extrai a URL real de uma <img>, priorizando atributos de lazy-loading
    (data-src, data-lazy-src, etc). Sites com carregamento preguiçoso de
    imagem deixam o "src" como um placeholder (base64 em branco, ou vazio)
    até o elemento entrar na tela — como o scraper nunca rola/espera cada
    imagem individualmente, produtos "abaixo da dobra" no HTML capturado
    ficavam sem foto se a gente lesse só o "src". Por isso os atributos de
    lazy-load são checados primeiro.
    """
    if not img_tag:
        return ''
    for attr in ('data-src', 'data-lazy-src', 'data-original', 'data-lazy', 'data-image'):
        val = (img_tag.get(attr) or '').strip()
        if val and not val.startswith('data:'):
            return val
    src = (img_tag.get('src') or '').strip()
    if src and not src.startswith('data:'):
        return src
    # Último recurso: retorna o que tiver (mesmo vazio ou base64), melhor
    # do que travar — o e-mail já trata ausência de imagem graciosamente.
    return src

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
            image = _extract_img_url(img_tag)

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

def _parse_catarse_deadline(text: str) -> str | None:
    """
    Interpreta os formatos de prazo do novo Catarse (catarse.com.br):
    - "Faltam 17 dias"               -> calcula data futura
    - "Lançamento em 15d 12h 43m"    -> projeto ainda não lançado (comingSoon)
    - "Lançamento em breve"          -> sem data definida
    - "24h 43m 14s"                  -> contagem regressiva final (últimas horas)
    Retorna string formatada 'DD/MM/AAAA' ou None se não houver prazo aplicável.
    """
    if not text:
        return None
    text = text.strip()

    if 'em breve' in text.lower():
        return None

    # "Faltam N dias"
    m = re.search(r'faltam\s+(\d+)\s+dias?', text, re.IGNORECASE)
    if m:
        dias = int(m.group(1))
        return (datetime.now() + timedelta(days=dias)).strftime('%d/%m/%Y')

    # "Lançamento em Xd Yh Zm" (projeto ainda não lançado — usamos como data de lançamento)
    m = re.search(r'(\d+)d\s+(\d+)h\s+(\d+)m', text)
    if m:
        dias = int(m.group(1))
        return (datetime.now() + timedelta(days=dias)).strftime('%d/%m/%Y')

    # Contagem regressiva pura "24h 43m 14s" -> últimas horas da campanha
    m = re.search(r'^(\d+)h\s+(\d+)m\s+(\d+)s$', text)
    if m:
        return datetime.now().strftime('%d/%m/%Y')

    return None


def scrape_catarse(days_window: int = 2) -> list:
    """
    Coleta projetos da categoria Jogos no novo Catarse (catarse.com.br).
    O site é um SPA Next.js; a listagem de cards é renderizada client-side,
    por isso o Selenium é obrigatório (requests simples não basta).

    Cada card de projeto é identificado pelo padrão de link
    '?ref=ctrse_..._project_card' — muito mais estável que adivinhar
    containers genéricos, já que a página também tem cards de criador,
    banners e links de categoria com estrutura parecida.
    """
    url = "https://www.catarse.com.br/discovery?category=2&filterBy=recent"
    print(f"Coletando projetos Catarse ({url})...")

    html = _selenium_get(
        url, wait_seconds=10,
        wait_for_selector='a[href*="ctrse_"]'
    )
    if not html:
        print("   -> Selenium indisponível. Catarse ignorado.")
        return []

    soup = BeautifulSoup(html, 'html.parser')

    project_links = [
        a for a in soup.find_all('a', href=True)
        if 'ref=ctrse_' in a['href'] and '_project_card' in a['href']
    ]
    print(f"   -> {len(project_links)} link(s) de card de projeto na página.")

    seen_slugs = set()
    projects = []

    for a in project_links:
        href = a['href'].strip()
        href_full = href if href.startswith('http') else f"https://www.catarse.com.br{href}"
        slug = href_full.split('catarse.com.br/')[-1].split('?')[0].strip('/')

        if not slug or slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        # Sobe até o container do card: ancestral mais próximo que tenha
        # tanto uma <img> quanto um <h3> (título do card em destaque).
        container = a
        for _ in range(6):
            parent = container.parent
            if parent is None or parent.name in ('body', 'html'):
                break
            container = parent
            if container.find('img') and container.find(['h2', 'h3']):
                break

        title_tag = container.find(['h2', 'h3'])
        name = title_tag.get_text(strip=True) if title_tag else a.get_text(strip=True)
        if not name or len(name) < 2:
            continue

        # Remove o badge de "+18" e contagem de seguidores que por vezes
        # se mistura ao texto do link âncora (ex: "Triangle Agency RPGAvatar...338 seguidores")
        name = re.sub(r'(Avatar)+\d*\s*seguidores$', '', name).strip()
        name = re.sub(r'^\+\d+\s*', '', name).strip()

        img_tag = container.find('img')
        image = _extract_img_url(img_tag)

        # Categoria do projeto: texto puro logo após o nome do criador,
        # geralmente a última linha de texto curta do card (ex: "Jogos").
        card_lines = [
            t for t in container.stripped_strings
            if t and t != name
        ]
        category = card_lines[-1] if card_lines else ''

        if category and category.lower() != 'jogos':
            # Card fora da categoria Jogos (ex: lixo de seção cruzada) — ignora.
            continue

        # Prazo/status: procura o texto que contenha 'Faltam', 'Lançamento' ou contagem regressiva
        deadline_text = ''
        for t in card_lines:
            if re.search(r'faltam|lançamento|^\d+h\s+\d+m\s+\d+s$', t, re.IGNORECASE):
                deadline_text = t
                break

        end_date = _parse_catarse_deadline(deadline_text)

        # Descrição curta: nome do criador. Exclui categoria, prazo e o badge
        # de percentual de financiamento (ex: "207%"), que também aparece como
        # texto solto no card e não deve ser confundido com o nome do criador.
        is_percent_badge = re.compile(r'^\d+%$')
        description = next(
            (t for t in card_lines
             if t not in (category, deadline_text) and not is_percent_badge.match(t)),
            name
        )

        print(f"   -> Projeto: '{name}' [{category or 'sem categoria'}]")
        projects.append({
            'name':        name,
            'link':        href_full,
            'description': description,
            'image':       image,
            'end_date':    end_date or 'A confirmar',
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
        image = _extract_img_url(img_tag) if img_tag else ''

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

def scrape_playeasy_product_description(url: str, driver=None) -> str | None:
    """
    Busca a descrição real do produto na página individual da PlayEasy.
    Recebe um driver Selenium já aberto para reutilização (mais eficiente).
    Se driver=None, abre e fecha um driver próprio.

    Estratégia (confirmada via inspeção real do HTML da PlayEasy, ago/2026):
    1. id="descricao" — a página usa abas por âncora (o link da aba é
       <a href="#descricao">Descrição Geral</a>) e o conteúdo já vem no
       HTML dentro de um elemento com esse id, só fica visualmente
       escondido até o clique. Não depende de nome de classe CSS, que
       muda a cada redesign do site — é a estratégia mais robusta.
    2. div.prose — classe do Tailwind Typography, formato usado antes da
       reestruturação do site. Mantido como fallback.
    3. Heading (h2/h3) cujo texto comece com "descri" (cobre tanto
       "Descrição" quanto "Descrição Geral") + <div> ou <p> seguinte.
    4. Segue o href="#algumId" do link da aba de descrição, seja qual for
       o id, e pega o texto do elemento correspondente.

    Não há fallback genérico nem geração por IA: se nenhuma estratégia
    encontrar o texto, retorna None.
    """
    own_driver = False
    if driver is None:
        driver = _get_selenium_driver()
        own_driver = True
        if not driver:
            return None

    try:
        driver.get(url)
        time.sleep(4)
        html = driver.page_source
    except Exception as e:
        print(f"   -> Erro ao acessar página do produto {url}: {e}")
        return None
    finally:
        if own_driver:
            try:
                driver.quit()
            except Exception:
                pass

    soup = BeautifulSoup(html, 'html.parser')

    # 1. id="descricao" — confirmado via inspeção real (ago/2026)
    tag = soup.find(id='descricao')
    if tag:
        text = tag.get_text(separator=' ', strip=True)
        if len(text) > 20:
            print(f"   -> Descrição encontrada via id='descricao'")
            return text[:800]

    # 2. Seletor direto — div.prose (Tailwind Typography, formato antigo)
    tag = soup.select_one('div.prose')
    if tag:
        text = tag.get_text(separator=' ', strip=True)
        if len(text) > 20:
            print(f"   -> Descrição encontrada via 'div.prose'")
            return text[:800]

    # 3. Fallback estrutural — heading que comece com "descri" (cobre
    # "Descrição" e "Descrição Geral") + div/p seguinte
    for heading in soup.find_all(['h2', 'h3']):
        heading_text = heading.get_text(strip=True).lower()
        if heading_text.startswith('descri'):
            sibling = heading.find_next_sibling(['div', 'p'])
            if sibling:
                text = sibling.get_text(separator=' ', strip=True)
                if len(text) > 20:
                    print(f"   -> Descrição encontrada via heading '{heading.get_text(strip=True)}'")
                    return text[:800]

    # 4. Último recurso — segue o href="#id" do link da aba de descrição
    tab_link = soup.find('a', href=re.compile(r'#descri', re.IGNORECASE))
    if tab_link:
        target_id = tab_link.get('href', '').lstrip('#')
        tag = soup.find(id=target_id) if target_id else None
        if tag:
            text = tag.get_text(separator=' ', strip=True)
            if len(text) > 20:
                print(f"   -> Descrição encontrada via link de aba (#{target_id})")
                return text[:800]

    print(f"   -> Descrição não encontrada em {url} (nenhuma estratégia funcionou).")
    return None


def _parse_playeasy_products(html: str, mode: str) -> list:
    """
    Extrai produtos do HTML da PlayEasy renderizado pelo Selenium.
    O site usa links relativos (ex: /et-de-varginha) e Tailwind CSS.

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
        # Slugs adicionais confirmados na reestruturação de URLs da PlayEasy
        # (site migrou de /pagina.html para /pagina, sem extensão) — ver PDR.
        'pre-venda', 'desconto-relampago', 'lancamentos-doff',
        'vitrine-inicial', 'my-account', 'cadastro', 'central-do-cliente',
        'empresa', 'como-comprar', 'entrega', 'sacdefeito',
        'trocas-e-devolucoes', 'reposicao-de-pecas-e-componentes',
        'privacidade',
    }

    # Agrupa <a> por slug de produto.
    # A partir da reestruturação do site (~jul/2026), os links de produto
    # deixaram de terminar em ".html" (ex: "fromage.html" -> "fromage").
    # Normalizamos removendo ".html" quando presente, para funcionar com
    # ambos os formatos (novo e antigo, caso o site volte atrás). Também
    # aceitamos tanto href relativo ("/fromage") quanto absoluto
    # ("https://www.playeasy.com.br/fromage"), pois não há garantia de
    # qual formato o site usa em cada seção.
    all_hrefs = [a.get('href', '').strip() for a in soup.find_all('a', href=True)]

    def _to_path(href: str) -> str | None:
        for prefix in ('https://www.playeasy.com.br', 'http://www.playeasy.com.br',
                       'https://playeasy.com.br', 'http://playeasy.com.br'):
            if href.startswith(prefix):
                return href[len(prefix):] or '/'
        if href.startswith('/'):
            return href
        return None

    product_map = {}
    for a in soup.find_all('a', href=True):
        href = a.get('href', '').strip()
        path = _to_path(href)
        if path is None:
            continue
        path = path.split('?')[0].rstrip('/')
        if path.endswith('.html'):
            path = path[:-5]
        slug = path.lstrip('/')
        # Só aceita slugs de 1 nível (produtos ficam na raiz do domínio).
        # Links com "/" no meio são categorias/subcategorias (ex: editoras/asmodee).
        if not slug or '/' in slug or slug in NAV_SLUGS:
            continue
        if slug not in product_map:
            product_map[slug] = {'href': '/' + slug, 'tags': []}
        product_map[slug]['tags'].append(a)

    if not product_map:
        print(f"   -> Nenhum link de produto encontrado. "
              f"({len(all_hrefs)} <a href> no total na página)")
        if all_hrefs:
            amostra = all_hrefs[:8]
            print(f"   -> Amostra de hrefs encontrados: {amostra}")
        return []

    print(f"   -> {len(product_map)} produto(s) únicos encontrados.")

    for slug, data in product_map.items():
        tags = data['tags']
        full_url = 'https://www.playeasy.com.br' + data['href']

        # 1. Imagem — primeiro <a> do grupo que contém <img> com URL válida
        img_url = ''
        for a in tags:
            img = a.find('img')
            if img:
                img_url = _extract_img_url(img)
                if img_url:
                    break

        # 2. Nome — extrai apenas o nome do jogo, sem editora nem descrição
        #
        # Estratégia primária: atributo "alt" da imagem do produto. Desde a
        # reestruturação do site (~jul/2026), o link de texto passou a vir
        # com nome E preço concatenados no mesmo <a> (ex: "Coup: Promo Pack
        # #3 R$ 19,90 R$ 17,90 -10% OFF à vista..."), então o filtro por
        # SKIP_PATTERNS abaixo descarta esse link inteiro. O "alt" da <img>
        # continua limpo e é a fonte mais confiável.
        raw_name = ''
        for a in tags:
            img = a.find('img')
            if img:
                alt = (img.get('alt') or '').strip()
                if alt and len(alt) > len(raw_name):
                    raw_name = alt

        # Fallback 1: filtra links de texto que não contenham preço/ruído.
        SKIP_PATTERNS = ('r$', '%', 'off', 'pré-venda', 'add ao', 'carrinho',
                         'à vista', 'ou em', 'pixou', 'preorderconsentrequired')
        if not raw_name:
            for a in tags:
                t = a.get_text(strip=True)
                tl = t.lower()
                if not t or any(p in tl for p in SKIP_PATTERNS):
                    continue
                if len(t) > len(raw_name):
                    raw_name = t

        # Fallback 2: nome e preço vieram grudados no mesmo link — corta
        # tudo a partir do primeiro "R$".
        if not raw_name:
            for a in tags:
                t = a.get_text(strip=True)
                if 'r$' in t.lower():
                    candidate = re.split(r'R\$', t, flags=re.IGNORECASE)[0].strip()
                    if candidate and len(candidate) > len(raw_name):
                        raw_name = candidate

        # Corta o nome no ponto onde o texto da editora começa colado SEM ESPAÇO
        # Ex: "ET de VarginhaBoard Game" → "ET de Varginha" (corta em "a" + "B")
        # Ex: "Duna: Traição AsmodeeA" → "Duna: Traição Asmodee" → ver próximo passo
        name = re.split(r'(?<=[a-záéíóúàãõâêôç])(?=[A-Z])', raw_name)[0].strip()

        # Corta também onde o nome termina e a editora vem separada por espaço
        # Só corta quando a próxima "palavra" é nome próprio seguido imediatamente
        # de outra maiúscula colada (ex: "Asmodee" + "A" sem espaço)
        name = re.split(r'\s+(?=[A-Z][a-záéíóúàãõâêôç]*[A-Z])', name)[0].strip()

        # Limita a 60 caracteres para evitar descrições longas
        if len(name) > 60:
            name = name[:60].rsplit(' ', 1)[0].strip()

        if not name or len(name) < 3:
            continue

        # 3. Preços — filtra parcelas de parcelamento
        # O link de preço contém texto como "R$ 249,90R$ 232,41-7%À vista no pixou em 5x de R$ 46,48"
        # Precisamos dos dois primeiros preços (original e promocional), ignorando parcelas
        price_link_text = ''
        for a in tags:
            t = a.get_text(strip=True)
            if 'r$' in t.lower() and any(c in t for c in ['%', 'à vista', 'pix']):
                price_link_text = t
                break

        # Fallback: concatena texto de todos os tags com R$
        if not price_link_text:
            price_link_text = ' '.join(
                a.get_text() for a in tags if 'R$' in a.get_text()
            )

        # Extrai todos os valores R$ encontrados
        all_raw_prices = re.findall(r'R\$\s*([\d.,]+)', price_link_text)
        all_prices = sorted(set(
            clean_price('R$ ' + p) for p in all_raw_prices
            if clean_price('R$ ' + p) > 0
        ), reverse=True)  # maior para menor

        # Filtra parcelas: remove preços menores que 30% do maior preço
        if all_prices:
            max_price = all_prices[0]
            main_prices = [p for p in all_prices if p >= max_price * 0.30]
        else:
            main_prices = []

        if mode == 'pre-sale':
            # Para pré-venda, pega o menor preço dos principais (preço atual)
            price = main_prices[-1] if main_prices else 0.0
            results.append({
                'name': name, 'link': full_url,
                'price': price, 'image': img_url,
                'type': 'pre-sale',
            })

        elif mode == 'promotion':
            if len(main_prices) < 2:
                continue
            price_from = main_prices[0]   # maior = preço original
            price_to   = main_prices[-1]  # menor dos principais = preço promocional
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
    Reutiliza um único driver Chrome para todas as páginas.
    """
    # A PlayEasy migrou de /vitrine/pre-venda.html para /pre-venda (sem
    # extensão .html) e trocou o parâmetro de paginação de ?page= para ?pg=.
    base_url = "https://www.playeasy.com.br/pre-venda"
    results = []
    driver = _get_selenium_driver()
    if not driver:
        print("   -> Selenium indisponível. Pré-vendas ignoradas.")
        return []

    try:
        for page in range(1, max_pages + 1):
            url = f"{base_url}?pg={page}" if page > 1 else base_url
            print(f"Raspando pré-vendas: {url}")
            try:
                driver.get(url)
                time.sleep(6)
                html = driver.page_source
            except Exception as e:
                print(f"   -> Erro Selenium página {page}: {e}")
                break

            page_results = _parse_playeasy_products(html, mode='pre-sale')
            if not page_results:
                break
            results.extend(page_results)
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return results


# ─────────────────────────────────────────────
# PLAYEASY — Promoções
# ─────────────────────────────────────────────

def scrape_playeasy_promotions(max_pages: int = 20) -> list:
    """
    Raspa os produtos em promoção da PlayEasy via Selenium.
    Reutiliza um único driver Chrome para todas as páginas (mais eficiente).
    Retorna apenas itens COM desconto real (price_from > price_to).
    """
    # A PlayEasy migrou de /promocoes.html para /promocoes (sem extensão
    # .html) e trocou o parâmetro de paginação de ?page= para ?pg=.
    base_url = "https://www.playeasy.com.br/promocoes"
    results = []
    driver = _get_selenium_driver()
    if not driver:
        print("   -> Selenium indisponível. Promoções ignoradas.")
        return []

    try:
        for page in range(1, max_pages + 1):
            url = f"{base_url}?pg={page}" if page > 1 else base_url
            print(f"Raspando promoções: {url}")
            try:
                driver.get(url)
                time.sleep(6)
                html = driver.page_source
            except Exception as e:
                print(f"   -> Erro Selenium página {page}: {e}")
                break

            page_results = _parse_playeasy_products(html, mode='promotion')
            if not page_results:
                print(f"   -> Nenhum produto na página {page}, parando paginação.")
                break
            results.extend(page_results)
            print(f"   -> Página {page}: {len(page_results)} produtos. Total acumulado: {len(results)}.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

    return results
