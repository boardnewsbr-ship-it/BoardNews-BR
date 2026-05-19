import sqlite3
import os
from datetime import datetime, timedelta

DB_FILE = 'newsletter.db'

def get_connection():
    """Retorna uma conexão com o banco de dados SQLite."""
    return sqlite3.connect(DB_FILE)

def init_db():
    """Inicializa as tabelas do banco de dados caso não existam."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # Tabela para controle de novidades/lançamentos de editoras e pré-vendas
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS sent_news (
            id TEXT PRIMARY KEY,
            publisher TEXT,
            title TEXT,
            url TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela para controle de promoções (com janela de 30 dias)
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
    
    conn.commit()
    conn.close()

def is_duplicate_news(url: str, title: str) -> bool:
    """
    Verifica se uma notícia/lançamento já foi enviado antes.
    Usa tanto a URL quanto o título para evitar duplicidade de conteúdos idênticos em URLs levemente distintas.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    # Normalização simples do título para comparação resiliente
    normalized_title = "".join(c.lower() for c in title if c.isalnum())
    
    cursor.execute('''
        SELECT 1 FROM sent_news 
        WHERE url = ? OR LOWER(REPLACE(REPLACE(title, ' ', ''), '-', '')) = ?
    ''', (url, normalized_title))
    
    result = cursor.fetchone()
    conn.close()
    return result is not None

def is_duplicate_promotion(game_name: str) -> bool:
    """
    Verifica se um jogo foi enviado na seção de promoções nos últimos 30 dias.
    """
    conn = get_connection()
    cursor = conn.cursor()
    
    normalized_name = "".join(c.lower() for c in game_name if c.isalnum())
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d %H:%M:%S')
    
    cursor.execute('''
        SELECT 1 FROM sent_promotions 
        WHERE LOWER(REPLACE(REPLACE(game_name, ' ', ''), '-', '')) = ? AND sent_at >= ?
    ''', (normalized_name, thirty_days_ago))
    
    result = cursor.fetchone()
    conn.close()
    return result is not None

def mark_news_as_sent(publisher: str, title: str, url: str):
    """Marca uma notícia como enviada."""
    conn = get_connection()
    cursor = conn.cursor()
    
    # ID gerado a partir do hash do título ou URL
    import hashlib
    news_id = hashlib.md5(f"{publisher}:{title}:{url}".encode('utf-8')).hexdigest()
    
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO sent_news (id, publisher, title, url, sent_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (news_id, publisher, title, url, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar novidade no banco: {e}")
    finally:
        conn.close()

def mark_promotion_as_sent(game_name: str, url: str, price_from: float, price_to: float, discount: int):
    """Marca uma promoção como enviada."""
    conn = get_connection()
    cursor = conn.cursor()
    
    import hashlib
    promo_id = hashlib.md5(f"{game_name}:{price_to}:{datetime.now().date()}".encode('utf-8')).hexdigest()
    
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO sent_promotions (id, game_name, url, price_from, price_to, discount, sent_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (promo_id, game_name, url, price_from, price_to, discount, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
        conn.commit()
    except Exception as e:
        print(f"Erro ao salvar promoção no banco: {e}")
    finally:
        conn.close()
