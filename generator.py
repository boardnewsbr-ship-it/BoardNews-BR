import os
import requests
import json
import time

GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"

# Controle preventivo de cota (15 RPM do Gemini Free Tier)
# Garante que as requisições tenham um intervalo seguro de pelo menos 4.5 segundos entre si.
_LAST_CALL_TIME = 0.0

def get_api_key() -> str:
    """Obtém a API Key do Gemini a partir das variáveis de ambiente."""
    return os.environ.get("GEMINI_API_KEY", "")

def call_gemini(prompt: str, response_json: bool = False) -> str:
    """
    Realiza uma chamada direta via HTTP para a API do Gemini (2.5-flash)
    com rate limiting preventivo e tratamento de erros 429 (excesso de cota) com retentativas e backoff.
    """
    global _LAST_CALL_TIME
    
    api_key = get_api_key()
    if not api_key:
        print("AVISO: GEMINI_API_KEY não configurada. Usando fallback básico.")
        return None
        
    # Rate limit preventivo: garante que decorreu pelo menos 4.5 segundos da última chamada
    current_time = time.time()
    elapsed = current_time - _LAST_CALL_TIME
    if elapsed < 4.5:
        sleep_time = 4.5 - elapsed
        time.sleep(sleep_time)
        
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
        
    max_retries = 3
    retry_delay = 20.0  # Aguarda 20 segundos iniciais em caso de 429
    
    for attempt in range(1, max_retries + 1):
        _LAST_CALL_TIME = time.time()
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=25)
            
            if response.status_code == 200:
                res_data = response.json()
                text = res_data['candidates'][0]['content']['parts'][0]['text']
                return text.strip()
                
            elif response.status_code == 429:
                print(f"⚠️ [Tentativa {attempt}/{max_retries}] Cota do Gemini excedida (Erro 429). Aguardando {retry_delay}s antes de tentar novamente...")
                time.sleep(retry_delay)
                retry_delay *= 1.5  # Aumenta o tempo de espera de forma progressiva
                continue
                
            else:
                print(f"Erro na API do Gemini: {response.status_code} - {response.text}")
                break
                
        except Exception as e:
            print(f"Erro ao chamar o Gemini (Tentativa {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(5)
                
    return None

def filter_publisher_post(title: str, content: str) -> bool:
    """
    Usa o Gemini para filtrar posts das editoras (blogs ou Instagram).
    Retorna True se for um anúncio/novidade de lançamento de jogo, expansão, pré-venda ou evento oficial de jogos.
    Retorna False para posts sociais genéricos, institucionais vazios, memes, etc.
    """
    if not get_api_key():
        # Fallback se não houver API key: busca termos chaves no título
        keywords = ["lançamento", "anúncio", "chegou", "pré-venda", "novidade", "revelado", "vem aí", "evento", "torneio", "campeonato", "encontro"]
        title_lower = title.lower()
        return any(k in title_lower for k in keywords)

    prompt = f"""
    Você é um assistente especialista em jogos de tabuleiro (board games) e atua na curadoria do canal "BoardNews BR".
    Analise o título e o conteúdo do post de uma editora (que pode ser do blog oficial ou da rede social Instagram) e classifique se ele é de valor:
    
    1. APROVE APENAS se o post for sobre:
       - Um anúncio de lançamento futuro de jogo ou expansão.
       - Abertura de pré-vendas ou a chegada física de um jogo/expansão às lojas brasileiras.
       - Novidades/teasers de novos títulos que estão sendo localizados.
       - Eventos oficiais de jogos de tabuleiro organizados pela editora (ex: torneios de jogos específicos, campeonatos nacionais/locais, encontros públicos de jogatina com demonstrações, palestras e feiras presenciais).
       
    2. REJEITE imediatamente se for sobre:
       - Posts sociais genéricos, mensagens de "bom dia", datas comemorativas sem relação com jogos.
       - Fotos de bastidores da empresa, memes, piadas, enquetes sem valor noticioso.
       - Avisos burocráticos (ex: recesso de feriado, aviso de envio atrasado, vagas de emprego).
       - Posts institucionais corporativos ou fotos de reuniões da empresa.

    Retorne APENAS um objeto JSON no formato exato:
    {{
      "is_announcement": true ou false,
      "reason": "uma frase curta explicando o motivo da aprovação ou rejeição"
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
            
    # Se a chamada à API do Gemini falhar ou retornar erro de cota (429), aplica o fallback local baseado em palavras-chaves
    keywords = ["lançamento", "anúncio", "chegou", "pré-venda", "novidade", "revelado", "vem aí", "unmatched", "puerto rico", "evento", "torneio", "campeonato", "encontro"]
    title_lower = title.lower()
    return any(k in title_lower for k in keywords)


def translate_game_name(game_name: str) -> str:
    """
    Usa o Gemini para traduzir ou encontrar o nome original em inglês de um jogo de tabuleiro brasileiro
    a fim de facilitar a busca na API do BoardGameGeek (BGG).
    """
    if not get_api_key():
        return game_name
        
    prompt = f"""
    Você é um assistente especialista em jogos de tabuleiro.
    Muitos jogos de tabuleiro são lançados no Brasil com nomes traduzidos para o português ou adaptados.
    Eu preciso saber o nome original em inglês (ou o nome padrão global cadastrado no site BoardGameGeek - BGG) para o seguinte jogo: "{game_name}".

    Exemplos de conversões corretas:
    - "Finspan: Tubarões e Recifes" -> "Finspan: Sharks & Reefs"
    - "Everdell: Duo" -> "Everdell Duo"
    - "O Senhor dos Anéis: Confronto" -> "The Lord of the Rings: The Confrontation"
    - "Project L" -> "Project L"
    - "Asas em Voo" -> "Wingspan"

    Por favor, retorne APENAS um objeto JSON válido no seguinte formato:
    {{
      "english_name": "Nome original do jogo em inglês ou no BGG"
    }}
    """
    
    try:
        res_text = call_gemini(prompt, response_json=True)
        if res_text:
            data = json.loads(res_text)
            english_name = data.get("english_name", game_name)
            if english_name:
                return english_name.strip()
    except Exception as e:
        print(f"Erro ao traduzir nome do jogo '{game_name}' via Gemini: {e}")
        
    return game_name


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
