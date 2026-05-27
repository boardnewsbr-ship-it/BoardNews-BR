import sqlite3
import hashlib
from datetime import datetime, timedelta

DB_FILE = 'newsletter.db'

def get_connection():
    return sqlite3.connect(DB_FILE)

def init_db():
    """Inicializa as tabelas do banco de dados caso não existam."""
    conn = get_connection()
    cursor = conn.cursor()

    # Notícias / pré-vendas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_news (
            id TEXT PRIMARY KEY,
            publisher TEXT,
            title TEXT,
            url TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Promoções (janela de 30 dias)
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

    # Financiamentos coletivos (aparece apenas uma vez, na janela de 2 dias do início)
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


# ── Notícias ──────────────────────────────────────────────────

def is_duplicate_news(url: str, title: str) -> bool:
    """Verifica se uma notícia já foi enviada (por URL ou título normalizado)."""
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
        db_norm = "".join(c.lower() for c in db_title if c.isalnum())
        if db_norm == normalized:
            return True

    return False

def mark_news_as_sent(publisher: str, title: str, url: str):
    """Marca uma notícia como enviada."""
    conn = get_connection()
    news_id = hashlib.md5(f"{publisher}:{title}:{url}".encode('utf-8')).hexdigest()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO sent_news (id, publisher, title, url, sent_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (news_id, publisher, title, url, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar notícia no banco: {e}")
    finally:
        conn.close()


# ── Promoções ─────────────────────────────────────────────────

def is_duplicate_promotion(game_name: str) -> bool:
    """Verifica se uma promoção foi enviada nos últimos 30 dias."""
    conn = get_connection()
    normalized = "".join(c.lower() for c in game_name if c.isalnum())
    cutoff = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')

    cursor = conn.cursor()
    cursor.execute('SELECT game_name FROM sent_promotions WHERE sent_at >= ?', (cutoff,))
    rows = cursor.fetchall()
    conn.close()

    for (db_name,) in rows:
        db_norm = "".join(c.lower() for c in db_name if c.isalnum())
        if db_norm == normalized:
            return True
    return False

def mark_promotion_as_sent(game_name: str, url: str, price_from: float,
                           price_to: float, discount: int):
    """Marca uma promoção como enviada. ID estável (sem data) para evitar re-inserção diária."""
    conn = get_connection()
    normalized = "".join(c.lower() for c in game_name if c.isalnum())
    promo_id = hashlib.md5(normalized.encode('utf-8')).hexdigest()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO sent_promotions
                (id, game_name, url, price_from, price_to, discount, sent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (promo_id, game_name, url, price_from, price_to, discount,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar promoção no banco: {e}")
    finally:
        conn.close()


# ── Financiamentos coletivos ──────────────────────────────────

def is_duplicate_crowdfunding(project_name: str, platform: str) -> bool:
    """
    Verifica se um projeto de financiamento coletivo já foi enviado.
    Sem janela de tempo — uma vez enviado, nunca mais aparece.
    """
    conn = get_connection()
    normalized = "".join(c.lower() for c in project_name if c.isalnum())
    cursor = conn.cursor()
    cursor.execute('SELECT project_name FROM sent_crowdfunding WHERE platform = ?', (platform,))
    rows = cursor.fetchall()
    conn.close()

    for (db_name,) in rows:
        db_norm = "".join(c.lower() for c in db_name if c.isalnum())
        if db_norm == normalized:
            return True
    return False

def mark_crowdfunding_as_sent(project_name: str, platform: str, url: str):
    """Marca um projeto de financiamento coletivo como enviado."""
    conn = get_connection()
    normalized = "".join(c.lower() for c in project_name if c.isalnum())
    cf_id = hashlib.md5(f"{platform}:{normalized}".encode('utf-8')).hexdigest()
    try:
        conn.execute('''
            INSERT OR IGNORE INTO sent_crowdfunding
                (id, project_name, platform, url, sent_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (cf_id, project_name, platform, url,
              datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar financiamento no banco: {e}")
    finally:
        conn.close()
