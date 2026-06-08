from flask import Flask, render_template, request, redirect, url_for
# Removi o SQLAlchemy pois agora usamos o supabase-py
from datetime import datetime
import os
from werkzeug.utils import secure_filename
# Importando o cliente do Supabase
from supabase import create_client
from flask import session
from werkzeug.security import generate_password_hash, check_password_hash
import io
import time
from PIL import Image


app = Flask(__name__)

app.secret_key = "uma_chave_muito_segura_aqui"

# --- CONFIGURAÇÃO DO SUPABASE E UPLOADS ---
# Coloque aqui as suas credenciais que usamos nos testes
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def salvar_na_nuvem(arquivo, pasta):
    if not arquivo or arquivo.filename == '':
        return "sem-foto.jpg"

    # 1. Cria um nome único (ex: 171554321.jpg)
    ext = os.path.splitext(arquivo.filename)[1].lower()
    nome_arquivo = f"{int(time.time())}{ext}"
    caminho_no_storage = f"{pasta}/{nome_arquivo}"

    # 2. Redimensiona a foto (Lanche não precisa ser 4K, 600px é o ideal)
    img = Image.open(arquivo)
    if img.mode in ("RGBA", "P"): img = img.convert("RGB")
    img.thumbnail((600, 600), Image.Resampling.LANCZOS)
    
    # 3. Transforma em "bits" para o Supabase entender
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", optimize=True, quality=80)
    buffer.seek(0)

    try:
        # 4. Manda para o Bucket 'food_online' que você criou no painel
        supabase.storage.from_("food_online").upload(
            path=caminho_no_storage,
            file=buffer.read(),
            file_options={"content-type": "image/jpeg"}
        )
        return nome_arquivo
    except Exception as e:
        print(f"Erro ao subir para nuvem: {e}")
        return "sem-foto.jpg"

# --- ROTAS ---

@app.route('/')
def index():
    # 1. Busca no Supabase estritamente os parceiros aprovados por você no Admin
    resposta = supabase.table("categorias").select("*").eq("aprovado", True).execute()
    lojas_aprovadas = resposta.data if resposta.data else []
    
    return render_template('tela_inicial.html', parceiros=lojas_aprovadas, lojas=lojas_aprovadas)

@app.route('/vitrine')
def vitrine():
    try:
        # 1. Buscamos do banco apenas os parceiros aprovados
        resposta = supabase.table("categorias").select("*").eq("aprovado", True).execute()
        lojas_aprovadas = resposta.data if resposta.data else []
        
        # 🛠️ TRATAMENTO INTELIGENTE: Garante que o HTML receba o nome da foto terminando em .jpg
        for loja in lojas_aprovadas:
            if loja.get('foto_perfil'):
                # Se o nome gravado no banco terminar com .png, .jpeg ou webp, o Python troca para .jpg na memória
                nome_atual = loja['foto_perfil']
                if nome_atual != "sem-foto.jpg":
                    # Remove a extensão antiga e força o .jpg
                    nome_sem_ext = os.path.splitext(nome_atual)[0]
                    loja['foto_perfil'] = f"{nome_sem_ext}.jpg"
        
        # 2. PRINT DE TESTE: Vamos ver no terminal se os nomes agora estão todos padronizados em .jpg
        print("🔍 LOJAS ENVIADAS PARA O HTML (SÓ JPG):", lojas_aprovadas)
        
        # 3. Enviamos para o HTML
        return render_template('vitrine.html', parceiros=lojas_aprovadas, lojas=lojas_aprovadas)
        
    except Exception as e:
        # Se der erro no Supabase, ele avisa no terminal do VS Code
        print(f"🚨 ERRO NA ROTA VITRINE: {e}")
        return f"Erro ao carregar os dados da vitrine: {e}"

#-----------------------------------------------------------------------------------------------
# Mudei o endereço para uma URL secreta que só você sabe e vai enviar no WhatsApp do parceiro
@app.route('/parceiro', methods=['GET', 'POST'])
def login():
    # SEGUNDA TRAVA: Se o lojista já estiver logado e tentar abrir esse link de novo,
    # ele não vê a tela de login, o Python joga ele direto para o painel dele.
    if 'lanchonete_id' in session:
        return redirect(url_for('cadastrar_item', lanchonete_id=session['lanchonete_id']))

    if request.method == 'POST':
        email = request.form.get('email')
        senha_digitada = request.form.get('senha')

        # 1. Busca o usuário apenas pelo e-mail (Sua lógica original)
        resposta = supabase.table("categorias").select("*").eq("email", email).execute()

        if resposta.data:
            usuario = resposta.data[0]
            
            # --- PROTEÇÃO EXTRA NO LOGIN ---
            # Se o usuário tentar logar mas ainda não foi aprovado por você no Admin, barra ele!
            if not usuario.get('aprovado', False):
                return "Sua conta está aguardando aprovação administrativa!"

            # 2. Compara a senha digitada com o hash (Sua lógica original)
            if check_password_hash(usuario['senha'], senha_digitada):
                session['lanchonete_id'] = usuario['id']
                session['nome_loja'] = usuario['nome']
                return redirect(url_for('cadastrar_item', lanchonete_id=usuario['id']))
        
        return "E-mail ou senha incorretos!"

    return render_template('login.html')


# --- 1. BLOCO DE LOGOUT ---
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# --- 2. EXIBIR FORMULÁRIO DE CADASTRO (DE VOLTA AO NORMAL) ---
# Agora qualquer pessoa que acessar /cadastro vai direto para a tela do formulário
@app.route('/cadastro')
def exibir_formulario():
    return render_template('cadastro_parceiro.html')


# --- 3. BARREIRA DE PROTEÇÃO (APENAS PARA O LOGIN) ---
# Mantemos apenas o /login bloqueado para os clientes curiosos
@app.route('/login')
def bloquear_cliente_curioso():
    return redirect('/')

# =========================================================================
# ROTA DE CADASTRO ATUALIZADA (BLOQUEANDO LOGIN AUTOMÁTICO ANTES DA HORA)
# =========================================================================
@app.route('/cadastrar_parceiro', methods=['POST'])
def cadastrar_parceiro():
    nome_loja = request.form.get('nome')
    whats_loja = request.form.get('whatsapp')
    cat_loja = request.form.get('categoria') # Guardado caso use em outra tabela depois
    desc_loja = request.form.get('descricao')
    email_loja = request.form.get('email')
    senha_loja = request.form.get('senha')
    cor_tema = request.form.get('cor_tema')
    cidade_loja = request.form.get('cidade') # Capturando a cidade do select
    
    if not senha_loja or len(senha_loja) < 8:
        return "Erro: A senha deve ter no mínimo 8 dígitos!", 400
    
    senha_com_hash = generate_password_hash(senha_loja)
    
    arquivo = request.files.get('foto_perfil')
    nome_da_foto = "sem-foto.jpg"

    if arquivo and arquivo.filename != '':
        # 🛠️ Forçamos o nome do arquivo a terminar sempre com .jpg para combinar com a vitrine
        nome_da_foto = f"perfil_{int(time.time())}.jpg"
        
        img = Image.open(arquivo)
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail((600, 600), Image.Resampling.LANCZOS)
        
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", optimize=True, quality=85)
        buffer.seek(0)

        try:
            # 🛠️ CORRIGIDO: Enviando para o seu bucket real 'comida_online' para não dar erro de rota
            supabase.storage.from_("food_online").upload(
                path=f"perfis/{nome_da_foto}",
                file=buffer.read(),
                file_options={"content-type": "image/jpeg"}
            )
        except Exception as e:
            print(f"Erro ao subir foto: {e}")
            nome_da_foto = "sem-foto.jpg"

    # 2. Montando o dicionário ajustado com a coluna oficial do seu banco ('foto_perfil')
    dados_lanchonete = {
        "nome": nome_loja,
        "whatsapp_numero": whats_loja, 
        "email": email_loja,
        "senha": senha_com_hash,
        "slug": nome_loja.lower().replace(" ", "-") if nome_loja else "",
        "descricao": desc_loja,
        "foto_perfil": nome_da_foto,        # 🛠️ MANTIDO: Ajustado para bater com a sua coluna oficial 'foto_perfil'
        "status_online": False,
        "cor_tema": cor_tema if cor_tema else "#EA1D2C",
        "cidade": cidade_loja,      
        "aprovado": False          
    }

    # 3. Salvando no banco com a estrutura original limpa
    try:
        supabase.table("categorias").insert(dados_lanchonete).execute()
        return redirect(url_for('cadastro_recebido'))
    except Exception as e:
        print(f"🚨 ERRO AO INSERIR NO SUPABASE: {e}")
        return f"Erro ao salvar cadastro. Erro: {e}"


@app.route('/cadastro-recebido')
def cadastro_recebido():
    return render_template('aguardando_aprovacao.html')
#------------------------------------------------------------------------------------------
@app.route('/cadastrar_item/<int:lanchonete_id>', methods=['GET', 'POST'])
def cadastrar_item(lanchonete_id):
    # SEGURANÇA: Mantido exatamente como o seu original
    if 'lanchonete_id' not in session or session['lanchonete_id'] != lanchonete_id:
        return redirect(url_for('login'))
        
    if request.method == 'POST':
        nome = request.form.get('nome_item')
        preco = request.form.get('preco')
        desc = request.form.get('descricao')
        
        # --- TRATAMENTO DO PREÇO COM VÍRGULA ---
        # Garante que valores digitados como "15,50" virem "15.50" antes do conversion para float
        preco_limpo = preco.replace(',', '.') if preco else "0.00"
        
        # --- LÓGICA DE SALVAMENTO NA NUVEM (MANTIDA) ---
        arquivo = request.files.get('foto_item')
        nome_da_foto = "sem-foto.jpg" # Padrão caso não envie foto

        if arquivo and arquivo.filename != '':
            # 1. Geramos um nome único para o lanche
            ext = os.path.splitext(arquivo.filename)[1].lower()
            nome_da_foto = f"item_{int(time.time())}{ext}"
            
            # 2. Processamos a imagem para não pesar no celular do cliente
            img = Image.open(arquivo)
            if img.mode in ("RGBA", "P"): img = img.convert("RGB")
            img.thumbnail((600, 600), Image.Resampling.LANCZOS)
            
            # 3. Transformamos em bytes para o Supabase
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", optimize=True, quality=85)
            buffer.seek(0)

            # 4. Enviamos para a pasta 'itens' dentro do bucket 'food_online'
            try:
                supabase.storage.from_("food_online").upload(
                    path=f"itens/{nome_da_foto}",
                    file=buffer.read(),
                    file_options={"content-type": "image/jpeg"}
                )
            except Exception as e:
                print(f"Erro ao subir foto do item: {e}")
                nome_da_foto = "sem-foto.jpg"

        # Novo item para a tabela item_cardapio (Sem a coluna cor_tema para evitar erros)
        novo_item = {
            "nome_item": nome,
            "preco": float(preco_limpo), # Converte o preço já tratado com ponto
            "descricao_item": desc,
            "imagem_url": nome_da_foto, # Salva o nome da foto na nuvem
            "lanchonete_id": lanchonete_id,
        }
        supabase.table("item_cardapio").insert(novo_item).execute()
        
        return redirect(url_for('cadastrar_item', lanchonete_id=lanchonete_id, msg="Item adicionado!"))

    # Buscando a loja na tabela 'categorias' e os itens dela no Supabase
    loja = supabase.table("categorias").select("*").eq("id", lanchonete_id).single().execute().data
    itens_da_loja = supabase.table("item_cardapio").select("*").eq("lanchonete_id", lanchonete_id).execute().data
    
    return render_template('cadastro_item.html', loja=loja, itens=itens_da_loja)

    # --- PARTE GET: Buscando dados para exibir na tela (Mantido original) ---
    loja = supabase.table("categorias").select("*").eq("id", lanchonete_id).single().execute().data
    itens_da_loja = supabase.table("item_cardapio").select("*").eq("lanchonete_id", lanchonete_id).execute().data
    
    return render_template('cadastro_item.html', loja=loja, itens=itens_da_loja)

@app.route('/cardapio/<int:id>')
def cardapio(id):
    # Buscando dados na tabela 'categorias' para exibir no cardapio.html
    loja_selecionada = supabase.table("categorias").select("*").eq("id", id).single().execute().data
    itens = supabase.table("item_cardapio").select("*").eq("lanchonete_id", id).execute().data
    
    # Mantendo o retorno igual ao que seu template espera
    return render_template('cardapio.html', lanchonete=loja_selecionada, itens=itens)

@app.route('/excluir_item/<int:item_id>')
def excluir_item(item_id):
    # Buscando o ID da loja antes de excluir para poder redirecionar
    item = supabase.table("item_cardapio").select("lanchonete_id").eq("id", item_id).single().execute().data
    id_loja = item['lanchonete_id']
    
    # Comando de exclusão
    supabase.table("item_cardapio").delete().eq("id", item_id).execute()
    
    return redirect(url_for('cadastrar_item', lanchonete_id=id_loja, msg="Item removido com sucesso!"))

@app.route('/editar_item/<int:item_id>', methods=['POST'])
def editar_item(item_id):
    # 1. Pegamos os dados do form (Exatamente como você fez)
    nome_item = request.form.get('nome_item')
    preco = float(request.form.get('preco'))
    descricao = request.form.get('descricao')
    
    dados_atualizados = {
        "nome_item": nome_item,
        "preco": preco,
        "descricao_item": descricao
    }
    
    arquivo = request.files.get('foto_item')
    
    # 2. Se o usuário enviou uma foto nova, mandamos para o Supabase
    if arquivo and arquivo.filename != '':
        # Geramos um nome único para evitar conflitos na nuvem
        ext = os.path.splitext(arquivo.filename)[1].lower()
        nome_da_foto = f"item_edit_{int(time.time())}{ext}"
        
        # Processando com PIL para a imagem ficar leve
        img = Image.open(arquivo)
        if img.mode in ("RGBA", "P"): img = img.convert("RGB")
        img.thumbnail((600, 600), Image.Resampling.LANCZOS)
        
        # Convertendo para bytes para o Supabase Storage
        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", optimize=True, quality=85)
        buffer.seek(0)

        # Enviando para a pasta 'itens' dentro do seu bucket 'food_online'
        try:
            supabase.storage.from_("food_online").upload(
                path=f"itens/{nome_da_foto}",
                file=buffer.read(),
                file_options={"content-type": "image/jpeg"}
            )
            # Se deu certo, colocamos o novo nome no dicionário de atualização
            dados_atualizados["imagem_url"] = nome_da_foto
        except Exception as e:
            print(f"Erro ao atualizar foto na nuvem: {e}")

    # 3. Faz o UPDATE no Supabase (Mantendo sua lógica original)
    resultado = supabase.table("item_cardapio").update(dados_atualizados).eq("id", item_id).execute()
    
    # Buscamos o ID da loja para o redirecionamento (Como você definiu)
    id_loja = resultado.data[0]['lanchonete_id']

    return redirect(url_for('cadastrar_item', lanchonete_id=id_loja, msg="Item atualizado!"))

if __name__ == '__main__':
    app.run(debug=True)
