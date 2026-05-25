import json
import os
import sys
import traceback
from datetime import datetime

# Importações dos nossos módulos locais
import database
import scraper
import enricher
import generator
import email_sender

CONFIG_FILE = 'config.json'

def load_config() -> dict:
    """Carrega as configurações do arquivo centralizado config.json."""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"Arquivo de configuração '{CONFIG_FILE}' não encontrado.")
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def run():
    print(f"--- Iniciando BoardNews BR em {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ---")
    
    # 1. Carrega configurações e inicializa banco de dados
    config = load_config()
    database.init_db()
    
    receiver_email = config['email']['receiver']
    settings = config.get('settings', {})
    dry_run = settings.get('dry_run', False)
    
    # 2. Coleta de dados em paralelo / sequencial (limite de páginas configurável)
    max_pre_sale_pages = settings.get('max_pre_sale_pages', 2)
    max_promo_pages = settings.get('max_promo_pages', 3)
    publishers = config.get('publishers', [])
    
    print("Iniciando raspagem de dados...")
    raw_news = scraper.scrape_publishers_news(publishers)
    raw_pre_sales = scraper.scrape_playeasy_pre_sales(max_pages=max_pre_sale_pages)
    raw_promotions = scraper.scrape_playeasy_promotions(max_pages=max_promo_pages)
    
    print(f"Coletados brutos: {len(raw_news)} posts de editoras, {len(raw_pre_sales)} pré-vendas, {len(raw_promotions)} promoções.")
    
    # Listas finais de envio
    processed_news = []
    processed_pre_sales = []
    processed_promotions = []
    
    # ----------------- PROCESSAMENTO: NOVIDADES DAS EDITORAS -----------------
    print("\nProcessando novidades das editoras...")
    for post in raw_news:
        # Controle de Duplicidade (Filtro prioritário local sem consumo de API)
        if database.is_duplicate_news(post['link'], post['title']):
            print(f"-> Duplicado (Já enviado antes): '{post['title']}'")
            continue
            
        # Filtragem Inteligente via IA (Executado apenas para itens 100% novos!)
        is_valuable = generator.filter_publisher_post(post['title'], post['content'])
        if not is_valuable:
            print(f"-> Ignorado (Não é anúncio/lançamento): '{post['title']}'")
            continue
            
        # Extração Inteligente do Nome do Jogo via Groq para busca precisa BGG
        game_name = generator.extract_game_name(post['title'], post['content'])
        print(f"-> Nome do jogo extraído via Groq: '{game_name}' (Post: '{post['title']}')")

        # Enriquecimento de Dados usando o nome limpo do jogo
        bgg_data = enricher.enrich_game_data(game_name)
        players = bgg_data.get('players')
        
        # Enriquecimento de Dados (Opcional - Fallback elegante se falhar no BGG)
        players = players or "Jogadores: Sob consulta"
            
        # Imagem (usa fallback do BGG se necessário)
        image = post.get('image') or bgg_data.get('image')
        
        # Geração de Resumo via IA focando no jogo e conteúdo
        summary = generator.generate_summary(game_name, post['content'])
        
        # Salva na lista
        item = {
            'publisher': post['publisher'],
            'title': post['title'],
            'link': post['link'],
            'image': image,
            'players': players,
            'summary': summary
        }
        processed_news.append(item)
        
        # Marca como enviado
        if not dry_run:
            database.mark_news_as_sent(post['publisher'], post['title'], post['link'])
            
    # ----------------- PROCESSAMENTO: LANÇAMENTOS PLAYEASY -----------------
    print("\nProcessando lançamentos PlayEasy...")
    for game in raw_pre_sales:
        if database.is_duplicate_news(game['link'], game['name']):
            print(f"-> Duplicado (Já enviado antes): '{game['name']}'")
            continue
            
        # Enriquecimento
        bgg_data = enricher.enrich_game_data(game['name'])
        players = bgg_data.get('players')
        
        # Enriquecimento de Dados (Opcional - Fallback elegante se falhar no BGG)
        players = players or "Jogadores: Sob consulta"
            
        image = game.get('image') or bgg_data.get('image')
        
        # Resumo via IA
        summary = generator.generate_summary(game['name'])
        
        item = {
            'name': game['name'],
            'link': game['link'],
            'price': game['price'],
            'image': image,
            'players': players,
            'summary': summary
        }
        processed_pre_sales.append(item)
        
        if not dry_run:
            database.mark_news_as_sent("PlayEasy Pre-Sale", game['name'], game['link'])
            
    # ----------------- PROCESSAMENTO: PROMOÇÕES PLAYEASY -----------------
    print("\nProcessando promoções PlayEasy...")
    for game in raw_promotions:
        # Filtro de duplicidade com janela de 30 dias
        if database.is_duplicate_promotion(game['name']):
            print(f"-> Duplicado (Enviado em promoção nos últimos 30 dias): '{game['name']}'")
            continue
            
        bgg_data = enricher.enrich_game_data(game['name'])
        players = bgg_data.get('players')
        
        # Enriquecimento de Dados (Opcional - Fallback elegante se falhar no BGG)
        players = players or "Jogadores: Sob consulta"
            
        image = game.get('image') or bgg_data.get('image')
        summary = generator.generate_summary(game['name'])
        
        item = {
            'name': game['name'],
            'link': game['link'],
            'price_from': game['price_from'],
            'price_to': game['price_to'],
            'discount': game['discount'],
            'image': image,
            'players': players,
            'summary': summary
        }
        processed_promotions.append(item)
        
        if not dry_run:
            database.mark_promotion_as_sent(game['name'], game['link'], game['price_from'], game['price_to'], game['discount'])
            
    # 5. Validação final e Envio do E-mail
    print("\n--- Resultados Processados ---")
    print(f"Editoras: {len(processed_news)} novas")
    print(f"Pré-vendas: {len(processed_pre_sales)} novas")
    print(f"Promoções: {len(processed_promotions)} novas")
    
    if not processed_news and not processed_pre_sales and not processed_promotions:
        print("Nenhum conteúdo novo detectado para enviar nesta rodada. Newsletter omitida.")
        return
        
    print("Gerando template HTML...")
    html_content = email_sender.build_the_news_html(processed_news, processed_pre_sales, processed_promotions)
    
    print("Enviando e-mail...")
    email_sender.send_email(receiver_email, html_content)
    print("Fluxo finalizado com sucesso!")

if __name__ == '__main__':
    try:
        run()
    except Exception as err:
        print("Erro crítico no sistema de orquestração!")
        traceback.print_exc()
        
        # Telemetria: tenta notificar o usuário por e-mail caso o fluxo principal quebre
        try:
            config = load_config()
            receiver = config['email']['receiver']
            tb_str = traceback.format_exc()
            email_sender.send_error_report(receiver, "Orquestrador Principal (main.py)", tb_str)
            print("E-mail de telemetria de erro enviado para o usuário.")
        except Exception as tel_err:
            print(f"Erro ao tentar enviar relatório de falhas por e-mail: {tel_err}")
        sys.exit(1)
