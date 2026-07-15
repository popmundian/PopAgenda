# 📖 Guia do Usuário — PopAgenda

Este guia é para quem **usa** o painel no dia a dia — criar, testar e
gerenciar agendamentos. Se você precisa instalar ou configurar o sistema
do zero, esse não é o guia certo; peça o `README.md` técnico pro admin.

Você precisa de um **usuário e senha** — peça pro administrador, se ainda
não tiver.

---

## 🧪 Testando num grupo novo — passo a passo

Essa é a dúvida mais comum de quem começa: "quero ver isso funcionando
antes de confiar". Segue o caminho mais curto.

### 1. Adicione o bot no grupo

No Telegram:
1. Abra (ou crie) o grupo onde quer testar
2. Toque no nome do grupo, no topo → **Adicionar membro**
3. Busque pelo username do bot (o mesmo que você já usa pra falar com ele
   no privado)
4. Adicione normalmente, como adicionaria uma pessoa

> Não precisa configurar nada no bot em si — as permissões dele já foram
> ajustadas uma vez pelo administrador, e valem automaticamente pra
> qualquer grupo novo que ele entrar.

### 2. Descubra o Chat ID do grupo

Dentro do grupo, envie:
```
/chatid
```
O bot responde na hora com um número (geralmente negativo, tipo
`-1001234567890`). Guarde esse número — ou nem precisa, o próximo passo
já resolve isso.

### 3. Cadastre o grupo como um Canal

No painel:
1. Menu lateral → **Canais de comunicação**
2. Preencha um nome (ex: "Grupo de Teste") e cole o Chat ID
3. **Cadastrar**

Feito isso, esse grupo já aparece pronto na lista suspensa sempre que
você for criar um agendamento — não precisa colar o ID de novo.

### 4. Crie um agendamento de teste

1. Menu lateral → **Novo agendamento**
2. Escolha o canal que você acabou de cadastrar
3. Preencha rótulo, mensagem, período (pode ser qualquer um, é só teste)
4. **Criar agendamento**

### 5. Use o botão "Testar"

Na lista de agendamentos, ache o que você criou e clique em **Testar**.
Vai pedir sua senha pessoal de login — isso é de propósito, pra ninguém
disparar mensagem sem querer. Confirme, e a mensagem chega no grupo **na
hora**, marcada com `🧪 [TESTE]` no início.

Isso **não conta** como um envio de verdade e não interfere no
agendamento recorrente — pode testar quantas vezes quiser.

### 6. Confira no grupo

Se a mensagem chegou certinha (texto, formatação), seu teste deu certo —
o agendamento real vai funcionar exatamente igual, só que no dia e
horário programados, sem o `[TESTE]` na frente.

---

## Criando um agendamento de verdade

| Campo | O que fazer |
|---|---|
| **Rótulo** | Nome curto pra você reconhecer na lista depois |
| **Canal** | Escolha um canal salvo, ou ative "Selecione outro canal" pra colar um Chat ID novo |
| **Categoria** | Opcional — ajuda a organizar e ordenar depois |
| **Emoji** | Opcional, mas **não pode repetir** entre agendamentos — o sistema avisa se já estiver em uso em outro |
| **Período** | Clique num botão (7d, 14d, 56d...) ou digite outro número de dias |
| **Horário** | A que horas a mensagem sai, no dia em que for disparar |
| **Data de início** | Obrigatória (a não ser que marque como rascunho) |
| **Data de fim** | Opcional — em branco, repete sem parar |
| **Mensagem** | Suporta `*negrito*`, `_itálico_` e `` `código` `` (formatação do Telegram) |
| **Rascunho** | Marque se ainda não sabe a data certa — fica guardado, visível na lista, mas nunca entra na fila de envio até você voltar e preencher uma data |

---

## Organizando e acompanhando

**Modos de visualização** — no topo de Agendamentos, três botões:
- 🔲 **Cartões** — visão completa, um bloco por agendamento
- ☰ **Em linha** — lista compacta, pra ver muitos de uma vez
- 📊 **Detalhes** — tabela com colunas; clique no cabeçalho de uma coluna
  pra ordenar por ela (igual ao modo "Detalhes" do Windows Explorer)

O modo que você escolher fica salvo pras próximas vezes.

**Calendário** — mostra os eventos do **seu canal favorito** (veja
abaixo). Clique em qualquer evento pra ir direto editá-lo.

**Log** — em cada agendamento, o botão de relógio mostra o histórico de
envios, com sucesso ou detalhe do erro.

---

## Minha conta

Menu lateral → **Minha conta**:
- **Trocar senha** — a qualquer momento, só precisa da senha atual
- **Canal favorito** — o canal que pré-preenche automaticamente o campo
  "Canal" ao criar um agendamento novo, e que define o que aparece no seu
  Calendário

> Sem favorito configurado? O sistema usa o canal **⭐ principal**
> (definido pelo admin) como padrão. Se nenhum dos dois existir, o campo
> vem em branco normalmente.

---

## O que só o administrador faz

- **Apagar** agendamentos, canais ou categorias (você pode **pausar**,
  mas apagar de vez é só admin)
- Criar ou remover outros usuários
- Ver o log de auditoria completo do sistema

Se precisar de algo dessa lista, é só pedir pro admin.

---

## Perguntas comuns

| Situação | O que fazer |
|---|---|
| Bot não responde `/chatid` no grupo novo | Confirme que ele foi realmente adicionado como membro |
| Mensagem de teste não chega | Veja se o grupo tem a opção "só admins podem postar" ativada — isso bloqueia o bot também, mesmo estando no grupo |
| Não consigo apagar algo | Normal — só admin apaga. Peça pra ele, ou use **Pausar** enquanto isso |
| Esqueci minha senha | Peça pro admin resetar em Usuários |
| "Esse emoji já está em uso" | Cada emoji só pode estar em um agendamento por vez — escolha outro ou remova do outro primeiro |
| Criei um agendamento com data no passado | Ele dispara na próxima verificação (não manda tudo que "deveria" ter saído antes, só a partir de agora) |
