import sqlite3
import hashlib
from datetime import datetime, timedelta

DB_FILE = 'newsletter.db'

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_news (
            id TEXT PRIMARY KEY,
            publisher TEXT,
            title TEXT,
            url TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_promotions (
            id TEXT PRIMARY KEY,
            game_name TEXT,
            url TEXT,
            price_from REAL,
            price_to REAL,
            discount INTEGER,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_crowdfunding (
            id TEXT PRIMARY KEY,
            project_name TEXT,
            platform TEXT,
            url TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()


def is_duplicate_news(url: str, title: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM sent_news WHERE url = ?', (url,))
    if cursor.fetchone():
        conn.close()
        return True
    normalized = "".join(c.lower() for c in title if c.isalnum())
    cursor.execute('SELECT title FROM sent_news')
    rows = cursor.fetchall()
    conn.close()
    for (db_title,) in rows:
        if "".join(c.lower() for c in db_title if c.isalnum()) == normalized:
            return True
    return False

def mark_news_as_sent(publisher: str, title: str, url: str):
    conn = get_connection()
    news_id = hashlib.md5(f"{publisher}:{title}:{url}".encode()).hexdigest()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO sent_news (id, publisher, title, url, sent_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (news_id, publisher, title, url, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar notícia: {e}")
    finally:
        conn.close()


def is_duplicate_promotion(game_name: str, discount: int = None) -> bool:
    """
    Um item de promoção só é considerado "novo" se:
      - nunca foi enviado antes, OU
      - o desconto atual é MAIOR que o melhor desconto já enviado para
        esse produto (ou seja, é uma oferta genuinamente melhor).

    Sem janela de tempo: o mesmo produto pode reaparecer a qualquer
    momento, contanto que o desconto tenha melhorado desde o último
    envio. Isso evita tanto reenviar a mesma oferta de novo (o antigo
    problema resolvido por essa mudança) quanto perder um desconto
    realmente maior só porque o produto já foi enviado antes.

    Compara contra o MAIOR desconto já visto entre todos os registros
    com esse nome normalizado (pode haver mais de um registro histórico
    com nomes ligeiramente diferentes).
    """
    conn = get_connection()
    normalized = "".join(c.lower() for c in game_name if c.isalnum())
    cursor = conn.cursor()
    cursor.execute('SELECT game_name, discount FROM sent_promotions')
    rows = cursor.fetchall()
    conn.close()

    best_seen = None
    for db_name, db_discount in rows:
        if "".join(c.lower() for c in db_name if c.isalnum()) == normalized:
            db_discount = db_discount or 0
            if best_seen is None or db_discount > best_seen:
                best_seen = db_discount

    if best_seen is None:
        return False  # nunca visto -- não é duplicado, deve enviar

    if discount is None:
        # Sem desconto pra comparar (chamada legada) -- mantém
        # comportamento conservador de "já enviado = duplicado".
        return True

    return discount <= best_seen

def mark_promotion_as_sent(game_name: str, url: str, price_from: float,
                           price_to: float, discount: int):
    """
    INSERT OR REPLACE — atualiza o registro existente com o desconto e
    sent_at mais recentes. Diferente da versão anterior (que usava
    INSERT OR IGNORE para preservar o sent_at e não quebrar a janela de
    30 dias), agora a decisão de duplicidade não depende mais de tempo,
    e sim do valor do desconto (ver is_duplicate_promotion) — então
    precisamos SEMPRE gravar o desconto mais recente, para que a próxima
    comparação seja contra o valor certo.
    """
    conn = get_connection()
    normalized = "".join(c.lower() for c in game_name if c.isalnum())
    promo_id = hashlib.md5(normalized.encode()).hexdigest()
    try:
        conn.execute('''
            INSERT OR REPLACE INTO sent_promotions
                (id, game_name, url, price_from, price_to, discount, sent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (promo_id, game_name, url, price_from, price_to, discount,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar promoção: {e}")
    finally:
        conn.close()


def is_duplicate_crowdfunding(project_name: str, platform: str) -> bool:
    conn = get_connection()
    normalized = "".join(c.lower() for c in project_name if c.isalnum())
    cursor = conn.cursor()
    cursor.execute('SELECT project_name FROM sent_crowdfunding WHERE platform = ?', (platform,))
    rows = cursor.fetchall()
    conn.close()
    for (db_name,) in rows:
        if "".join(c.lower() for c in db_name if c.isalnum()) == normalized:
            return True
    return False

def mark_crowdfunding_as_sent(project_name: str, platform: str, url: str):
    conn = get_connection()
    normalized = "".join(c.lower() for c in project_name if c.isalnum())
    cf_id = hashlib.md5(f"{platform}:{normalized}".encode()).hexdigest()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO sent_crowdfunding
                (id, project_name, platform, url, sent_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (cf_id, project_name, platform, url,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar financiamento: {e}")
    finally:
        conn.close()
