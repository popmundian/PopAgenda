# 🤖 Agendador de Mensagens Telegram — 100% grátis, com GitHub + PythonAnywhere

Esta versão não usa servidor pago nem Docker. O código fica no **GitHub**
(controle de versão), a aplicação roda de graça no **PythonAnywhere**, e um
robozinho do **GitHub Actions** dispara a checagem diária — tudo sem custo.

---

## Por que essa combinação (e não outra)

Pesquisei as opções atuais antes de recomendar. Resumo:

| Opção | Problema para este projeto |
|---|---|
| Render (free) | Banco de dados grátis expira em 30 dias — inviável para ciclos de 56+ dias |
| Railway / Fly.io | Não são mais realmente grátis para uso contínuo |
| Oracle Cloud (VPS grátis) | Aprovação de conta instável, alguns relatos de contas encerradas sem aviso |
| **PythonAnywhere + GitHub Actions** | ✅ Hospedagem que não "dorme", disco persistente de verdade, `api.telegram.org` já liberado, e o GitHub Actions supre a única peça que faltava (agendamento automático) — tudo grátis |

---

## 🆕 Atualização v3 — usuários com permissões, contatos e teste de envio

Se seu app já está no ar (PythonAnywhere), essa atualização é **não-destrutiva**:
seus agendamentos atuais continuam intactos. O que muda:

- **Múltiplos usuários com dois papéis**: `admin` e `user`
- **Sua conta atual (WEB_USER/WEB_PASS do .env) vira automaticamente o primeiro admin** na primeira vez que o app reiniciar com o código novo — você não perde acesso
- **Contatos**: cadastre nomes amigáveis para Chat IDs (ex: "Notificações PPM" em vez de decorar `5402433549`)
- **Botão de teste**: envia a mensagem agora mesmo, marcada como `🧪 [TESTE]`, exige sua senha antes de enviar

### Tabela de permissões

| Ação | Usuário comum | Admin |
|---|---|---|
| Criar / editar agendamento | ✅ | ✅ |
| Pausar / ativar agendamento | ✅ | ✅ |
| Enviar teste (com senha) | ✅ | ✅ |
| Cadastrar contatos | ✅ | ✅ |
| **Apagar agendamento** | ❌ | ✅ |
| Gerenciar usuários | ❌ | ✅ |

### Como aplicar essa atualização no que já está no ar

1. Suba os arquivos atualizados no seu repositório GitHub (upload manual, ou
   `git add . && git commit -m "v3" && git push` se estiver usando Git local)
2. No console Bash do PythonAnywhere:
   ```bash
   cd PopAgenda
   git pull
   ```
   (Não precisa `pip install` de novo — nenhuma dependência nova foi adicionada)
3. Aba **Web** → botão **Reload**
4. Pronto — faça login normalmente com seu usuário/senha de sempre. Ele agora é o admin.

### Criando outros usuários

Como admin, vá em **Usuários** no menu lateral → preencha nome, senha (mínimo
6 caracteres) e escolha o papel. Cada colaborador loga com sua própria conta.

---

## O que mudou por baixo do capô (versão GitHub + PythonAnywhere)

- O bot agora usa **webhook** em vez de "polling": o Telegram chama seu app
  diretamente quando alguém manda `/chatid` ou `/status`, em vez do app ficar
  perguntando "tem mensagem nova?" o tempo todo (isso exigiria um processo
  contínuo em segundo plano, que o plano grátis não permite).
- A checagem diária de "preciso enviar algo hoje?" virou uma rota protegida
  por senha (`/cron/check-and-send`), chamada de fora pelo GitHub Actions —
  em vez de rodar sozinha dentro do processo.
- Rodar essa checagem várias vezes por dia **não duplica envios** (testei
  isso especificamente) — por isso o robô do GitHub roda 3x/dia, como
  segurança contra os atrasos ocasionais do agendador do GitHub.

O painel web (criar/editar/pausar agendamentos) é **idêntico** a antes.

---

## ✅ O que você precisa ter em mãos

- Uma conta no GitHub (você já tem)
- Uma conta no Telegram
- 15-20 minutos

Nenhum cartão de crédito, nenhum servidor próprio, nenhum terminal SSH.

---

## FASE 1 — Criar o repositório no GitHub

1. Acesse [github.com/new](https://github.com/new)
2. Nome sugerido: `telegram-agendador`
3. Pode ser **privado** (recomendado) ou público — os dois funcionam
4. **Não** marque "Add a README" (vamos subir o nosso)
5. Clique em **Create repository**

### Enviar os arquivos para o repositório

Na página do repositório recém-criado, clique em **uploading an existing
file** (ou "Add file → Upload files"), e arraste **todos os arquivos e
pastas** do ZIP que você baixou desta conversa (extraia o ZIP no seu
computador primeiro). Confirme o envio ("Commit changes").

> ⚠️ Confira que a pasta `.github/workflows/` foi enviada junto — alguns
> navegadores escondem pastas que começam com ponto ao arrastar. Se não
> aparecer, crie o arquivo manualmente pelo GitHub: **Add file → Create new
> file**, digite o caminho `.github/workflows/daily-check.yml` (o próprio
> GitHub cria as pastas) e cole o conteúdo do arquivo.

---

## FASE 2 — Criar o bot no Telegram

1. No Telegram, fale com **@BotFather** → `/newbot` → escolha nome e username
2. Copie o **token** (ex: `123456789:AABBCCDDEEFFaabbccddeeff`)
3. `/mybots` → seu bot → **Bot Settings → Group Privacy → Turn off**
4. Adicione o bot ao seu grupo

---

## FASE 3 — Criar a conta no PythonAnywhere

1. Acesse [pythonanywhere.com](https://www.pythonanywhere.com) → **Pricing & signup → Create a Beginner account** (grátis)
2. Confirme o e-mail

### Subir o código

1. No painel do PythonAnywhere, abra a aba **Consoles → Bash**
2. Rode:
   ```bash
   git clone https://github.com/SEU_USUARIO/telegram-agendador.git
   cd telegram-agendador
   ```
   Se o repositório for **privado**, o Git vai pedir usuário/senha — use um
   [Personal Access Token](https://github.com/settings/tokens) do GitHub no
   lugar da senha (o GitHub não aceita mais senha comum para isso).
3. Crie o ambiente e instale as dependências:
   ```bash
   mkvirtualenv --python=/usr/bin/python3.12 venv-agendador
   pip install -r requirements.txt
   ```
   > Se `mkvirtualenv` não for reconhecido, rode antes: `source virtualenvwrapper.sh`

### Criar o arquivo .env

Ainda no console Bash:
```bash
cp .env.example .env
nano .env
```
Preencha `TELEGRAM_TOKEN`, `WEB_USER`, `WEB_PASS`. Para `SECRET_KEY`,
`CRON_SECRET` e `WEBHOOK_SECRET`, gere três valores diferentes com:
```bash
python3 -c "import secrets; print(secrets.token_hex(24))"
```
(rode três vezes, uma para cada campo). Salvar no nano: `Ctrl+O` → Enter → `Ctrl+X`.

### Criar a aplicação web

1. Aba **Web** → **Add a new web app** → **Manual configuration** → **Python 3.12**
2. Na seção **Virtualenv**, informe o caminho do ambiente que você criou:
   `/home/SEU_USUARIO/.virtualenvs/venv-agendador`
3. Na seção **Code**, clique no link do arquivo WSGI (algo como
   `/var/www/seuusuario_pythonanywhere_com_wsgi.py`) e **substitua todo o
   conteúdo** pelo modelo do arquivo `wsgi_example.py` do projeto — troque
   `seuusuario` pelo seu usuário real do PythonAnywhere nos dois lugares
4. Clique no botão verde **Reload** no topo da aba Web
5. Acesse `https://SEU_USUARIO.pythonanywhere.com` — deve aparecer a tela de login 🎉

---

## FASE 4 — Registrar o webhook do Telegram

Isso avisa o Telegram para onde mandar as mensagens do seu bot. Rode este
comando **uma única vez** — pode ser no console Bash do PythonAnywhere ou
até colando a URL no navegador (trocando os valores):

```bash
curl "https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook?url=https://<SEU_USUARIO>.pythonanywhere.com/telegram/webhook&secret_token=<WEBHOOK_SECRET>"
```

Troque `<TELEGRAM_TOKEN>`, `<SEU_USUARIO>` e `<WEBHOOK_SECRET>` pelos valores
reais (o mesmo `WEBHOOK_SECRET` que você colocou no `.env`). Deve responder
algo como `{"ok":true,"result":true,"description":"Webhook was set"}`.

---

## FASE 5 — Configurar o GitHub Actions

1. No repositório do GitHub, vá em **Settings → Secrets and variables → Actions**
2. Clique **New repository secret** duas vezes, criando:
   - `APP_URL` → `https://SEU_USUARIO.pythonanywhere.com` (sem barra no final)
   - `CRON_SECRET` → o mesmo valor de `CRON_SECRET` que está no seu `.env`
3. Vá na aba **Actions** do repositório → você deve ver o workflow
   "Verificar e enviar agendamentos" → clique nele → **Run workflow** para
   testar manualmente agora (não precisa esperar o horário programado)

---

## FASE 6 — Testar tudo

1. Abra `https://SEU_USUARIO.pythonanywhere.com`, faça login
2. No grupo do Telegram, envie `/chatid` → o bot deve responder na hora
3. No painel, **+ Novo** → cole o Chat ID → escolha o período → data de
   início → mensagem → **Criar**
4. Na aba **Actions** do GitHub, rode o workflow manualmente (**Run
   workflow**) e confira se o status fica verde ✅
5. Compartilhe o link + usuário/senha com os colaboradores

---

## 🔄 Como atualizar o código depois

Sempre que eu (ou você) mudar algo no projeto:

1. Suba as mudanças no GitHub (upload manual, ou `git push` se preferir usar
   Git no seu computador)
2. No console Bash do PythonAnywhere:
   ```bash
   cd telegram-agendador
   git pull
   pip install -r requirements.txt
   ```
3. Aba **Web** → botão **Reload**

O `schedules.db` (seus agendamentos reais) **não é afetado** por esse
processo — ele fica de fora do controle de versão de propósito (veja o
`.gitignore`), então o `git pull` nunca sobrescreve seus dados.

---

## 🛠 Manutenção — o que fica de olho

| Item | O que acontece | O que fazer |
|---|---|---|
| App web do PythonAnywhere | E-mail a cada ~3 meses perguntando se você ainda quer usar | Clicar no link do e-mail (ou logar no site) — nada é apagado se ignorar, só fica pausado até você confirmar |
| Workflow do GitHub Actions | Desliga sozinho após 60 dias **sem nenhum commit** no repositório | Se for ficar muito tempo sem mexer no código, entre na aba Actions e rode manualmente, ou faça qualquer commit pequeno |
| Horário dos envios | Pode atrasar alguns minutos ocasionalmente (o GitHub não garante horário exato) | Por isso o robô roda 3x/dia — se atrasar num horário, pega no próximo |

---

## ❓ Problemas comuns

| Problema | Causa provável | Solução |
|---|---|---|
| `/chatid` não responde | Webhook não registrado, ou Group Privacy ligado | Refaça a FASE 4; confira Group Privacy no @BotFather |
| Painel não abre | Web app não recarregado após configurar | Aba Web → **Reload** |
| "Internal Server Error" no painel | `.env` incompleto ou caminho errado no WSGI | Confira o arquivo WSGI e o `.env`; veja o log de erros na aba Web → "Error log" |
| GitHub Actions falha (❌) | `APP_URL` ou `CRON_SECRET` errados nos Secrets | Confira Settings → Secrets and variables → Actions |
| Mensagem não chega no dia certo | Workflow desativado por inatividade (60 dias) | Aba Actions → reative e rode manualmente |

---

## 📌 Roteiro — o que falta das suas ideias originais

Já entregue nesta atualização (v3): usuários com permissões, contatos com
nome amigável, botão de teste com senha.

Ainda por vir, na ordem que pretendo seguir:

1. **Log de auditoria completo** — quem logou, criou, editou; alerta para um
   chat do Telegram do admin quando algo falha
2. **Categorias** para organizar as agendas + **emoji único por evento**
3. **Eventos sem data definida** — salvar como rascunho para ativar depois
4. **Visão de calendário** — panorama do que está agendado

Me avisa se quiser mudar essa ordem ou prioridade.
