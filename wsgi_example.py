# ══════════════════════════════════════════════════════════════════════════
# ARQUIVO DE REFERÊNCIA — não é usado diretamente pelo projeto.
#
# No PythonAnywhere, a aba "Web" cria automaticamente um arquivo chamado
# algo como "/var/www/seuusuario_pythonanywhere_com_wsgi.py". Você precisa
# ABRIR esse arquivo (tem um link direto na aba Web) e SUBSTITUIR todo o
# conteúdo dele por algo parecido com o que está abaixo, trocando
# "seuusuario" pelo seu nome de usuário real do PythonAnywhere.
#
# Veja o passo a passo completo no README.md.
# ══════════════════════════════════════════════════════════════════════════

import sys
import os

# Caminho da pasta onde está o app.py (ajuste "seuusuario" para o seu usuário)
project_home = "/home/seuusuario/telegram_agendador"
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Carrega as variáveis do arquivo .env que está dentro dessa mesma pasta
from dotenv import load_dotenv
load_dotenv(os.path.join(project_home, ".env"))

# Importa o app Flask — o PythonAnywhere procura especificamente por uma
# variável chamada "application"
from app import app as application
