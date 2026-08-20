import os
import requests
import json
import time

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Controle preventivo de cota (Limites generosos do Groq, mas mantendo intervalo seguro de 1.5s)
_LAST_CALL_TIME = 0.0

_USE_AI_CHECKED = False
_USE_AI_VALUE = True


def _use_ai() -> bool:
    """
    Lê settings.use_ai do config.json. Default True (comportamento antigo)
    se a chave não existir, para não quebrar quem já usa o projeto.
    Quando False, get_api_key() retorna vazio direto — nenhuma chamada à
    Groq é feita (nem as 3 tentativas com backoff), e todas as funções
    deste módulo caem direto no fallback sem IA.
    """
    global _USE_AI_CHECKED, _USE_AI_VALUE
    if _USE_AI_CHECKED:
        return _USE_AI_VALUE
    _USE_AI_CHECKED = True
    try:
        if os.path.exists('config.json'):
            with open('config.json', 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                _USE_AI_VALUE = bool(cfg.get('settings', {}).get('use_ai', True))
    except Exception:
        _USE_AI_VALUE = True
    if not _USE_AI_VALUE:
        print("Groq: use_ai=false em config.json — geração por IA desabilitada, usando fallbacks.")
    return _USE_AI_VALUE


def get_api_key() -> str:
    """Obtém a API Key da Groq a partir das variáveis de ambiente.
    Retorna vazio (desligando a IA) se settings.use_ai=false no config.json.
    """
    if not _use_ai():
        return ""
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


def extract_game_name(title: str, content: str = "") -> str:
    """
    Usa o Llama 3 via Groq para extrair unicamente o nome limpo do jogo de tabuleiro
    principal mencionado no título ou conteúdo de um post de editora.
    """
    if not get_api_key():
        # Fallback simples: remove prefixo "Instagram: " e retorna o título
        cleaned = title
        if title.startswith("Instagram: "):
            cleaned = title[len("Instagram: "):]
        return cleaned.strip()

    prompt = f"""
    Você é um assistente especialista em jogos de tabuleiro.
    Dada uma publicação (título e/ou conteúdo) de uma editora, sua tarefa é identificar e extrair unicamente o nome do JOGO DE TABULEIRO principal que é o tema da notícia.

    Regras Estritas:
    - Retorne APENAS o nome limpo do jogo de tabuleiro, em formato texto puro, sem aspas, sem pontuações desnecessárias, sem nenhuma outra palavra.
    - Se a notícia mencionar uma expansão, retorne o nome do jogo base ou do jogo completo (ex: "Wingspan: Edição Ásia" ou "Wingspan").
    - Remova ruídos como "lançamento", "anuncia", "pré-venda", "chegou", "evento de", nomes de editoras (como Devir, Galápagos, Grok, Meeple BR, Paper Games) e quaisquer outras frases explicativas.
    - Se for impossível extrair um nome de jogo claro, retorne exatamente o título original.

    Exemplos:
    - Título: "Devir anuncia Unmatched: Sun's Origin para o segundo semestre" -> "Unmatched: Sun's Origin"
    - Título: "Galápagos lança nova expansão de Wingspan em pré-venda" -> "Wingspan"
    - Título: "Instagram: Chegou na Paper Games o incrível Project L!" -> "Project L"
    - Título: "Meeple BR anuncia a chegada de Everdell: Duo" -> "Everdell: Duo"

    Título: "{title}"
    Conteúdo: "{content}"
    """
    
    try:
        # Usamos call_groq sem formatação JSON, apenas texto puro, que é muito mais simples para extrações únicas de string
        res_text = call_groq(prompt, response_json=False)
        if res_text:
            cleaned_res = res_text.strip()
            # Se a resposta vier envolvida em aspas, remove
            if cleaned_res.startswith('"') and cleaned_res.endswith('"'):
                cleaned_res = cleaned_res[1:-1].strip()
            return cleaned_res
    except Exception as e:
        print(f"Erro ao extrair nome do jogo via Groq: {e}")
        
    cleaned = title
    if title.startswith("Instagram: "):
        cleaned = title[len("Instagram: "):]
    return cleaned.strip()


def generate_news_summary(title: str, content: str) -> str:
    """
    Gera um resumo de até 100 palavras de uma notícia do LudoNews.
    """
    if not get_api_key():
        return content[:300] if content else title

    prompt = f"""
    Você é um redator especialista em jogos de tabuleiro, estilo "The News" — direto, informativo e engajador.
    Escreva um resumo da notícia abaixo em Português do Brasil.

    Instruções estritas:
    - LIMITE ABSOLUTO: no máximo 100 palavras. Um único parágrafo.
    - Preserve os fatos principais: o que foi anunciado, qual jogo, qual editora.
    - Não invente informações que não estejam no conteúdo fornecido.
    - Não use clichês como "incrível", "imperdível", "revolucionário".

    Título: "{title}"
    Conteúdo: "{content}"
    """

    result = call_groq(prompt, response_json=False)
    return result if result else (content[:300] if content else title)


def generate_crowdfunding_summary(project_name: str, description: str,
                                   platform: str, end_date: str) -> str:
    """
    Gera um resumo de até 100 palavras de um projeto de financiamento coletivo.
    """
    if not get_api_key():
        return description[:300] if description else project_name

    prompt = f"""
    Você é um redator especialista em jogos de tabuleiro, estilo "The News" — direto e objetivo.
    Um projeto de financiamento coletivo de jogo de tabuleiro foi lançado na plataforma {platform}.
    Escreva um resumo em Português do Brasil explicando o que é o projeto e por que vale a pena apoiar.

    Instruções estritas:
    - LIMITE ABSOLUTO: no máximo 100 palavras. Um único parágrafo.
    - Mencione a data de encerramento da campanha: {end_date}.
    - Baseie-se apenas nas informações fornecidas. Não invente detalhes.
    - Não use termos como "incrível", "imperdível", "revolucionário".

    Nome do projeto: "{project_name}"
    Descrição disponível: "{description}"
    """

    result = call_groq(prompt, response_json=False)
    return result if result else (description[:300] if description else project_name)


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
    - LIMITE ABSOLUTO: no máximo 100 palavras. Seja conciso e direto.
    - NÃO use mais de 1 parágrafo.
    - Linguagem: Português do Brasil (PT-BR).
    - Evite clichês exagerados. Seja informativo e empolgante.

    Informações de contexto adicionais coletadas: "{contextual_info}"
    """
    
    summary = call_groq(prompt, response_json=False)
    if summary:
        return summary
        
    return f"Descubra a proposta de gameplay e o tema envolvente de {game_name}. Um título de destaque no cenário dos jogos de tabuleiro que promete desafiar suas estratégias."


# Palavras-chave usadas como fallback quando a Groq estiver indisponível.
# Propositalmente restritas a sinais fortes de jogo DIGITAL/videogame —
# RPG de mesa, card game e livro de regras NÃO entram aqui, pois fazem
# parte do escopo aceito da categoria "Jogos" do Catarse.
_DIGITAL_GAME_NEGATIVE_KEYWORDS = [
    'videogame', 'video game', 'jogo digital', 'jogo eletrônico',
    'steam', 'playstation', 'xbox', 'nintendo switch', 'mobile game',
    'app gratuito', 'app mobile', 'pc gamer', 'console', 'demo gameplay',
    'unreal engine', 'unity engine', 'indie game digital',
    'play store', 'google play', 'app store', 'android', 'ios',
    'aplicativo mobile', 'jogue no celular', 'jogo para celular',
    'disponível na loja', 'baixe o app', 'baixar o jogo',
]


def is_board_game_project(name: str, description: str = "") -> bool:
    """
    Classifica um projeto do Catarse como jogo de tabuleiro/RPG físico (True)
    ou jogo digital/videogame (False), para excluir apenas itens digitais
    dos resultados do Catarse (que mistura tabuleiro e digital na categoria
    "Jogos"). RPG de mesa e card games são considerados válidos (True).

    Em caso de falha da API ou resposta ambígua, o fallback é permissivo
    (assume jogo de tabuleiro válido) para evitar excluir projetos legítimos
    por excesso de cautela — só exclui quando há sinal claro de "digital".
    """
    text_lower = f"{name} {description}".lower()

    if not get_api_key():
        # Fallback por palavras-chave negativas quando a IA não está disponível.
        is_digital = any(kw in text_lower for kw in _DIGITAL_GAME_NEGATIVE_KEYWORDS)
        return not is_digital

    prompt = f"""
    Você é um classificador especialista em financiamento coletivo de jogos.
    Analise o projeto abaixo, do Catarse, e decida se ele é um JOGO DE TABULEIRO
    (ou RPG de mesa, card game físico, livro de regras impresso) ou um JOGO DIGITAL
    (videogame, app, jogo para PC/console/celular).

    Regras:
    - RPG de mesa, card game físico e livros de regras impressos contam como
      "jogo de tabuleiro" (board_game = true).
    - Apenas jogos eletrônicos/digitais (videogame, app, software jogável em
      tela) contam como "jogo digital" (board_game = false).
    - Em caso de dúvida real (informação insuficiente), responda board_game = true.

    Nome do projeto: "{name}"
    Descrição disponível: "{description}"

    Responda APENAS um objeto JSON válido no formato:
    {{
      "board_game": true ou false
    }}
    """

    try:
        res_text = call_groq(prompt, response_json=True)
        if res_text:
            data = json.loads(res_text)
            return bool(data.get("board_game", True))
    except Exception as e:
        print(f"Erro ao classificar projeto '{name}' via Groq: {e}")

    # Fallback final: permissivo, igual ao caminho sem API key.
    is_digital = any(kw in text_lower for kw in _DIGITAL_GAME_NEGATIVE_KEYWORDS)
    return not is_digital
