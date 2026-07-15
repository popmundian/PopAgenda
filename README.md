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

## 🆕 Atualização v4 — horário do envio, precisão com cron-job.org, auditoria e alertas

Também não-destrutiva. O que muda:

### Horário do envio

Cada agendamento agora tem um campo **Horário** (além do período em dias).
A mensagem só sai a partir desse horário, no primeiro check que acontecer
depois dele — por isso a frequência do check importa (veja abaixo).
Agendamentos atrasados de dias anteriores (ex: o servidor ficou fora do ar)
disparam imediatamente, sem esperar o horário — não faz sentido segurar
uma mensagem que já devia ter saído há dias.

### Por que o cron-job.org agora faz sentido

O GitHub Actions (3x/dia) não é feito pra precisão de horário — pode
atrasar minutos, e frequências curtas (tipo a cada 5-15 min) são
desencorajadas pela própria documentação do GitHub por confiabilidade.
O cron-job.org é construído exatamente pra isso: grátis, até 1x por
minuto, sem limite de jobs.

**Configuração (uma vez só):**

1. Crie conta grátis em [cron-job.org](https://cron-job.org)
2. **Create cronjob** →
   - **Title**: PopAgenda - check
   - **URL**: `https://SEU_USUARIO.pythonanywhere.com/cron/check-and-send?token=SEU_CRON_SECRET`
     (o mesmo `CRON_SECRET` do seu `.env`)
   - **Schedule**: a cada 10 ou 15 minutos
3. Salve e ative

O GitHub Actions **continua rodando** 3x/dia — agora como rede de
segurança redundante, caso o cron-job.org tenha algum problema. Não
precisa remover nada.

### Log de auditoria

Nova tela **Auditoria** (menu do admin) registra: login (sucesso e
falha), criação/edição/pausa/remoção de agendamentos, criação/remoção de
usuários, testes de envio. Com filtro por tipo de ação.

### Alerta de falha para o admin

Configure `ADMIN_CHAT_ID` no `.env` (seu chat pessoal com o bot, ou um
grupo/canal só seu) e toda falha de envio automático chega lá na hora,
além de ficar registrada na Auditoria. Comecei só com falhas (não com
todo login/edição) pra não virar spam no seu Telegram — se quiser ampliar
isso, é só pedir.

### Como aplicar

Igual às atualizações anteriores:
```bash
cd PopAgenda
git pull
```
Reload na aba Web. Se quiser os alertas de falha, adicione `ADMIN_CHAT_ID`
no `.env` antes do reload.

---

## 🆕 Atualização v5 — categorias, emoji único e eventos sem data (rascunho)

Também não-destrutiva.

### Categorias

Tela nova **Categorias** (menu lateral) — crie categorias com nome e cor,
associe ao criar/editar um agendamento. O dashboard ganhou um seletor de
**ordenação**: por próximo envio, categoria, alfabética ou período.

### Emoji único por evento

Campo de emoji no formulário (com paleta de sugestões + você pode colar
qualquer emoji). O sistema **bloqueia** se você tentar usar um emoji que já
está em outro agendamento, apontando qual é.

### Eventos sem data (rascunho)

Marque "Salvar sem data definida" ao criar um evento que você sabe que vai
acontecer de novo, mas ainda não sabe quando. Fica guardado, visível no
dashboard com uma tag **Rascunho**, e nunca entra na fila de envio. Pra
ativar depois, é só editar e preencher período + data — o sistema detecta
e ativa automaticamente.

### Como aplicar

```bash
cd PopAgenda
git pull
```
Reload na aba Web. Sem dependência nova.

**Arquivos que mudaram nesta atualização** (se for subir manualmente pelo
GitHub em vez de usar git pull local): `app.py`, `templates/form.html`,
`templates/index.html`, `templates/base.html`, e o novo
`templates/categorias.html`.

---

## 🆕 Atualização v6 — redesign, canal favorito, e "Canais de comunicação"

Também não-destrutiva.

### Redesign visual

Reformulei a tela de **Novo Agendamento** (era a mais apertada e desalinhada):
- Removi a paleta de sugestões de emoji — agora é só um campo compacto onde
  você mesmo digita/cola o emoji, do seu jeito
- O toggle de rascunho virou um controle pequeno e discreto, alinhado à
  direita, em vez do banner grande de antes
- A tela agora tem largura máxima (não fica esticada e desalinhada em
  monitores grandes)
- Tipografia nova (Plus Jakarta Sans) e paleta de cores refinada em todo o
  painel — cards, badges e espaçamento mais consistentes

### "Contatos" agora é "Canais de comunicação"

Renomeei em todo o painel — é mais preciso pro que a lista realmente é (não
são pessoas, são grupos/canais do Telegram). A URL mudou de `/contatos`
para `/canais`.

### Canal favorito por usuário

Ao criar um usuário (Admin → Usuários), dá pra escolher um **canal
favorito** — o campo "Canal" do formulário de novo agendamento já vem
preenchido com ele automaticamente. Cada pessoa também pode trocar o
próprio favorito a qualquer momento em **Minha conta**. Pra usar outro
canal pontualmente, é só trocar no formulário ou escolher outro da lista.

### Como aplicar

```bash
cd PopAgenda
git pull
```
Reload na aba Web. Sem dependência nova.

**Se for subir manualmente pelo GitHub** (upload de arquivo em vez de git
pull local), estes mudaram: `app.py`, `templates/base.html`,
`templates/form.html`, `templates/index.html`, `templates/usuarios.html`,
`templates/conta.html`. E **este arquivo foi removido**:
`templates/contatos.html` (virou `templates/canais.html` — se você tiver os
dois no repositório, apague o `contatos.html` antigo pra não confundir).

---

## 🆕 Atualização v7 — calendário, e correção de permissão

Também não-destrutiva. Inclui uma **correção de segurança** — leia primeiro.

### 🔒 Correção: exclusão de Canais e Categorias

Usuários comuns conseguiam apagar Canais de comunicação e Categorias — só
deveria ser o admin, igual já era pra agendamentos. Corrigido nas duas
telas (backend bloqueia, e o botão de apagar nem aparece mais pra quem não
é admin).

### Calendário

Tela nova **Calendário** — visão mensal com navegação (mês anterior/
seguinte, atalho "Hoje"). Cada dia mostra os eventos que caem nele
(emoji + rótulo), eventos pausados aparecem esmaecidos, e clicar em um
evento leva direto pra edição dele.

- **Admin**: vê os eventos de **todos** os canais juntos
- **Usuário comum**: vê **só** os eventos do canal favorito dele (o mesmo
  configurado em Minha conta). Sem favorito definido, mostra uma tela
  pedindo pra configurar, em vez de aparecer vazio sem explicação

Rascunhos (sem data) nunca aparecem no calendário — não têm data pra
mostrar.

### Como aplicar

```bash
cd PopAgenda
git pull
```
Reload na aba Web. Sem dependência nova.

**Se for subir manualmente pelo GitHub**: `app.py`, `templates/base.html`,
`templates/canais.html`, `templates/categorias.html`, e o novo
`templates/calendario.html`.

---

## 🆕 Atualização v8 — destaque visual, canal principal, e correção de bug

Também não-destrutiva. Inclui uma **correção de bug real** — leia primeiro.

### 🐛 Correção: "database is locked" ao marcar canal principal

Ao implementar a marcação de canal principal, uma chamada de auditoria
acontecia antes do commit da transação principal, e as duas disputavam o
mesmo arquivo do banco. Encontrei isso nos meus próprios testes antes de
te entregar, corrigi, e also revisei todas as OUTRAS 16 chamadas de
auditoria do sistema pra confirmar que nenhuma tinha o mesmo problema
(só essa tinha). Também blindei a função de auditoria: se algo parecido
escapar no futuro, na pior hipótese perde-se um registro de log — a ação
do usuário nunca mais quebra por causa disso.

### Canal principal

Em **Canais de comunicação**, o admin agora marca um canal como ⭐
**principal** (só um por vez — marcar outro desmarca automaticamente o
anterior). Esse canal principal vira o padrão pra qualquer usuário que
ainda não tenha um canal **favorito** pessoal definido — tanto no
formulário de novo agendamento quanto no calendário. A hierarquia é:
favorito pessoal → canal principal → vazio.

### Calendário com mais destaque

Os eventos agora aparecem com a cor da categoria **preenchida** (não só
uma bordinha), com o texto trocando entre claro/escuro automaticamente
pra continuar legível em qualquer cor escolhida.

### Categorias e Canais redesenhados

Categorias virou uma nuvem de chips coloridos em vez de tabela. Canais
virou uma lista de linhas mais ricas (com o selo de principal). Os dois
ficaram mais compactos e organizados.

### Formulário de Novo Agendamento reorganizado

Segui o layout que você desenhou: rótulo e o toggle de rascunho dividem a
mesma linha, o seletor de canal agora tem um toggle "Selecione outro
canal" que só revela o campo manual quando necessário (fica escondido
por padrão), categoria+emoji lado a lado, período com os botões e o campo
manual na mesma linha, e início/fim/horário juntos numa linha só.

### Como aplicar

```bash
cd PopAgenda
git pull
```
Reload na aba Web. Sem dependência nova.

**Se for manual pelo GitHub**: `app.py`, `templates/base.html`,
`templates/form.html`, `templates/canais.html`, `templates/categorias.html`,
`templates/calendario.html`.



---

## 🆕 Atualização v9 — três modos de visualização

Não-destrutiva, sem migração de banco nesta.

Resolvido o pedido dos "modos de visualização" — três opções, alternáveis
pelos botões ao lado do "Ordenar", no topo de Agendamentos:

- **Cartões** — o que já existia, cada agendamento em um bloco rico
- **Em linha** — uma linha compacta por agendamento, só o essencial, pra
  ver muitos de uma vez
- **Detalhes** — tabela ao estilo "Detalhes" do Windows Explorer: colunas
  (Nome, Canal, Categoria, Período, Próximo envio, Status, Criado por,
  Ações), e clicar no cabeçalho de uma coluna ordena por ela, igual no
  Explorer

O modo escolhido fica salvo — se você sair e voltar, continua no mesmo
modo, sem precisar escolher de novo toda vez.

### Como aplicar

```bash
cd PopAgenda
git pull
```
Reload na aba Web. Sem dependência nova, sem migração de banco.

**Se for manual pelo GitHub**: só `app.py` e `templates/index.html`.



---

## 🆕 Correção v10.1 — destaque visual no período selecionado

Ao clicar num dos botões de dias (7d, 14d...), o valor era salvo
corretamente por trás dos panos, mas nenhum botão mudava de aparência —
sem confirmação visual de qual foi escolhido. Corrigido: o botão clicado
agora fica destacado (preenchido), e some o destaque do anterior. Testei
simulando cliques de verdade (não só lendo o código): clicar, trocar de
botão, ir pro modo "Personalizado" e voltar, e reabrir um agendamento já
existente (o botão certo já vem marcado).

**Como aplicar**: só `templates/form.html` mudou.
```bash
cd PopAgenda
git pull
```
Reload na aba Web.

## 🆕 Atualização v10 — edição completa, cópia entre canais, escopo e filtros

Também não-destrutiva.

### 📝 Formulário de Novo Agendamento — refeito conforme pedido

1. **Rótulo agora é obrigatório**, alinhado com o toggle de Rascunho na
   mesma linha
2. **Canal favorito pré-selecionado**, mostrado de forma compacta; pra
   trocar, o botão **"Usar outro canal salvo"** revela a lista completa
3. **Período personalizado** agora fica na mesma linha dos botões fixos
   (7d, 14d...) — clique em "✏️ Personalizado" pra digitar outro valor
4. **Data de início, fim e horário** juntos numa linha, logo acima da
   Mensagem

### Editar tudo que é cadastrado

Canais, Categorias e Usuários agora têm botão de **editar** (não só
criar/apagar). Em Usuários, dá pra editar nome e papel.

### Copiar agendamento entre canais

Botão de copiar (ícone 📋) em qualquer agendamento — cria uma cópia
apontando pra outro canal, mesma mensagem/período/datas. O emoji não é
copiado (evita duplicidade); escolha um novo na cópia.

### Ativar/desativar usuário — inclusive outros admins

Em Usuários, além de apagar, agora dá pra **desativar** uma conta sem
apagar (bloqueia o login, preserva o histórico). Funciona pra qualquer
conta, inclusive outros administradores — só não a sua própria, e nunca
a ponto de zerar os admins ativos.

### Dashboard escopado por canal (igual o Calendário)

Por padrão, quem não é admin só vê os agendamentos do **próprio canal**
(favorito ou principal) na tela de Agendamentos — igual já acontecia no
Calendário. Admin continua vendo tudo. O filtro de canal permite ver
outros canais quando necessário — não é uma parede, é só o padrão.

### Filtros

Barra de filtro no topo de Agendamentos: busca por texto (nome, mensagem,
canal), categoria, status (ativo/pausado/rascunho) e canal — combináveis.

### Categorias mostram quantos agendamentos usam cada uma

Contagem de agendamentos **ativos** ao lado de cada categoria.

### "Detalhes" agora é o padrão

A tela principal abre no modo tabela por padrão (antes era Cartões).

### Como aplicar

```bash
cd PopAgenda
git pull
```
Reload na aba Web. Sem dependência nova.

**Se for manual pelo GitHub**: `app.py`, e em `templates/`: `base.html`,
`form.html`, `index.html`, `canais.html`, `categorias.html`,
`usuarios.html`.



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

## ✅ Roteiro — plano original completo, agora com edição e refinamentos

Todos os itens originais entregues, mais: edição completa de canais,
categorias e usuários; cópia de agendamento entre canais; ativar/desativar
qualquer usuário (inclusive admins); dashboard escopado por canal com
filtros; contagem de uso por categoria.

Qualquer ideia nova ou ajuste fino, é só pedir.

Qualquer ideia nova ou ajuste fino, é só pedir.

Me avisa quando quiser seguir pra essa.
