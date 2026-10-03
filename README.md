# Biblioteca — modelo da aula

Projeto adaptado ao ZIP `PYCHARM-E-BANCO-main` enviado: Flask, driver **fdb**, banco **Firebird**, SQL direto e rotas em **PythonProject1/main.py**. A estrutura anterior com pacote `biblioteca` e SQLite foi substituída pelo modelo da professora.

## Estrutura

```text
Biblioteca/
├── BANCO.FDB
├── PythonProject1/
│   ├── main.py
│   ├── templates/
│   │   ├── livros.html
│   │   ├── novo.html
│   │   ├── editar.html
│   │   ├── login.html
│   │   ├── usuarios.html
│   │   └── usuario_formulario.html
│   └── static/
│       ├── css/style.css
│       └── js/script.js
├── database/atualizar_usuario.sql
├── tests/test_main.py
└── requirements.txt
```

## O que segue o exemplo da professora

- `app = Flask(__name__)`, `fdb.connect`, `con.cursor`, `cursor.execute`, `fetchall` e `fetchone`.
- SQL parametrizado com `?`, `con.commit()`, `con.rollback()` e fechamento do cursor no `finally`.
- Tabela `LIVRO`: `ID_LIVRO`, `NOME`, `AUTOR`, `LIVRO` (tema) e `DATAPUBLICACAO` (ano inteiro).
- Rotas `/`, `/novo`, `/criar`, `/editar/<int:id>` e `/deletar/<int:id>`.
- Formulários com os nomes `nome`, `autor` e `ano`; templates acessam tuplas por índices (`livro[0]`, `livro[1]` etc.).
- `BANCO.FDB` na raiz, como no material original. Os livros de exemplo foram preservados.

## Requisitos adicionados

- CRUD de usuários na tabela `USUARIO`, mantendo `ID_USUARIO`, `NOME`, `EMAIL` e `SENHA`.
- Senha armazenada como **hash Bcrypt** (salt e custo 12), nunca como texto puro. O campo `SENHA` foi ampliado para VARCHAR(100).
- Senha forte: de 12 a 64 caracteres, no máximo 72 bytes UTF-8, com maiúscula, minúscula, número e símbolo; validada no servidor.
- Administrador gerencia livros e usuários. Leitor consulta a lista de livros.
- Bloqueio manual até o administrador desbloquear; cinco erros de senha bloqueiam o login por 15 minutos.
- Bloquear, editar ou excluir um usuário invalida suas sessões existentes. Sessão expira após 30 minutos de inatividade.
- Proteção CSRF dos formulários; administrador não pode bloquear, excluir ou rebaixar a própria conta.
- Correção do exemplo original: exclusão redireciona para `index`, pois o endpoint `livros` não existia. Foi adicionado o botão Deletar à lista.

O banco entregue já está preparado para esses campos, sem usuários ou senhas de acesso cadastrados. Os dados de livros são os exemplos do banco fornecido. O arquivo de Downloads original não foi alterado.

## Executar no PyCharm / Windows

1. Instale Python 3.12 ou superior e **Firebird 4 de 64 bits**, compatível com o Python. O `BANCO.FDB` fornecido usa formato ODS 13.0; Firebird 3 não o abre diretamente.
2. Abra a pasta raiz no PyCharm, crie um ambiente virtual e instale as dependências. No PowerShell da pasta raiz:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:SECRET_KEY = (.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))")
$env:FIREBIRD_HOST = 'localhost'
$env:FIREBIRD_USER = 'SYSDBA'
$env:FIREBIRD_PASSWORD = 'senha-do-seu-servidor'
$env:FIREBIRD_CLIENT = 'C:/Program Files/Firebird/Firebird_4_0/fbclient.dll'
.\.venv\Scripts\python.exe -m flask --app PythonProject1/main.py preparar-banco
.\.venv\Scripts\python.exe -m flask --app PythonProject1/main.py criar-admin
.\.venv\Scripts\python.exe PythonProject1/main.py
```

3. Use a senha real do **seu servidor Firebird** na variável `FIREBIRD_PASSWORD`. No material da professora, o servidor estava configurado com `sysdba`; essa senha não é universal. O servidor precisa ter acesso ao caminho do arquivo `BANCO.FDB`. Ajuste o caminho de `fbclient.dll` conforme sua instalação.
4. No comando `criar-admin`, informe nome, e-mail e uma senha forte; a senha fica oculta. Abra http://127.0.0.1:5000 e entre com esse usuário.
5. No botão Run do PyCharm, selecione `PythonProject1/main.py`, o interpretador `.venv` e configure as mesmas variáveis de ambiente na Run Configuration. O caminho do banco é calculado a partir de `main.py`, independente do diretório de execução. Se necessário, configure `FIREBIRD_DATABASE` com o caminho absoluto do banco.

`preparar-banco` pode ser repetido e também adapta uma cópia do banco original da aula; faça backup antes de migrar outro banco. Se outro banco tiver senhas antigas em texto puro, elas não permitem login: redefina-as pelo administrador. Nenhuma senha é convertida automaticamente. Mantenha uma `SECRET_KEY` persistente fora do GitHub; sem ela, uma chave temporária encerra as sessões ao reiniciar.

## Testes com Firebird real

Os testes fazem cópias temporárias do banco entregue e usam **Firebird Embedded 4**, sem SQLite. Com a distribuição ZIP oficial do Firebird 4 extraída em uma pasta:

```powershell
$env:FIREBIRD = 'C:/ferramentas/firebird4'
$env:FIREBIRD_CLIENT = "$env:FIREBIRD/fbclient.dll"
$env:FIREBIRD_TEST_CLIENT = $env:FIREBIRD_CLIENT
$env:FIREBIRD_LOCK = "$PWD/.pytest_cache/firebird-locks"
New-Item -ItemType Directory -Force $env:FIREBIRD_LOCK
.\.venv\Scripts\python.exe -m pytest -q
```

O banco de entrega não é modificado pelos testes. Sem `FIREBIRD_TEST_CLIENT`, os testes são sinalizados como ignorados, e isso não significa aprovação. A versão entregue foi validada com Firebird 4.0.6 Embedded em Windows.

## Roteiro de apresentação

1. Mostrar `main.py`, as rotas e as consultas iguais à estrutura da aula.
2. Cadastrar, listar, editar e deletar um livro.
3. Cadastrar um leitor e mostrar a recusa de senha fraca.
4. Bloquear e desbloquear o leitor; demonstrar que a sessão é encerrada.
5. Errar cinco senhas e mostrar o bloqueio temporário.
6. Mostrar o campo `SENHA` com hash Bcrypt e a tabela `LIVRO` preservada.

Repositório: https://github.com/NicolasGiovanniRodrigues/Biblioteca

O servidor Flask deste projeto é para desenvolvimento e apresentação local. Para hospedar publicamente, use HTTPS, servidor WSGI, `COOKIE_SECURE=1`, chave persistente e credenciais próprias do banco.
