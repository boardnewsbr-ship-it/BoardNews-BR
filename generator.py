import os
import requests
import json
import time

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Controle preventivo de cota (Limites generosos do Groq, mas mantendo intervalo seguro de 1.5s)
_LAST_CALL_TIME = 0.0

def get_api_key() -> str:
    """Obtém a API Key da Groq a partir das variáveis de ambiente."""
    return os.environ.get("GROQ_API_KEY", "")

def call_groq(prompt: str, response_json: bool = False) -> str:
    """
    Realiza uma chamada direta via HTTP para a API do Groq (Llama 3.3 70B)
    com rate limiting preventivo e tratamento de erros 429 (excesso de cota) com retentativas e backoff.
    """
    global _LAST_CALL_TIME
    
    api_key = get_api_key()
    if not api_key:
        print("AVISO: GROQ_API_KEY não configurada. Usando fallback básico.")
        return None
        
    # Rate limit preventivo sutil: garante pelo menos 1.5 segundos da última chamada
    current_time = time.time()
    elapsed = current_time - _LAST_CALL_TIME
    if elapsed < 1.5:
        sleep_time = 1.5 - elapsed
        time.sleep(sleep_time)
        
    url = GROQ_API_URL
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.2
    }
    
    if response_json:
        payload["response_format"] = {"type": "json_object"}
        
    max_retries = 3
    retry_delay = 5.0  # Aguarda 5 segundos iniciais em caso de 429 na Groq
    
    for attempt in range(1, max_retries + 1):
        _LAST_CALL_TIME = time.time()
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=25)
            
            if response.status_code == 200:
                res_data = response.json()
                text = res_data['choices'][0]['message']['content']
                return text.strip()
                
            elif response.status_code == 429:
                print(f"⚠️ [Tentativa {attempt}/{max_retries}] Cota do Groq excedida (Erro 429). Aguardando {retry_delay}s antes de tentar novamente...")
                time.sleep(retry_delay)
                retry_delay *= 2.0  # Aumenta o tempo de espera de forma progressiva
                continue
                
            else:
                print(f"Erro na API do Groq: {response.status_code} - {response.text}")
                break
                
        except Exception as e:
            print(f"Erro ao chamar o Groq (Tentativa {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                time.sleep(2)
                
    return None

def filter_publisher_post(title: str, content: str) -> bool:
    """Filtro menos restritivo: aceita todos os posts.
    Mantém a verificação de API key apenas para compatibilidade; se houver chave,
    ainda tenta a chamada Groq, mas caso falhe ou não exista, aceita o post.
    """
    if not get_api_key():
        # Sem API key: aceita tudo
        return True
    # Tenta usar a API do Groq, mas se falhar aceita o post
    prompt = f"""
    Você é um assistente especialista em jogos de tabuleiro (board games) e atua na curadoria do canal "BoardNews BR".
    Analise o título e o conteúdo do post de uma editora (que pode ser do blog oficial ou da rede social Instagram) e classifique se ele é de valor:
       
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
    
    res_text = call_groq(prompt, response_json=True)
    if res_text:
        try:
            data = json.loads(res_text)
            return bool(data.get("is_announcement", False))
        except Exception as e:
            print(f"Erro ao parsear resposta de filtragem do Groq: {e}. Texto original: {res_text}")
            
    # Se a chamada à API do Groq falhar ou retornar erro de cota (429), aplica o fallback local baseado em palavras-chaves
    keywords = ["lançamento", "anúncio", "chegou", "pré-venda", "novidade", "revelado", "vem aí", "unmatched", "puerto rico", "evento", "torneio", "campeonato", "encontro"]
    title_lower = title.lower()
    return any(k in title_lower for k in keywords)


def translate_game_name(game_name: str) -> str:
    """
    Usa o Llama 3 via Groq para traduzir ou encontrar o nome original em inglês de um jogo de tabuleiro brasileiro
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
        res_text = call_groq(prompt, response_json=True)
        if res_text:
            data = json.loads(res_text)
            english_name = data.get("english_name", game_name)
            if english_name:
                return english_name.strip()
    except Exception as e:
        print(f"Erro ao traduzir nome do jogo '{game_name}' via Groq: {e}")
        
    return game_name


def generate_summary(game_name: str, contextual_info: str = "") -> str:
    """
    Gera um resumo atraente de gameplay de no máximo 2 parágrafos usando o Groq.
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
    
    summary = call_groq(prompt, response_json=False)
    if summary:
        return summary
        
    return f"Descubra a proposta de gameplay e o tema envolvente de {game_name}. Um título de destaque no cenário dos jogos de tabuleiro que promete desafiar suas estratégias."
