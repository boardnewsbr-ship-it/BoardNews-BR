import json
import os
import sys
import traceback
from datetime import datetime

import database
import scraper
import enricher
import generator
import email_sender

CONFIG_FILE = 'config.json'

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Arquivo de configuração '{CONFIG_FILE}' não encontrado.")
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def run():
    print(f"--- Iniciando BoardNews BR em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")

    config = load_config()
    database.init_db()

    receiver_email = config['email']['receiver']
    settings = config.get('settings', {})
    dry_run = settings.get('dry_run', False)
    max_pre_sale_pages = settings.get('max_pre_sale_pages', 2)
    max_promo_pages = settings.get('max_promo_pages', 3)
    news_days_window = settings.get('news_days_window', 2)
    crowdfunding_days_window = settings.get('crowdfunding_days_window', 2)

    print("Iniciando raspagem de dados...")
    raw_news        = scraper.scrape_ludonews(days_window=news_days_window)
    raw_pre_sales   = scraper.scrape_playeasy_pre_sales(max_pages=max_pre_sale_pages)
    raw_promotions  = scraper.scrape_playeasy_promotions(max_pages=max_promo_pages)
    raw_catarse     = scraper.scrape_catarse(days_window=crowdfunding_days_window)
    raw_meeple      = scraper.scrape_meeplestarter(days_window=crowdfunding_days_window)

    print(f"\nColetados brutos: {len(raw_news)} notícias LudoNews | "
          f"{len(raw_pre_sales)} pré-vendas | {len(raw_promotions)} promoções | "
          f"{len(raw_catarse)} Catarse | {len(raw_meeple)} Meeple Starter")

    processed_news          = []
    processed_pre_sales     = []
    processed_promotions    = []
    processed_crowdfunding  = []   # lista única com campo 'platform' para separar no template

    # ── NOVIDADES LUDONEWS ────────────────────────────────────
    print("\nProcessando notícias LudoNews...")
    for post in raw_news:
        if database.is_duplicate_news(post['link'], post['title']):
            print(f"-> Duplicado: '{post['title']}'")
            continue

        print(f"-> Processando: '{post['title']}'")
        summary = generator.generate_news_summary(post['title'], post['content'])

        processed_news.append({
            'title':   post['title'],
            'link':    post['link'],
            'image':   post.get('image', ''),
            'summary': summary,
        })

        if not dry_run:
            database.mark_news_as_sent('LudoNews', post['title'], post['link'])

    # ── PRÉ-VENDAS PLAYEASY ───────────────────────────────────
    print("\nProcessando pré-vendas PlayEasy...")
    for game in raw_pre_sales:
        # Limpa o nome via IA — remove editora e descrição concatenados
        clean_name = generator.extract_game_name(game['name'])
        print(f"-> Nome limpo: '{clean_name}' (original: '{game['name']}')")

        if database.is_duplicate_news(game['link'], clean_name):
            print(f"-> Duplicado: '{clean_name}'")
            continue

        bgg_data = enricher.enrich_game_data(clean_name)
        players  = bgg_data.get('players') or "Jogadores: Sob consulta"
        image    = game.get('image') or bgg_data.get('image', '')

        # Tenta pegar a descrição real da página do produto
        description = scraper.scrape_playeasy_product_description(game['link'])
        if not description:
            print(f"   -> Descrição não encontrada, usando IA como fallback.")
            description = generator.generate_summary(clean_name)
        else:
            print(f"   -> Usando descrição real da página.")

        processed_pre_sales.append({
            'name':    clean_name,
            'link':    game['link'],
            'price':   game['price'],
            'image':   image,
            'players': players,
            'summary': description,
        })

        if not dry_run:
            database.mark_news_as_sent('PlayEasy Pre-Sale', clean_name, game['link'])

    # ── PROMOÇÕES PLAYEASY ────────────────────────────────────
    print("\nProcessando promoções PlayEasy...")
    for game in raw_promotions:
        # Limpa o nome via IA antes de checar duplicidade
        clean_name = generator.extract_game_name(game['name'])
        print(f"-> Nome limpo: '{clean_name}' (original: '{game['name']}')")

        if database.is_duplicate_promotion(clean_name):
            print(f"-> Duplicado (30 dias): '{clean_name}'")
            continue

        bgg_data = enricher.enrich_game_data(clean_name)
        players  = bgg_data.get('players') or "Jogadores: Sob consulta"
        image    = game.get('image') or bgg_data.get('image', '')

        # Tenta pegar a descrição real da página do produto
        description = scraper.scrape_playeasy_product_description(game['link'])
        if not description:
            print(f"   -> Descrição não encontrada, usando IA como fallback.")
            description = generator.generate_summary(clean_name)
        else:
            print(f"   -> Usando descrição real da página.")

        processed_promotions.append({
            'name':       clean_name,
            'link':       game['link'],
            'price_from': game['price_from'],
            'price_to':   game['price_to'],
            'discount':   game['discount'],
            'image':      image,
            'players':    players,
            'summary':    description,
        })

        if not dry_run:
            database.mark_promotion_as_sent(
                clean_name, game['link'],
                game['price_from'], game['price_to'], game['discount']
            )

    # ── FINANCIAMENTOS COLETIVOS ──────────────────────────────
    print("\nProcessando financiamentos coletivos...")
    for project in raw_catarse + raw_meeple:
        platform = project.get('platform', 'desconhecido')
        name     = project.get('name', '')

        if database.is_duplicate_crowdfunding(name, platform):
            print(f"-> Duplicado [{platform}]: '{name}'")
            continue

        print(f"-> Novo financiamento [{platform}]: '{name}'")
        summary = generator.generate_crowdfunding_summary(
            project_name=name,
            description=project.get('description', ''),
            platform=platform.capitalize(),
            end_date=project.get('end_date', 'A confirmar'),
        )

        processed_crowdfunding.append({
            'name':     name,
            'link':     project.get('link', ''),
            'image':    project.get('image', ''),
            'end_date': project.get('end_date', 'A confirmar'),
            'platform': platform,
            'summary':  summary,
        })

        if not dry_run:
            database.mark_crowdfunding_as_sent(name, platform, project.get('link', ''))

    # ── RESULTADO FINAL ───────────────────────────────────────
    print("\n--- Resultados Processados ---")
    print(f"LudoNews:              {len(processed_news)}")
    print(f"Pré-vendas:            {len(processed_pre_sales)}")
    print(f"Promoções:             {len(processed_promotions)}")
    print(f"Financiamentos:        {len(processed_crowdfunding)}")

    if not any([processed_news, processed_pre_sales,
                processed_promotions, processed_crowdfunding]):
        print("Nenhum conteúdo novo. Newsletter omitida.")
        return

    print("Gerando template HTML...")
    html_content = email_sender.build_the_news_html(
        processed_news, processed_pre_sales,
        processed_promotions, processed_crowdfunding
    )

    print("Enviando e-mail...")
    email_sender.send_email(receiver_email, html_content)
    print("Fluxo finalizado com sucesso!")

if __name__ == '__main__':
    try:
        run()
    except Exception:
        print("Erro crítico!")
        traceback.print_exc()
        try:
            config = load_config()
            receiver = config['email']['receiver']
            tb_str = traceback.format_exc()
            email_sender.send_error_report(receiver, "main.py", tb_str)
        except Exception as tel_err:
            print(f"Falha ao enviar relatório de erro: {tel_err}")
        sys.exit(1)
