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

def build_the_news_html(news_list: list, pre_sales: list, promotions: list) -> str:
    """Gera o template de e-mail HTML responsivo com estilos inline para melhor compatibilidade em clientes de e‑mail."""
    current_date = datetime.now().strftime("%d/%m/%Y")
    # Estilos inline reutilizáveis
    container_style = "max-width:600px;margin:0 auto;background-color:#ffffff;border:1px solid #e2e8f0;padding:24px;"
    header_style = "text-align:center;border-bottom:3px double #1a202c;padding-bottom:16px;margin-bottom:24px;"
    h1_style = "font-family:'Londrina Solid','Impact',-apple-system,sans-serif;font-size:32px;font-weight:900;letter-spacing:1px;margin:0 0 4px 0;text-transform:uppercase;color:#1a202c;"
    date_style = "font-size:14px;color:#718096;text-transform:uppercase;letter-spacing:2px;margin:0;"
    section_style = "margin-bottom:40px;"
    section_title_style = "font-size:18px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;border-bottom:1px solid #1a202c;padding-bottom:6px;margin-bottom:20px;color:#1a202c;"
    item_style = "margin-bottom:30px;padding-bottom:24px;border-bottom:1px solid #edf2f7;"
    item_title_style = "font-size:18px;font-weight:700;margin:0 0 10px 0;line-height:1.3;"
    item_link_style = "color:#1a202c;text-decoration:underline;"
    item_meta_style = "font-size:13px;color:#e53e3e;font-weight:600;margin-bottom:12px;text-transform:uppercase;letter-spacing:0.5px;"
    players_style = "display:inline-block;background-color:#edf2f7;color:#4a5568;font-size:12px;font-weight:600;padding:3px 8px;border-radius:4px;margin-bottom:12px;"
    content_style = "font-size:15px;line-height:1.6;color:#4a5568;margin:0 0 14px 0;"
    image_container_style = "text-align:center;margin-bottom:16px;"
    image_style = "max-width:200px;max-height:200px;height:auto;border-radius:8px;border:1px solid #e2e8f0;object-fit:contain;"
    badge_style = "background-color:#feb2b2;color:#9b2c2c;font-size:11px;font-weight:bold;padding:2px 6px;border-radius:4px;margin-left:6px;"

    html = f"""<!DOCTYPE html><html lang='pt-BR'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'><title>BoardNews BR</title></head><body><div style='{container_style}'><div style='{header_style}'><h1 style='{h1_style}'>BoardNews BR</h1><p class='date' style='{date_style}'>Notícias &amp; Ofertas • {current_date}</p></div>"""

    # Seção 1 – Novidades das Editoras
    if news_list:
        html += f"<div style='{section_style}'><div style='{section_title_style}'>I. Novidades das Editoras</div>"
        for item in news_list:
            players_html = f'<div style="{players_style}">{item["players"]}</div>' if item.get('players') else ''
            image_html = f'<div style="{image_container_style}"><img src="{item["image"]}" alt="{item["title"]}" style="{image_style}"></div>' if item.get('image') else ''
            html += f"<div style='{item_style}'><h3 style='{item_title_style}'><a href='{item["link"]}' target='_blank' style='{item_link_style}'>{item["title"]}</a></h3><div style='{item_meta_style}'>{item["publisher"]}</div>{players_html}{image_html}<div style='{content_style}'>{item["summary"]}</div></div>"
        html += "</div>"

    # Seção 2 – Lançamentos / Pré‑venda
    if pre_sales:
        html += f"<div style='{section_style}'><div style='{section_title_style}'>II. Novos Lançamentos em Pré-Venda</div>"
        for item in pre_sales:
            players_html = f'<div style="{players_style}">{item["players"]}</div>' if item.get('players') else ''
            image_html = f'<div style="{image_container_style}"><img src="{item["image"]}" alt="{item["name"]}" style="{image_style}"></div>' if item.get('image') else ''
            price_formatted = format_price(item["price"])
            html += f"<div style='{item_style}'><h3 style='{item_title_style}'><a href='{item["link"]}' target='_blank' style='{item_link_style}'>{item["name"]}</a></h3><div style='{item_meta_style}'>Preço atual: {price_formatted}</div>{players_html}{image_html}<div style='{content_style}'>{item["summary"]}</div></div>"
        html += "</div>"

    # Seção 3 – Promoções
    if promotions:
        html += f"<div style='{section_style}'><div style='{section_title_style}'>III. Ofertas &amp; Promoções Imperdíveis</div>"
        # Deduplicar promoções por link
        unique = {}
        for promo in promotions:
            link = promo.get('link')
            if link and link not in unique:
                unique[link] = promo
        promos = list(unique.values())
        for item in promos:
            players_html = f'<div style="{players_style}">{item["players"]}</div>' if item.get('players') else ''
            image_html = f'<div style="{image_container_style}"><img src="{item["image"]}" alt="{item["name"]}" style="{image_style}"></div>' if item.get('image') else ''
            price_from_fmt = format_price(item["price_from"])
            price_to_fmt = format_price(item["price_to"])
            discount_badge = f'<span style="{badge_style}">-{item["discount"]}% OFF</span>'
            html += f"<div style='{item_style}'><h3 style='{item_title_style}'><a href='{item["link"]}' target='_blank' style='{item_link_style}'>{item["name"]}</a></h3><div style='{item_meta_style}'>De: <span style='text-decoration:line-through;'>{price_from_fmt}</span> Por: <span style='color:#2b6cb0;font-size:16px;'>{price_to_fmt}</span>{discount_badge}</div>{players_html}{image_html}<div style='{content_style}'>{item["summary"]}</div></div>"
        html += "</div>"

    # Rodapé
    html += f"""<div style='text-align:center;border-top:1px solid #e2e8f0;padding-top:20px;margin-top:40px;font-size:12px;color:#a0aec0;line-height:1.5;'><p><strong>BoardNews BR</strong> é o seu boletim de notícias automatizado de jogos de tabuleiro.</p><p>Enviado diariamente de forma autônoma no horário de Brasília.</p><p>Este e‑mail foi gerado e enviado de forma 100% gratuita via GitHub Actions &amp; Resend.</p></div></div></body></html>"""
    
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
