import os
import requests
import json

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

def get_api_key() -> str:
    """Obtém a API Key do Gemini a partir das variáveis de ambiente."""
    return os.environ.get("GEMINI_API_KEY", "")

def call_gemini(prompt: str, response_json: bool = False) -> str:
    """
    Realiza uma chamada direta via HTTP para a API do Gemini (2.5-flash).
    """
    api_key = get_api_key()
    if not api_key:
        print("AVISO: GEMINI_API_KEY não configurada. Usando fallback básico.")
        return None
        
    url = f"{GEMINI_API_URL}?key={api_key}"
    headers = {
        "Content-Type": "application/json"
    }
    
    payload = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "temperature": 0.2
        }
    }
    
    if response_json:
        payload["generationConfig"]["responseMimeType"] = "application/json"
        
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=20)
        if response.status_code == 200:
            res_data = response.json()
            # Extrai o texto da resposta do Gemini
            text = res_data['candidates'][0]['content']['parts'][0]['text']
            return text.strip()
        else:
            print(f"Erro na API do Gemini: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"Erro ao chamar o Gemini: {e}")
        
    return None

def filter_publisher_post(title: str, content: str) -> bool:
    """
    Usa o Gemini para filtrar posts das editoras.
    Retorna True se for um anúncio/novidade de lançamento de jogo ou expansão.
    Retorna False para posts institucionais, eventos, memes, etc.
    """
    if not get_api_key():
        # Fallback se não houver API key: busca termos chaves no título
        keywords = ["lançamento", "anúncio", "chegou", "pré-venda", "novidade", "revelado", "vem aí"]
        title_lower = title.lower()
        return any(k in title_lower for k in keywords)

    prompt = f"""
    Você é um assistente especialista em jogos de tabuleiro (board games). 
    Analise o título e o conteúdo do post de uma editora abaixo e classifique se ele é:
    1. Um anúncio de lançamento futuro, uma pré-venda ou a chegada de um novo jogo/expansão nas lojas brasileiras.
    2. Outro tipo de post (institucional, foto de evento, meme, aviso de reabertura, promoção genérica da loja, etc.).

    Retorne APENAS um objeto JSON no formato exato:
    {{
      "is_announcement": true ou false,
      "reason": "uma frase curta explicando o motivo"
    }}

    Título do Post: "{title}"
    Conteúdo do Post: "{content}"
    """
    
    res_text = call_gemini(prompt, response_json=True)
    if res_text:
        try:
            data = json.loads(res_text)
            return bool(data.get("is_announcement", False))
        except Exception as e:
            print(f"Erro ao parsear resposta de filtragem do Gemini: {e}. Texto original: {res_text}")
            
    return False

def generate_summary(game_name: str, contextual_info: str = "") -> str:
    """
    Gera um resumo atraente de gameplay de no máximo 2 parágrafos.
    """
    if not get_api_key():
        # Fallback se não houver API key
        return f"Descubra as novidades incríveis e explore a proposta estratégica de {game_name}. Um jogo de tabuleiro excelente para reunir amigos e familiares para grandes momentos de diversão."

    prompt = f"""
    Você é um redator sênior especialista em jogos de tabuleiro com estilo de escrita moderno, direto e engajador, similar ao portal de notícias "The News".
    Escreva um resumo cativante sobre o jogo de tabuleiro "{game_name}".
    
    Instruções estritas:
    - O resumo deve focar no tema do jogo e em como funciona a sua proposta de gameplay/estratégia.
    - O resumo deve conter no máximo 2 parágrafos.
    - Linguagem: Português do Brasil (PT-BR).
    - Evite clichês exagerados. Seja informativo e empolgante.

    Informações de contexto adicionais coletadas: "{contextual_info}"
    """
    
    summary = call_gemini(prompt, response_json=False)
    if summary:
        return summary
        
    return f"Descubra a proposta de gameplay e o tema envolvente de {game_name}. Um título de destaque no cenário dos jogos de tabuleiro que promete desafiar suas estratégias."
