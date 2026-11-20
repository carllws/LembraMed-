# Publicar o LembraMed! e instalar no celular

## 1. Colocar o código no GitHub
Crie um repositório e envie a pasta do projeto. O `.gitignore` já deixa de fora o banco (`*.db`) e o `.segredo`.

## 2. Publicar no Render
1. Em render.com, escolha **New → Blueprint** e selecione o repositório (ele lê o `render.yaml`).
2. Crie o serviço. O disco `/data` guarda o banco, e o plano `starter` é pago (confira o preço atual no site). O plano gratuito "dorme" quando ninguém acessa e não tem disco persistente, então os alarmes não saem e os dados se perdem.
3. Quando o Render mostrar o endereço (algo como `https://lembramed.onrender.com`), crie a variável **BASE_URL** com ele e faça um novo deploy. Ela é usada no link do e-mail de recuperação de senha.
4. Opcional: configure `SMTP_HOST`, `SMTP_PORT`, `SMTP_USUARIO`, `SMTP_SENHA` e `SMTP_DE` para o e-mail funcionar. Sem isso, o link de nova senha só aparece nos logs.

Outros serviços com Docker (Railway, Fly.io) também servem: use o `Dockerfile` e defina as mesmas variáveis do `render.yaml`, com um volume montado em `/data`.

## 3. Instalar no celular
- **Android (Chrome):** abra o endereço, toque em ⋮ → **Instalar app**.
- **iPhone (Safari):** botão Compartilhar → **Adicionar à Tela de Início**.
- Depois de entrar, toque em **Ativar som e aviso** na aba Hoje e cadastre o tópico do ntfy no Perfil.

## 4. Cuidados
- Mantenha **um único processo**: o agendador de alarmes roda dentro dele.
- Faça cópia do banco (`/data/lembramed.db`) de vez em quando.
- O app só toca o som e fala com a página aberta. Para avisar com o app fechado, continue usando o ntfy.
- Rodar em casa por HTTP não instala como app: o navegador exige HTTPS, exceto em `localhost`.
