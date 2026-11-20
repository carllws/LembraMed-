# LembraMed! (Python + Flask + SQLite)

Aplicativo web com **login e cadastro de usuários**, alarmes de remédio, histórico e
**aviso no celular** (push via ntfy). Cada pessoa só enxerga os próprios remédios.

## Jeito mais fácil (Windows)
Dê dois cliques em **iniciar.bat**. Ele instala o Flask, abre o LembraMed! no navegador
(http://127.0.0.1:5000) e liga o servidor. Deixe a janela preta aberta enquanto usar.
Na primeira vez, clique em **Criar conta**.

## Como rodar (manual)
    pip install -r requirements.txt
    python app.py                       # http://127.0.0.1:5000
    python -m unittest discover tests   # testes (59)

## Visual (azul noite)
Tema **azul noite** por padrão (com tema claro opcional no botão ☀️/🌙), fundo com estrelas e brilhos animados,
cartões de vidro, menu lateral (vira barra inferior no celular) com indicador deslizante, troca de abas com
animação direcional, relógio e saudação ao vivo, contagem para a próxima dose, botão flutuante "+" para um novo
cronograma, efeito de onda nos botões e confetes ao confirmar a dose. Quem prefere menos movimento no sistema
operacional vê as animações reduzidas.

## Cronogramas (dashboard)
Na aba **Cronogramas**: adesão da semana, calendário seg–dom com o status de cada dose e a lista de
tratamentos com barra de progresso ("Dia 3 de 10"). O assistente **Novo cronograma** monta os horários
sozinho (1× a 6× ao dia a partir do primeiro horário, ou horários personalizados), define a duração
(por período ou uso contínuo), a data de início e os dias da semana, e mostra uma prévia em linha do tempo
de 24 h com o total de doses antes de salvar. Doses antes da criação do cronograma não contam como perdidas,
e alarmes não atendidos viram "perdido" após 2 h.

## Cálculo automático por intervalo de horas
No assistente, a opção **A cada X horas** (X de 1 a 12) calcula a primeira dose e todas as seguintes.
Exemplo: dipirona de 6 em 6 horas, começando às 16:23 → 16:23, 22:23, 04:23, 10:23, 16:23… Funciona também
para intervalos que não dividem 24 (como 5 h), em que o horário muda a cada dia. A primeira dose pode ser
**agora** ou um horário escolhido; a duração é por dias (ex.: 3 dias = 12 doses de 6 em 6 h) ou uso contínuo
(o app mantém sempre as próximas 72 h calculadas). Cada dose vira um alarme, com push e histórico, e o painel mostra
o progresso "3 de 12 doses tomadas". Limite: 2000 doses por cronograma.

## Cadastro em 3 passos
A aba **Criar conta** é um assistente: **nome → e-mail → senha**, com barra de progresso e animação de
deslize entre os passos (Enter avança). O nome vira uma saudação ao vivo ("Prazer, Maria! 👋"); o e-mail
mostra sugestões de provedor (gmail, outlook…), avisa de erros comuns de digitação ("gmial.com") e marca ✓
quando é válido; a senha tem barra de força, checklist que vai marcando os requisitos e confirmação com
aviso ao vivo. O botão pulsa quando o passo está certo. Regras do servidor: nome obrigatório, e-mail válido
e senha de 8 a 128 caracteres (o restante do checklist é só recomendação).

## Histórico e som do alarme
- **Histórico de 30 dias**, com filtro de 7, 15 ou 30 dias e resumo (tomadas, perdidas e adesão do período).
- **Som do alarme** (aba Perfil): 17 sons, em dois grupos — **Estilo celular** (Horizonte, Galáxia, Flor da manhã,
  Marimba, Radar, Reflexo, Harpa, Bolhas) e **Clássicos** (Telefone, Bip, Sino, Sirene, Digital, Suave, Despertador,
  Alerta urgente, Pulso) —, **altura** (grave ↔ agudo),
  **volume** e **duração** do toque (5 s, 10 s, 20 s, 30 s, 1 min ou até confirmar, no máximo 5 min).
  O som se repete durante o tempo escolhido e para ao confirmar ou adiar; o botão "Silenciar" também para.
  Os sons são gerados no próprio navegador (Web Audio), sem arquivos de áudio. O som padrão é o Horizonte.
  As escolhas ficam salvas no navegador de cada usuário. Alarmes adiados voltam a tocar quando o adiamento termina.

## Aviso no celular (push)
Cada usuário configura o seu na aba **Perfil**: instale o app **ntfy**, clique em
"Gerar nome", salve, assine o mesmo nome no app e clique em "Enviar teste".
Na hora do remédio o push chega e se repete a cada 10 min até você confirmar.

## Novidades
- **PWA**: instalável no celular (manifesto + service worker).
- **Recuperação de senha**: link por e-mail válido por 30 min. Defina `BASE_URL` (endereço público do app; sem ela o link só é montado em localhost) e `SMTP_HOST`, `SMTP_PORT`, `SMTP_USUARIO`, `SMTP_SENHA`, `SMTP_DE`; sem SMTP o link aparece no console do servidor.
- **Estoque**: aba Perfil; baixa de 1 a cada dose tomada e push de aviso quando chega ao limite.
- **Cuidador/familiar**: tópico ntfy que recebe aviso de dose perdida.
- **Som salvo na conta**, **letra grande/alto contraste** e **histórico para imprimir/salvar em PDF** (Perfil).
- **Voz**: depois do alarme, o app fala o remédio e a dosagem (Web Speech API, pt-BR) e vibra o celular; liga/desliga em Perfil → Som.
- **Publicação**: veja `DEPLOY.md` (Docker, Render, `BASE_URL`, `TZ`, disco em `/data`, cookie `Secure`, SQLite em modo WAL).
- **Produção**: `python app.py` usa waitress se instalado; `HOST`/`PORT` por variável de ambiente.

## Estrutura
- `static/index.html` – tela (login, menu Hoje/Cronogramas/Histórico/Perfil, tema azul noite, animações)
- `app.py`           – API REST, sessão de login, limite de tentativas e agendador (30 s)
- `servico.py`       – regras: usuários, alarmes, adiar, confirmar, histórico
- `db.py`            – esquema SQLite (usuarios, medicamentos com início/fim/intervalo, horarios, registros)
- `notificacao.py`   – envio do push (ntfy)
- `iniciar.bat`      – atalho para Windows
- `tests/`           – testes das regras e da API

## Segurança (resumo para o relatório)
- Senhas guardadas só como hash (PBKDF2-SHA256); nunca em texto puro.
- Sessão por cookie assinado (HttpOnly, SameSite=Lax); a chave fica no arquivo `.segredo`
  (criado sozinho) ou na variável `SECRET_KEY`.
- 5 senhas erradas seguidas bloqueiam o login por 60 s (por e-mail + IP).
- Todas as consultas filtram pelo usuário logado; testes garantem que um usuário
  não vê nem altera dados de outro.
- Se for publicar na internet: use HTTPS (cookie `Secure`), um servidor de produção
  (gunicorn/waitress) e não rode com `debug=True`.

> Aviso: ferramenta de lembrete, não substitui orientação médica.
