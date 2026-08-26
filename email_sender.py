import os
import requests
from datetime import datetime

def get_resend_api_key() -> str:
    """Obtém a chave de API do Resend das variáveis de ambiente."""
    return os.environ.get("RESEND_API_KEY", "")

def format_price(value: float) -> str:
    """Formata um float em formato monetário de Real (R$)."""
    if not value or value == 0.0:
        return "R$ --"
    return f"R$ {value:,.2f}".replace(',', '_').replace('.', ',').replace('_', '.')


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _truncate(text: str, max_len: int = 40) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len - 3].rstrip() + "..."


_WEEKDAYS_PT = ['Segunda-feira', 'Terça-feira', 'Quarta-feira', 'Quinta-feira',
                'Sexta-feira', 'Sábado', 'Domingo']
_MONTHS_PT = ['', 'Janeiro', 'Fevereiro', 'Março', 'Abril', 'Maio', 'Junho',
              'Julho', 'Agosto', 'Setembro', 'Outubro', 'Novembro', 'Dezembro']


def _formatted_date_pt(dt: datetime) -> str:
    """Ex: 'QUINTA-FEIRA, 20 DE AGOSTO DE 2026'. Não depende de locale do
    sistema (que costuma faltar em runners do GitHub Actions)."""
    weekday = _WEEKDAYS_PT[dt.weekday()]
    return f"{weekday}, {dt.day} de {_MONTHS_PT[dt.month]} de {dt.year}".upper()


def _join_natural(items: list) -> str:
    """Junta itens com vírgula e 'e' antes do último, no estilo natural
    do português (ex: 'A, B e C')."""
    items = [i for i in items if i]
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " e " + items[-1]


def _build_intro_summary(news_list: list, pre_sales: list, promotions: list,
                          crowdfunding: list) -> str:
    """Frase de abertura dinâmica resumindo o conteúdo do dia, no espírito
    de newsletters como a The News."""
    bits = []
    if news_list:
        bits.append(_plural(len(news_list), 'notícia', 'notícias'))
    if pre_sales:
        bits.append(_plural(len(pre_sales), 'pré-venda', 'pré-vendas'))
    if promotions:
        bits.append(_plural(len(promotions), 'promoção', 'promoções'))
    if crowdfunding:
        bits.append(_plural(len(crowdfunding), 'financiamento coletivo',
                             'financiamentos coletivos'))
    if not bits:
        return "Um dia tranquilo no universo dos jogos de tabuleiro."
    return f"Hoje tem {_join_natural(bits)} esperando por você."


def build_subject(news_list: list, pre_sales: list, promotions: list,
                   crowdfunding: list = None) -> str:
    """
    Monta um assunto dinâmico para o e-mail, priorizando o conteúdo mais
    chamativo do dia:
      1. Se há promoções, destaca a de maior desconto.
      2. Senão, se há pré-vendas, destaca a primeira.
      3. Senão, resume só as contagens (notícias / financiamentos).
      4. Sem nenhum conteúdo, cai no assunto genérico com a data
         (main.py já não envia e-mail nesse caso, mas mantemos o fallback
         por segurança caso a função seja chamada de outro lugar).

    Sempre soma um resumo das outras categorias com conteúdo, para dar
    uma ideia completa do que tem no e-mail sem precisar abrir.
    """
    if crowdfunding is None:
        crowdfunding = []

    def extras(skip: set) -> str:
        bits = []
        if 'news' not in skip and news_list:
            bits.append(_plural(len(news_list), 'notícia', 'notícias'))
        if 'pre_sales' not in skip and pre_sales:
            bits.append(_plural(len(pre_sales), 'pré-venda', 'pré-vendas'))
        if 'promotions' not in skip and promotions:
            bits.append(_plural(len(promotions), 'promoção', 'promoções'))
        if 'crowdfunding' not in skip and crowdfunding:
            bits.append(_plural(len(crowdfunding), 'financiamento', 'financiamentos'))
        return " · ".join(bits)

    # 1. Promoções — destaca a de maior desconto
    if promotions:
        best = max(promotions, key=lambda p: p.get('discount', 0))
        name = _truncate(best.get('name', ''))
        discount = best.get('discount', 0)
        others = len(promotions) - 1

        headline = f"{name} -{discount}% OFF"
        if others > 0:
            headline += f" e mais {_plural(others, 'oferta', 'ofertas')}"

        subject = f"BoardNews BR 🎲 • {headline}"
        rest = extras(skip={'promotions'})
        if rest:
            subject += f" · {rest}"
        return subject[:150]

    # 2. Sem promoções, mas com pré-vendas — destaca a primeira
    if pre_sales:
        name = _truncate(pre_sales[0].get('name', ''))
        others = len(pre_sales) - 1

        headline = f"Pré-venda: {name}"
        if others > 0:
            headline += f" e mais {others}"

        subject = f"BoardNews BR 🎲 • {headline}"
        rest = extras(skip={'pre_sales'})
        if rest:
            subject += f" · {rest}"
        return subject[:150]

    # 3. Só notícias e/ou financiamentos — resume as contagens
    rest = extras(skip=set())
    if rest:
        return f"BoardNews BR 🎲 • {rest}"[:150]

    # 4. Fallback — sem conteúdo (não deveria chegar aqui em uso normal)
    current_date = datetime.now().strftime("%d/%m/%Y")
    return f"BoardNews BR 🎲 • {current_date}"


def build_the_news_html(news_list: list, pre_sales: list, promotions: list,
                        crowdfunding: list = None) -> str:
    """
    Gera o template de e-mail HTML responsivo, minimalista e limpo estilo "The News".
    Seções: I. Notícias LudoNews | II. Pré-Vendas | III. Promoções | IV. Financiamentos
    """
    if crowdfunding is None:
        crowdfunding = []
    now = datetime.now()
    formatted_date = _formatted_date_pt(now)
    intro_summary = _build_intro_summary(news_list, pre_sales, promotions, crowdfunding)

    # 1. Cabeçalho do E-mail
    html = f"""
    <!DOCTYPE html>
    <html lang="pt-BR">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>BoardNews BR</title>
        <style>
            body {{
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
                background-color: #f9f9fb;
                color: #1a202c;
                margin: 0;
                padding: 0;
                -webkit-font-smoothing: antialiased;
            }}
            .container {{
                max-width: 600px;
                margin: 0 auto;
                background-color: #ffffff;
                border: 1px solid #e2e8f0;
                padding: 24px;
            }}
            .header {{
                background-color: #4c3fa8;
                background-image: linear-gradient(135deg, #4c3fa8 0%, #7c3aed 55%, #db2777 100%);
                border-radius: 18px;
                padding: 32px 24px 26px 24px;
                text-align: center;
                margin-bottom: 24px;
            }}
            .header-badge {{
                display: inline-block;
                width: 52px;
                height: 52px;
                line-height: 52px;
                background-color: #ffffff;
                border-radius: 50%;
                font-size: 26px;
                margin-bottom: 14px;
            }}
            .header h1 {{
                font-family: "Londrina Solid", "Impact", -apple-system, sans-serif;
                font-size: 30px;
                font-weight: 900;
                letter-spacing: 1px;
                margin: 0 0 6px 0;
                text-transform: uppercase;
                color: #ffffff;
            }}
            .header .tagline {{
                font-size: 14px;
                color: rgba(255, 255, 255, 0.88);
                margin: 0 0 20px 0;
            }}
            .header .date-pill {{
                display: inline-block;
                background-color: rgba(255, 255, 255, 0.16);
                border: 1px solid rgba(255, 255, 255, 0.45);
                color: #ffffff;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1.5px;
                text-transform: uppercase;
                padding: 6px 16px;
                border-radius: 999px;
            }}
            .intro {{
                text-align: center;
                margin-bottom: 28px;
            }}
            .intro-summary {{
                font-size: 16px;
                line-height: 1.5;
                color: #2d3748;
                margin: 0 0 16px 0;
            }}
            .dotted-divider {{
                letter-spacing: 8px;
                color: #cbd5e0;
                font-size: 14px;
                margin: 0;
            }}
            .section {{
                margin-bottom: 40px;
            }}
            .section-title {{
                font-size: 18px;
                font-weight: 700;
                letter-spacing: 0.5px;
                text-transform: uppercase;
                border-bottom: 1px solid #1a202c;
                padding-bottom: 6px;
                margin-bottom: 20px;
                color: #1a202c;
            }}
            .item {{
                margin-bottom: 30px;
                padding-bottom: 24px;
                border-bottom: 1px solid #edf2f7;
            }}
            .item:last-child {{
                border-bottom: none;
                margin-bottom: 0;
                padding-bottom: 0;
            }}
            .item-title {{
                font-size: 18px;
                font-weight: 700;
                margin: 0 0 10px 0;
                line-height: 1.3;
            }}
            .item-title a {{
                color: #1a202c;
                text-decoration: underline;
            }}
            .item-meta {{
                font-size: 13px;
                color: #e53e3e;
                font-weight: 600;
                margin-bottom: 12px;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }}
            .item-players {{
                display: inline-block;
                background-color: #edf2f7;
                color: #4a5568;
                font-size: 12px;
                font-weight: 600;
                padding: 3px 8px;
                border-radius: 4px;
                margin-bottom: 12px;
            }}
            .item-content {{
                font-size: 15px;
                line-height: 1.6;
                color: #4a5568;
                margin: 0 0 14px 0;
            }}
            .item-image-container {{
                text-align: center;
                margin-bottom: 16px;
            }}
            .item-image {{
                max-width: 200px;
                max-height: 200px;
                height: auto;
                border-radius: 8px;
                border: 1px solid #e2e8f0;
                object-fit: contain;
            }}
            .footer {{
                text-align: center;
                border-top: 1px solid #e2e8f0;
                padding-top: 20px;
                margin-top: 40px;
                font-size: 12px;
                color: #a0aec0;
                line-height: 1.5;
            }}
            .badge-discount {{
                background-color: #feb2b2;
                color: #9b2c2c;
                font-size: 11px;
                font-weight: bold;
                padding: 2px 6px;
                border-radius: 4px;
                margin-left: 6px;
            }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div class="header-badge">🎲</div>
                <h1>BoardNews BR</h1>
                <p class="tagline">Sua dose diária do universo dos jogos de tabuleiro</p>
                <span class="date-pill">{formatted_date}</span>
            </div>
            <div class="intro">
                <p class="intro-summary">{intro_summary}</p>
                <p class="dotted-divider">• • • • •</p>
            </div>
    """
    
    # 2. Seção 1: Notícias LudoNews
    if news_list:
        html += """
            <div class="section">
                <div class="section-title">I. Notícias — LudoNews</div>
        """
        for item in news_list:
            image_html = f'<div class="item-image-container"><img class="item-image" src="{item["image"]}" alt="{item["title"]}" width="200" style="max-width: 200px; max-height: 200px; height: auto; border-radius: 8px; border: 1px solid #e2e8f0; object-fit: contain;"></div>' if item.get('image') else ''

            html += f"""
                <div class="item">
                    <h3 class="item-title"><a href="{item["link"]}" target="_blank">{item["title"]}</a></h3>
                    <div class="item-meta">LudoNews / Ludopedia</div>
                    {image_html}
                    <div class="item-content">{item["summary"]}</div>
                </div>
            """
        html += "</div>"
        
    # 3. Seção 2: Lançamentos / Pré-venda PlayEasy
    if pre_sales:
        html += """
            <div class="section">
                <div class="section-title">II. Novos Lançamentos em Pré-Venda</div>
        """
        for item in pre_sales:
            players_html = f'<div class="item-players">{item["players"]}</div>' if item.get('players') else ''
            image_html = f'<div class="item-image-container"><img class="item-image" src="{item["image"]}" alt="{item["name"]}" width="200" style="max-width: 200px; max-height: 200px; height: auto; border-radius: 8px; border: 1px solid #e2e8f0; object-fit: contain;"></div>' if item.get('image') else ''
            price_formatted = format_price(item["price"])
            price_pix = item.get("price_pix") or 0.0
            pix_html = (f' <span style="color: #38a169;">· {format_price(price_pix)} no Pix</span>'
                        if price_pix > 0 else '')

            html += f"""
                <div class="item">
                    <h3 class="item-title"><a href="{item["link"]}" target="_blank">{item["name"]}</a></h3>
                    <div class="item-meta">Preço atual: {price_formatted}{pix_html}</div>
                    {players_html}
                    {image_html}
                    <div class="item-content">{item["summary"]}</div>
                </div>
            """
        html += "</div>"
        
    # 4. Seção 3: Promoções PlayEasy
    if promotions:
        html += """
            <div class="section">
                <div class="section-title">III. Ofertas & Promoções Imperdíveis</div>
        """
        for item in promotions:
            players_html = f'<div class="item-players">{item["players"]}</div>' if item.get('players') else ''
            image_html = f'<div class="item-image-container"><img class="item-image" src="{item["image"]}" alt="{item["name"]}" width="200" style="max-width: 200px; max-height: 200px; height: auto; border-radius: 8px; border: 1px solid #e2e8f0; object-fit: contain;"></div>' if item.get('image') else ''
            price_from_fmt = format_price(item["price_from"])
            price_to_fmt = format_price(item["price_to"])
            price_pix = item.get("price_pix") or 0.0
            pix_html = (f' <span style="color: #38a169;">· {format_price(price_pix)} no Pix</span>'
                        if price_pix > 0 else '')

            html += f"""
                <div class="item">
                    <h3 class="item-title"><a href="{item["link"]}" target="_blank">{item["name"]}</a></h3>
                    <div class="item-meta">
                        De: <span style="text-decoration: line-through;">{price_from_fmt}</span> 
                        Por: <span style="color: #2b6cb0; font-size: 16px;">{price_to_fmt}</span>{pix_html}
                        <span class="badge-discount">-{item["discount"]}% OFF</span>
                    </div>
                    {players_html}
                    {image_html}
                    <div class="item-content">{item["summary"]}</div>
                </div>
            """
        html += "</div>"
        
    # 5. Seção 4: Financiamentos Coletivos
    if crowdfunding:
        # Separa por plataforma
        catarse_items    = [p for p in crowdfunding if p.get('platform') == 'catarse']
        meeple_items     = [p for p in crowdfunding if p.get('platform') == 'meeplestarter']

        html += """
            <div class="section">
                <div class="section-title">IV. Financiamentos Coletivos</div>
        """

        if catarse_items:
            html += '<p style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#718096;margin:0 0 12px 0;">📦 Catarse</p>'
            for item in catarse_items:
                image_html = f'<div class="item-image-container"><img class="item-image" src="{item["image"]}" alt="{item["name"]}" width="200" style="max-width: 200px; max-height: 200px; height: auto; border-radius: 8px; border: 1px solid #e2e8f0; object-fit: contain;"></div>' if item.get('image') else ''
                html += f"""
                    <div class="item">
                        <h3 class="item-title"><a href="{item["link"]}" target="_blank">{item["name"]}</a></h3>
                        <div class="item-meta">Encerra em: {item["end_date"]}</div>
                        {image_html}
                        <div class="item-content">{item["summary"]}</div>
                    </div>
                """

        if meeple_items:
            html += '<p style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#718096;margin:16px 0 12px 0;">🎲 Meeple Starter</p>'
            for item in meeple_items:
                image_html = f'<div class="item-image-container"><img class="item-image" src="{item["image"]}" alt="{item["name"]}" width="200" style="max-width: 200px; max-height: 200px; height: auto; border-radius: 8px; border: 1px solid #e2e8f0; object-fit: contain;"></div>' if item.get('image') else ''
                html += f"""
                    <div class="item">
                        <h3 class="item-title"><a href="{item["link"]}" target="_blank">{item["name"]}</a></h3>
                        <div class="item-meta">Encerra em: {item["end_date"]}</div>
                        {image_html}
                        <div class="item-content">{item["summary"]}</div>
                    </div>
                """

        html += "</div>"

    # 6. Rodapé
    html += f"""
            <div class="footer">
                <p><strong>BoardNews BR</strong> é o seu boletim de notícias automatizado de jogos de tabuleiro.</p>
                <p>Enviado diariamente de forma autônoma no horário de Brasília.</p>
                <p>Este e-mail foi gerado e enviado de forma 100% gratuita via GitHub Actions & Resend.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    return html

def send_email(to_email: str, html_content: str, subject: str = None) -> bool:
    """
    Envia um e-mail utilizando a API REST do Resend.
    """
    api_key = get_resend_api_key()
    if not api_key:
        print("AVISO: RESEND_API_KEY não configurada. Imprimindo e-mail no console (DRY RUN).")
        # Escreve o HTML em um arquivo temporário local para inspeção do usuário
        with open("mock_email.html", "w", encoding="utf-8") as f:
            f.write(html_content)
        print("E-mail mock salvo em 'mock_email.html'!")
        return True
        
    if not subject:
        current_date = datetime.now().strftime("%d/%m/%Y")
        subject = f"BoardNews BR 🎲 • {current_date}"
        
    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "from": "BoardNews BR <onboarding@resend.dev>",
        "to": to_email,
        "subject": subject,
        "html": html_content
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=15)
        if response.status_code in [200, 201]:
            print(f"E-mail enviado com sucesso para {to_email}!")
            return True
        else:
            print(f"Falha ao enviar e-mail via Resend: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Erro ao enviar e-mail via Resend: {e}")
        
    return False

def send_error_report(to_email: str, error_module: str, traceback_str: str) -> bool:
    """
    Envia um e-mail de alerta de falha de telemetria para o usuário.
    """
    current_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    subject = f"⚠️ ALERTA DE FALHA: BoardNews BR ({error_module})"
    
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Falha no Sistema</title>
        <style>
            body {{ font-family: monospace; background-color: #f7fafc; padding: 20px; }}
            .card {{ background-color: white; border: 1px solid #e2e8f0; padding: 20px; border-radius: 8px; max-width: 700px; margin: 0 auto; }}
            .header {{ color: #e53e3e; font-size: 20px; font-weight: bold; border-bottom: 2px solid #feb2b2; padding-bottom: 10px; margin-bottom: 20px; }}
            .time {{ font-size: 12px; color: #718096; }}
            .code-block {{ background-color: #2d3748; color: #a0aec0; padding: 15px; border-radius: 6px; overflow-x: auto; font-size: 13px; line-height: 1.5; }}
        </style>
    </head>
    <body>
        <div class="card">
            <div class="header">🚨 Falha na Execução do BoardNews BR</div>
            <p>Olá,</p>
            <p>O sistema autônomo de newsletter detectou uma exceção não tratada no módulo <strong>{error_module}</strong>.</p>
            <p class="time">Horário da falha: {current_time} (Horário do servidor)</p>
            <p><strong>Detalhes do Rastreamento do Erro (Traceback):</strong></p>
            <div class="code-block">
                <pre>{traceback_str}</pre>
            </div>
            <p style="margin-top:20px; font-size:12px; color:#a0aec0;">Este e-mail foi gerado automaticamente pela telemetria do sistema BoardNews BR.</p>
        </div>
    </body>
    </html>
    """
    return send_email(to_email, html, subject)
