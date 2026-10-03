# Biblioteca

Projeto acadêmico com back-end Flask, front-end HTML/Jinja2, CSS e JavaScript e banco relacional. Desenvolvido a partir dos exemplos de CRUD Flask/Firebird fornecidos.

## Funcionalidades

- Livros: criar, listar, buscar por título/autor, editar e excluir, com código automático.
- Usuários: cadastrar, listar, editar, excluir, bloquear e desbloquear.
- Administrador gerencia livros e usuários; leitor consulta o acervo.
- Senhas armazenadas como hash Bcrypt com salt e custo 12, nunca em texto puro. Hash é uma transformação irreversível, não uma senha recuperável.
- Senhas de 12 a 64 caracteres, até 72 bytes UTF-8, com maiúscula, minúscula, número e símbolo, validadas no servidor.
- Cinco tentativas incorretas bloqueiam o login por 15 minutos. Administrador pode liberar antes. Bloqueio manual permanece até desbloqueio.
- Bloqueio, exclusão e edição de usuário invalidam sessões existentes. Sessão expira após 30 minutos de inatividade.
- Proteção CSRF em todos os formulários POST, SQL parametrizado e escape HTML do Jinja2.
- Impede bloquear, excluir ou rebaixar o administrador que executa a ação.

## Executar no Windows (Python 3.12 ou superior)

Abra o PowerShell na pasta do projeto:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:SECRET_KEY = (.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
.\.venv\Scripts\python.exe -m flask --app biblioteca init-db
.\.venv\Scripts\python.exe -m flask --app biblioteca create-admin
.\.venv\Scripts\python.exe -m flask --app biblioteca run
```

No cadastro do administrador, informe nome, e-mail e uma senha forte (a senha fica oculta). Abra http://127.0.0.1:5000 e faça login. Nenhuma conta ou senha padrão é distribuída. Mantenha a mesma SECRET_KEY nas próximas execuções; não publique a chave. Se omitida, uma chave temporária é gerada a cada início, encerrando sessões após reiniciar.

SQLite é o padrão e cria `instance/biblioteca.db`. Os scripts de estrutura estão em `database/`. O banco com contas reais não deve ser enviado ao GitHub; a entrega inclui a estrutura e comando para criá-lo.

## Executar com Firebird (conforme as aulas)

Instale o servidor Firebird 3 ou superior e sua biblioteca cliente `fbclient.dll` compatível com a arquitetura do Python. Crie um banco vazio UTF8 com uma ferramenta Firebird (por exemplo, isql) e um usuário com permissão para criar as tabelas. Configure no PowerShell:

```powershell
$env:DB_ENGINE = 'firebird'
$env:FIREBIRD_DATABASE = 'localhost:C:/dados/biblioteca.fdb'
$env:FIREBIRD_USER = 'seu_usuario'
$env:FIREBIRD_PASSWORD = 'sua_senha'
.\.venv\Scripts\python.exe -m flask --app biblioteca init-db
.\.venv\Scripts\python.exe -m flask --app biblioteca create-admin
.\.venv\Scripts\python.exe -m flask --app biblioteca run
```

Execute `init-db` no Firebird apenas uma vez em banco vazio; não é uma migração. O mesmo aplicativo utiliza o driver `firebird-driver` e SQL compatível com ambos os bancos. A integração Firebird precisa ser validada em uma instalação Firebird; os testes automatizados usam SQLite.

## Testes

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Cobrem CRUD, senha forte/hash, autenticação, autorização, CSRF, bloqueio manual/automático e invalidação de sessões.

## Estrutura

```text
biblioteca/
  __init__.py     Rotas, autenticação, permissões e comandos CLI
  db.py           Conexões, consultas e transações
  templates/      Interface em português
  static/         CSS responsivo e confirmação de exclusão
database/         Estruturas SQLite e Firebird
tests/            Testes de integração
requirements.txt  Dependências
```

## Roteiro de apresentação

1. Criar o administrador e entrar.
2. Cadastrar um livro, buscar, editar e excluir.
3. Cadastrar um leitor; mostrar rejeição de senha fraca.
4. Entrar como leitor e mostrar o acervo sem ações administrativas.
5. Como administrador, bloquear o leitor e demonstrar a recusa de acesso.
6. Desbloquear, errar cinco senhas e demonstrar o bloqueio temporário.
7. Mostrar no banco apenas o hash Bcrypt, sem divulgar senhas reais.

## Publicar no GitHub

Destino escolhido: conta `NicolasGiovanniRodrigues`, repositório `Biblioteca`.

Crie um repositório vazio nesse nome em https://github.com/new (sem README ou .gitignore gerados pelo GitHub). Na pasta do projeto:

```powershell
git init -b main
git add .
git commit -m "Projeto Biblioteca: CRUD e autenticação"
git remote add origin https://github.com/NicolasGiovanniRodrigues/Biblioteca.git
git push -u origin main
```

Autentique no GitHub quando solicitado. O endereço esperado após a publicação é https://github.com/NicolasGiovanniRodrigues/Biblioteca . Esse endereço só funciona depois que o repositório for criado e enviado.

Para uso público, execute com servidor WSGI e HTTPS, configure `COOKIE_SECURE=1`, uma chave secreta persistente e credenciais do banco via ambiente. O servidor `flask run` é destinado ao desenvolvimento local. O bloqueio por conta não substitui limitação de tráfego por IP em uma implantação pública.
