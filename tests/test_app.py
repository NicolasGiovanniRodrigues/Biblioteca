import time
import pytest
from biblioteca import bcrypt, create_app, validate_password
from biblioteca.db import execute, init_db, query

PASSWORD = 'Biblioteca!2026'


@pytest.fixture
def app(tmp_path):
    app = create_app({'TESTING': True, 'SECRET_KEY': 'test-key', 'DATABASE': str(tmp_path / 'test.db'), 'DB_ENGINE': 'sqlite', 'BCRYPT_LOG_ROUNDS': 4})
    with app.app_context():
        init_db()
        for role in ('admin', 'user'):
            execute('INSERT INTO users (name, email, role, password_hash) VALUES (?, ?, ?, ?)', (role, role + '@example.com', role, bcrypt.generate_password_hash(PASSWORD).decode()))
    return app


def post(client, path, data=None):
    with client.session_transaction() as session:
        session.setdefault('csrf', 'test-token')
        token = session['csrf']
    return client.post(path, data={**(data or {}), 'csrf_token': token})


def login(client, role='admin', password=PASSWORD):
    return post(client, '/login', {'email': role + '@example.com', 'password': password})


def test_book_crud_and_validation(app):
    client = app.test_client()
    assert login(client).status_code == 302
    assert post(client, '/livros/novo', {'title': 'Dom Casmurro', 'author': 'Machado de Assis', 'publication_year': '1899'}).status_code == 302
    assert b'Dom Casmurro' in client.get('/?q=machado').data
    with app.app_context():
        book_id = query('SELECT id FROM books', one=True)['id']
    assert client.get(f'/livros/{book_id}/editar').status_code == 200
    post(client, f'/livros/{book_id}/editar', {'title': 'Memórias', 'author': 'Machado', 'publication_year': '1881'})
    post(client, '/livros/novo', {'title': 'Memórias', 'author': 'Outro', 'publication_year': '2000'})
    post(client, '/livros/novo', {'title': 'Inválido', 'author': 'Autor', 'publication_year': '-2'})
    with app.app_context():
        assert len(query('SELECT * FROM books')) == 1
    assert post(client, f'/livros/{book_id}/excluir').status_code == 302
    assert post(client, f'/livros/{book_id}/excluir').status_code == 404
    with app.app_context():
        assert query('SELECT * FROM books') == []


@pytest.mark.parametrize('password', ['curta', 'abcdefghijkl', 'ABCDEFGHIJKL', 'Abcdefgh1234', 'Abcdefgh!!!!', 'A1!' + 'é' * 36])
def test_weak_passwords(password):
    with pytest.raises(ValueError):
        validate_password(password)


def test_user_crud_hash_and_sessions(app):
    client = app.test_client()
    login(client)
    payload = {'name': 'Ana', 'email': 'ana@example.com', 'role': 'user', 'password': 'fraca'}
    assert post(client, '/usuarios/novo', payload).status_code == 200
    payload['password'] = PASSWORD
    assert post(client, '/usuarios/novo', payload).status_code == 302
    with app.app_context():
        user = query('SELECT * FROM users WHERE email = ?', ('ana@example.com',), one=True)
        assert user['password_hash'] != PASSWORD
        assert user['password_hash'].startswith('$2b$')
        assert bcrypt.check_password_hash(user['password_hash'], PASSWORD)
    uid = user['id']
    reader = app.test_client()
    assert post(reader, '/login', {'email': 'ana@example.com', 'password': PASSWORD}).status_code == 302
    assert client.get('/usuarios').status_code == 200
    assert client.get(f'/usuarios/{uid}/editar').status_code == 200
    payload.update(name='Ana Maria', password='OutraSenha!2026')
    assert post(client, f'/usuarios/{uid}/editar', payload).status_code == 302
    assert reader.get('/').status_code == 302
    assert post(reader, '/login', {'email': 'ana@example.com', 'password': PASSWORD}).status_code == 200
    assert post(reader, '/login', {'email': 'ana@example.com', 'password': payload['password']}).status_code == 302
    post(client, f'/usuarios/{uid}/excluir')
    assert reader.get('/').status_code == 302
    with app.app_context():
        assert query('SELECT id FROM users WHERE id = ?', (uid,), one=True) is None


def test_permissions_csrf_and_self_protection(app):
    client = app.test_client()
    assert client.get('/').status_code == 302
    assert client.post('/login', data={'email': 'admin@example.com', 'password': PASSWORD}).status_code == 400
    login(client, 'user')
    for path in ['/usuarios', '/usuarios/novo', '/livros/novo']:
        assert client.get(path).status_code == 403
    assert post(client, '/livros/1/excluir').status_code == 403
    login(client)
    with app.app_context():
        uid = query('SELECT id FROM users WHERE role = ?', ('admin',), one=True)['id']
    post(client, f'/usuarios/{uid}/bloquear')
    post(client, f'/usuarios/{uid}/excluir')
    post(client, f'/usuarios/{uid}/editar', {'name': 'Admin', 'email': 'admin@example.com', 'role': 'user', 'password': ''})
    with app.app_context():
        user = query('SELECT * FROM users WHERE id = ?', (uid,), one=True)
        assert user['role'] == 'admin' and not user['blocked']
    assert client.get('/livros/999/editar').status_code == 404
    assert client.get('/livros/1/excluir').status_code == 405


def test_manual_block_and_unlock(app):
    admin, reader = app.test_client(), app.test_client()
    login(admin)
    login(reader, 'user')
    with app.app_context():
        uid = query('SELECT id FROM users WHERE role = ?', ('user',), one=True)['id']
    post(admin, f'/usuarios/{uid}/bloquear')
    assert reader.get('/').status_code == 302
    assert login(reader, 'user').status_code == 200
    post(admin, f'/usuarios/{uid}/desbloquear')
    assert login(reader, 'user').status_code == 302


def test_automatic_lock_expiry_and_long_input(app):
    client = app.test_client()
    for _ in range(5):
        assert login(client, 'user', 'errada').status_code == 200
    assert login(client, 'user').status_code == 200
    with app.app_context():
        user = query('SELECT * FROM users WHERE role = ?', ('user',), one=True)
        assert user['failed_attempts'] == 5 and user['locked_until'] > time.time()
        execute('UPDATE users SET locked_until = ? WHERE id = ?', (int(time.time()) - 1, user['id']))
    assert login(client, 'user', 'errada').status_code == 200
    with app.app_context():
        user = query('SELECT * FROM users WHERE role = ?', ('user',), one=True)
        assert user['failed_attempts'] == 1 and user['locked_until'] == 0
    assert login(client, 'user').status_code == 302
    assert login(client, 'user', 'x' * 200).status_code == 200


def test_cli_and_escaping(app):
    runner = app.test_cli_runner()
    assert runner.invoke(args=['create-admin', '--name', 'Nicolas', '--email', 'nicolas@example.com', '--password', PASSWORD]).exit_code == 0
    client = app.test_client()
    login(client)
    post(client, '/livros/novo', {'title': '<script>alert(1)</script>', 'author': "Autor'", 'publication_year': '2020'})
    response = client.get('/')
    assert b'&lt;script&gt;' in response.data
    assert b'<script>alert(1)</script>' not in response.data
    assert 'Content-Security-Policy' in response.headers
    post(client, '/logout')
    assert client.get('/').status_code == 302
