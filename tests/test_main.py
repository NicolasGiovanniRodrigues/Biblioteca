"""Testes de integração usando Firebird real, sem SQLite ou banco simulado."""
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import time
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('biblioteca_aula', ROOT / 'PythonProject1/main.py')
main = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = main
spec.loader.exec_module(main)
pytestmark = pytest.mark.skipif(not os.environ.get('FIREBIRD_TEST_CLIENT'), reason='Configure FIREBIRD_TEST_CLIENT para executar com Firebird Embedded 4.')
SENHA = 'Biblioteca!2026'


@pytest.fixture
def app(tmp_path, monkeypatch):
    main.fdb.load_api(os.environ['FIREBIRD_TEST_CLIENT'])
    banco = tmp_path / 'teste.fdb'
    shutil.copy2(ROOT / 'BANCO.FDB', banco)
    monkeypatch.setattr(main, 'database', str(banco))
    monkeypatch.setattr(main, 'host', '')
    monkeypatch.setattr(main, 'password', 'masterkey')
    main.app.config.update(TESTING=True, SECRET_KEY='teste-local', BCRYPT_LOG_ROUNDS=4)
    result = main.app.test_cli_runner().invoke(args=['preparar-banco'])
    assert result.exit_code == 0, result.output
    with main.app.app_context():
        con = main.conectar()
        cursor = con.cursor()
        for perfil in ('admin', 'leitor'):
            cursor.execute('INSERT INTO USUARIO (NOME,EMAIL,SENHA,PERFIL) VALUES (?,?,?,?)', (perfil, perfil+'@example.com', main.bcrypt.generate_password_hash(SENHA).decode(), perfil))
        con.commit()
        cursor.close()
    return main.app


def consultar(app, sql, parametros=()):
    with app.app_context():
        cursor = main.conectar().cursor()
        try:
            cursor.execute(sql, parametros)
            return cursor.fetchall()
        finally:
            cursor.close()


def post(cliente, caminho, dados=None):
    with cliente.session_transaction() as sessao:
        sessao.setdefault('csrf_token', 'teste')
        token = sessao['csrf_token']
    return cliente.post(caminho, data={**(dados or {}), 'csrf_token': token})


def login(cliente, perfil='admin', senha=SENHA):
    return post(cliente, '/login', {'email':perfil+'@example.com', 'senha':senha})


def test_crud_livros_modelo_aula(app):
    cliente = app.test_client()
    login(cliente)
    quantidade = consultar(app, 'SELECT COUNT(*) FROM LIVRO')[0][0]
    assert cliente.get('/novo').status_code == 200
    assert post(cliente, '/criar', {'nome':'Livro de teste','autor':'Autora','ano':'2020'}).status_code == 302
    id = consultar(app, 'SELECT ID_LIVRO FROM LIVRO WHERE NOME = ?', ('Livro de teste',))[0][0]
    assert b'Livro de teste' in cliente.get('/').data
    assert cliente.get(f'/editar/{id}').status_code == 200
    post(cliente, f'/editar/{id}', {'nome':'Livro atualizado','autor':'Outro autor','ano':'2021'})
    assert consultar(app, 'SELECT NOME,AUTOR,DATAPUBLICACAO FROM LIVRO WHERE ID_LIVRO = ?', (id,))[0] == ('Livro atualizado','Outro autor',2021)
    post(cliente, '/criar', {'nome':'Livro atualizado','autor':'Autora','ano':'2020'})
    post(cliente, '/criar', {'nome':'Inválido','autor':'Autora','ano':'-1'})
    assert consultar(app, 'SELECT COUNT(*) FROM LIVRO')[0][0] == quantidade + 1
    resposta = post(cliente, f'/deletar/{id}')
    assert resposta.status_code == 302 and resposta.location.endswith('/')
    assert consultar(app, 'SELECT COUNT(*) FROM LIVRO')[0][0] == quantidade
    assert post(cliente, f'/deletar/{id}').status_code == 404


@pytest.mark.parametrize('senha',['curta','abcdefghijkl','ABCDEFGHIJKL','Abcdefgh1234','Abcdefgh!!!!','A1!'+'é'*36])
def test_senha_fraca(senha):
    with pytest.raises(ValueError):
        main.senha_forte(senha)


def test_crud_usuario_bcrypt(app):
    cliente = app.test_client()
    login(cliente)
    dados = {'nome':'Ana','email':'ana@example.com','perfil':'leitor','senha':'fraca'}
    assert post(cliente, '/usuario/novo', dados).status_code == 200
    dados['senha'] = SENHA
    assert post(cliente, '/usuario/novo', dados).status_code == 302
    id, hash = consultar(app, 'SELECT ID_USUARIO,SENHA FROM USUARIO WHERE EMAIL = ?', ('ana@example.com',))[0]
    assert hash.startswith('$2b$') and hash != SENHA
    assert main.bcrypt.check_password_hash(hash, SENHA)
    assert cliente.get('/usuarios').status_code == 200
    assert cliente.get(f'/usuario/editar/{id}').status_code == 200
    leitor = app.test_client()
    assert post(leitor, '/login', {'email':'ana@example.com','senha':SENHA}).status_code == 302
    dados.update(nome='Ana Maria',senha='OutraSenha!2026')
    post(cliente, f'/usuario/editar/{id}', dados)
    assert leitor.get('/').status_code == 302
    assert consultar(app, 'SELECT NOME FROM USUARIO WHERE ID_USUARIO = ?', (id,))[0][0] == 'Ana Maria'
    post(cliente, f'/usuario/{id}/deletar')
    assert consultar(app, 'SELECT ID_USUARIO FROM USUARIO WHERE ID_USUARIO = ?', (id,)) == []


def test_permissoes_csrf_autoprotecao(app):
    cliente = app.test_client()
    assert cliente.get('/').status_code == 302
    assert cliente.post('/login',data={'email':'admin@example.com','senha':SENHA}).status_code == 400
    login(cliente,'leitor')
    assert cliente.get('/').status_code == 200
    for rota in ('/novo','/usuarios','/usuario/novo'):
        assert cliente.get(rota).status_code == 403
    assert post(cliente,'/deletar/1').status_code == 403
    login(cliente)
    id = consultar(app,'SELECT ID_USUARIO FROM USUARIO WHERE PERFIL = ?',('admin',))[0][0]
    post(cliente,f'/usuario/{id}/bloquear')
    post(cliente,f'/usuario/{id}/deletar')
    post(cliente,f'/usuario/editar/{id}',{'nome':'Admin','email':'admin@example.com','perfil':'leitor','senha':''})
    assert consultar(app,'SELECT PERFIL,BLOQUEADO FROM USUARIO WHERE ID_USUARIO = ?',(id,))[0] == ('admin',0)


def test_bloqueio_manual_e_sessao(app):
    admin, leitor = app.test_client(), app.test_client()
    login(admin)
    login(leitor,'leitor')
    id = consultar(app,'SELECT ID_USUARIO FROM USUARIO WHERE PERFIL = ?',('leitor',))[0][0]
    post(admin,f'/usuario/{id}/bloquear')
    assert leitor.get('/').status_code == 302
    assert login(leitor,'leitor').status_code == 200
    post(admin,f'/usuario/{id}/desbloquear')
    assert login(leitor,'leitor').status_code == 302


def test_bloqueio_automatico_expiracao(app):
    cliente = app.test_client()
    for _ in range(5):
        assert login(cliente,'leitor','errada').status_code == 200
    assert login(cliente,'leitor').status_code == 200
    id,tentativas,ate = consultar(app,'SELECT ID_USUARIO,TENTATIVAS,BLOQUEADO_ATE FROM USUARIO WHERE PERFIL = ?',('leitor',))[0]
    assert tentativas == 5 and ate > time.time()
    with app.app_context():
        con = main.conectar(); cursor = con.cursor()
        cursor.execute('UPDATE USUARIO SET BLOQUEADO_ATE = ? WHERE ID_USUARIO = ?', (int(time.time())-1,id))
        con.commit(); cursor.close()
    login(cliente,'leitor','errada')
    assert consultar(app,'SELECT TENTATIVAS,BLOQUEADO_ATE FROM USUARIO WHERE ID_USUARIO = ?',(id,))[0] == (1,0)
    assert login(cliente,'leitor').status_code == 302


def test_cli_migracao_e_escape(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=['preparar-banco']).exit_code == 0
    assert runner.invoke(args=['criar-admin','--nome','Nicolas','--email','nicolas@example.com','--password',SENHA]).exit_code == 0
    cliente=app.test_client(); login(cliente)
    post(cliente,'/criar',{'nome':'<script>alert(1)</script>','autor':'Autor','ano':'2020'})
    assert b'&lt;script&gt;' in cliente.get('/').data
    post(cliente,'/sair')
    assert cliente.get('/').status_code == 302
