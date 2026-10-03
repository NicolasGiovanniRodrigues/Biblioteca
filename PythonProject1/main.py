import os
import re
import secrets
import time
from datetime import date, timedelta
from functools import wraps
from pathlib import Path

import click
import fdb
from flask import Flask, render_template, redirect, request, flash, url_for, session, g, abort
from flask_bcrypt import Bcrypt

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.environ.get('COOKIE_SECURE') == '1',
                  PERMANENT_SESSION_LIFETIME=timedelta(minutes=30), MAX_CONTENT_LENGTH=65536)
bcrypt = Bcrypt(app)

host = os.environ.get('FIREBIRD_HOST', 'localhost')
database = os.environ.get('FIREBIRD_DATABASE', str(Path(__file__).resolve().parent.parent / 'BANCO.FDB'))
user = os.environ.get('FIREBIRD_USER', 'SYSDBA')
password = os.environ.get('FIREBIRD_PASSWORD', '')
if os.environ.get('FIREBIRD_CLIENT'):
    fdb.load_api(os.environ['FIREBIRD_CLIENT'])


def conectar():
    """Uma conexão por requisição; as rotas usam cursor, commit e rollback."""
    if 'con' not in g:
        configuracao = dict(database=database, user=user, password=password, charset='UTF8')
        if host:
            configuracao['host'] = host
        g.con = fdb.connect(**configuracao)
    return g.con


@app.teardown_appcontext
def fechar_conexao(erro=None):
    con = g.pop('con', None)
    if con:
        con.close()


def csrf_token():
    if 'csrf_token' not in session:
        session['csrf_token'] = secrets.token_urlsafe(32)
    return session['csrf_token']


app.jinja_env.globals['csrf_token'] = csrf_token


def senha_forte(senha):
    if not 12 <= len(senha) <= 64 or len(senha.encode('utf-8')) > 72:
        raise ValueError('A senha deve ter de 12 a 64 caracteres e no máximo 72 bytes.')
    if not all(re.search(padrao, senha) for padrao in (r'[A-Z]', r'[a-z]', r'[0-9]', r'[^\w\s]')):
        raise ValueError('A senha precisa de maiúscula, minúscula, número e símbolo.')


def acesso(administrador=False):
    def decorar(funcao):
        @wraps(funcao)
        def verificar(*args, **kwargs):
            if not g.usuario:
                return redirect(url_for('login'))
            if administrador and g.usuario[4] != 'admin':
                abort(403)
            return funcao(*args, **kwargs)
        return verificar
    return decorar


@app.before_request
def verificar_sessao():
    g.usuario = None
    if session.get('id_usuario'):
        cursor = conectar().cursor()
        try:
            cursor.execute('SELECT ID_USUARIO, NOME, EMAIL, SENHA, PERFIL, BLOQUEADO, TENTATIVAS, BLOQUEADO_ATE, VERSAO_SESSAO FROM USUARIO WHERE ID_USUARIO = ?', (session['id_usuario'],))
            usuario = cursor.fetchone()
            if not usuario or usuario[5] or usuario[8] != session.get('versao'):
                session.clear()
            else:
                g.usuario = usuario
        finally:
            cursor.close()
    if request.method == 'POST':
        token = request.form.get('csrf_token', '')
        if not token or not secrets.compare_digest(token, session.get('csrf_token', '')):
            abort(400, description='Formulário expirado. Atualize a página.')


@app.after_request
def proteger_resposta(resposta):
    resposta.headers['X-Content-Type-Options'] = 'nosniff'
    resposta.headers['X-Frame-Options'] = 'DENY'
    resposta.headers['Cache-Control'] = 'no-store'
    return resposta


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        con = conectar()
        cursor = con.cursor()
        try:
            cursor.execute('SELECT ID_USUARIO, SENHA, BLOQUEADO, TENTATIVAS, BLOQUEADO_ATE, VERSAO_SESSAO FROM USUARIO WHERE EMAIL = ?', (email,))
            usuario = cursor.fetchone()
            agora = int(time.time())
            correta = False
            if usuario and len(senha.encode('utf-8')) <= 72:
                try:
                    correta = bcrypt.check_password_hash(usuario[1], senha)
                except ValueError:
                    correta = False
            if usuario and not usuario[2] and usuario[4] <= agora and correta:
                cursor.execute('UPDATE USUARIO SET TENTATIVAS = 0, BLOQUEADO_ATE = 0 WHERE ID_USUARIO = ?', (usuario[0],))
                con.commit()
                session.clear()
                session.update(id_usuario=usuario[0], versao=usuario[5])
                session.permanent = True
                return redirect(url_for('index'))
            if usuario and not usuario[2] and usuario[4] <= agora:
                cursor.execute('UPDATE USUARIO SET TENTATIVAS = CASE WHEN BLOQUEADO_ATE > 0 THEN 1 ELSE TENTATIVAS + 1 END, BLOQUEADO_ATE = 0 WHERE ID_USUARIO = ?', (usuario[0],))
                cursor.execute('UPDATE USUARIO SET BLOQUEADO_ATE = ?, VERSAO_SESSAO = VERSAO_SESSAO + 1 WHERE ID_USUARIO = ? AND TENTATIVAS >= 5 AND BLOQUEADO_ATE = 0', (agora + 900, usuario[0]))
                con.commit()
            flash('Não foi possível entrar. Confira os dados ou tente novamente em 15 minutos.')
        except fdb.DatabaseError:
            con.rollback()
            app.logger.exception('Falha no login')
            flash('Não foi possível acessar o banco de dados.')
        finally:
            cursor.close()
    return render_template('login.html')


@app.route('/sair', methods=['POST'])
def sair():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@acesso()
def index():
    con = conectar()
    cursor = con.cursor()
    try:
        cursor.execute('SELECT ID_LIVRO, NOME, AUTOR, DATAPUBLICACAO FROM LIVRO ORDER BY NOME')
        livros = cursor.fetchall()
        return render_template('livros.html', livros=livros)
    finally:
        cursor.close()


@app.route('/novo')
@acesso(administrador=True)
def novo():
    return render_template('novo.html', ano_maximo=date.today().year + 1)


def dados_livro():
    nome = request.form.get('nome', '').strip()
    autor = request.form.get('autor', '').strip()
    try:
        ano = int(request.form.get('ano', '0'))
    except ValueError:
        raise ValueError('Informe um ano válido.') from None
    if not nome or not autor or len(nome.encode('utf-8')) > 254 or len(autor.encode('utf-8')) > 254 or not 1 <= ano <= date.today().year + 1:
        raise ValueError('Confira nome, autor e ano do livro (textos de até 254 bytes).')
    return nome, autor, ano


@app.route('/criar', methods=['POST'])
@acesso(administrador=True)
def criar():
    con = conectar()
    cursor = con.cursor()
    try:
        nome, autor, ano = dados_livro()
        cursor.execute('SELECT 1 FROM LIVRO WHERE LOWER(NOME) = ?', (nome.lower(),))
        if cursor.fetchone():
            flash('Erro ao cadastrar o livro. Ele já existe.')
            return redirect(url_for('novo'))
        cursor.execute('INSERT INTO LIVRO (NOME, AUTOR, LIVRO, DATAPUBLICACAO) VALUES (?, ?, ?, ?)', (nome, autor, None, ano))
        con.commit()
        flash('Livro cadastrado com sucesso.')
        return redirect(url_for('index'))
    except ValueError as erro:
        con.rollback()
        flash(str(erro))
        return redirect(url_for('novo'))
    except fdb.DatabaseError:
        con.rollback()
        app.logger.exception('Falha ao cadastrar livro')
        flash('Ocorreu um erro ao cadastrar o livro.')
        return redirect(url_for('novo'))
    finally:
        cursor.close()


@app.route('/editar/<int:id>', methods=['GET', 'POST'])
@acesso(administrador=True)
def editar(id):
    con = conectar()
    cursor = con.cursor()
    try:
        cursor.execute('SELECT ID_LIVRO, NOME, AUTOR, DATAPUBLICACAO FROM LIVRO WHERE ID_LIVRO = ?', (id,))
        livro = cursor.fetchone()
        if not livro:
            abort(404)
        if request.method == 'POST':
            nome, autor, ano = dados_livro()
            cursor.execute('SELECT 1 FROM LIVRO WHERE LOWER(NOME) = ? AND ID_LIVRO <> ?', (nome.lower(), id))
            if cursor.fetchone():
                raise ValueError('Já existe um livro com esse nome.')
            cursor.execute('UPDATE LIVRO SET NOME = ?, AUTOR = ?, DATAPUBLICACAO = ? WHERE ID_LIVRO = ?', (nome, autor, ano, id))
            con.commit()
            flash('Livro atualizado com sucesso.')
            return redirect(url_for('index'))
        return render_template('editar.html', livro=livro, ano_maximo=date.today().year + 1)
    except ValueError as erro:
        con.rollback()
        flash(str(erro))
        return redirect(url_for('editar', id=id))
    except fdb.DatabaseError:
        con.rollback()
        app.logger.exception('Falha ao editar livro')
        flash('Ocorreu um erro ao editar o livro.')
        return redirect(url_for('index'))
    finally:
        cursor.close()


@app.route('/deletar/<int:id>', methods=['POST'])
@acesso(administrador=True)
def deletar(id):
    con = conectar()
    cursor = con.cursor()
    try:
        cursor.execute('SELECT ID_LIVRO FROM LIVRO WHERE ID_LIVRO = ?', (id,))
        if not cursor.fetchone():
            abort(404)
        cursor.execute('DELETE FROM LIVRO WHERE ID_LIVRO = ?', (id,))
        con.commit()
        flash('Livro deletado com sucesso.')
    except fdb.DatabaseError:
        con.rollback()
        app.logger.exception('Falha ao deletar livro')
        flash('Ocorreu um erro ao deletar o livro.')
    finally:
        cursor.close()
    return redirect(url_for('index'))


@app.route('/usuarios')
@acesso(administrador=True)
def usuarios():
    cursor = conectar().cursor()
    try:
        cursor.execute('SELECT ID_USUARIO, NOME, EMAIL, PERFIL, BLOQUEADO, BLOQUEADO_ATE FROM USUARIO ORDER BY NOME')
        return render_template('usuarios.html', usuarios=cursor.fetchall(), agora=int(time.time()))
    finally:
        cursor.close()


@app.route('/usuario/novo', methods=['GET', 'POST'])
@app.route('/usuario/editar/<int:id>', methods=['GET', 'POST'])
@acesso(administrador=True)
def usuario_formulario(id=None):
    con = conectar()
    cursor = con.cursor()
    usuario = None
    try:
        if id:
            cursor.execute('SELECT ID_USUARIO, NOME, EMAIL, PERFIL FROM USUARIO WHERE ID_USUARIO = ?', (id,))
            usuario = cursor.fetchone()
            if not usuario:
                abort(404)
        if request.method == 'POST':
            nome, email = request.form.get('nome', '').strip(), request.form.get('email', '').strip().lower()
            perfil, senha = request.form.get('perfil', 'leitor'), request.form.get('senha', '')
            if not nome or len(nome.encode('utf-8')) > 100 or len(email.encode('utf-8')) > 100 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email) or perfil not in ('admin', 'leitor'):
                raise ValueError('Confira nome, e-mail e perfil (nome e e-mail até 100 bytes).')
            if id == g.usuario[0] and perfil != 'admin':
                raise ValueError('Você não pode remover seu próprio perfil de administrador.')
            cursor.execute('SELECT 1 FROM USUARIO WHERE EMAIL = ? AND ID_USUARIO <> ?', (email, id or 0))
            if cursor.fetchone():
                raise ValueError('E-mail já cadastrado.')
            if senha or not id:
                senha_forte(senha)
            if id:
                cursor.execute('UPDATE USUARIO SET NOME = ?, EMAIL = ?, PERFIL = ?, VERSAO_SESSAO = VERSAO_SESSAO + 1 WHERE ID_USUARIO = ?', (nome, email, perfil, id))
                if senha:
                    cursor.execute('UPDATE USUARIO SET SENHA = ? WHERE ID_USUARIO = ?', (bcrypt.generate_password_hash(senha).decode(), id))
            else:
                cursor.execute('INSERT INTO USUARIO (NOME, EMAIL, SENHA, PERFIL) VALUES (?, ?, ?, ?)', (nome, email, bcrypt.generate_password_hash(senha).decode(), perfil))
            con.commit()
            flash('Usuário salvo com sucesso.')
            return redirect(url_for('usuarios'))
        return render_template('usuario_formulario.html', usuario=usuario, editando=bool(id))
    except ValueError as erro:
        con.rollback()
        flash(str(erro))
        usuario = (id, request.form.get('nome', ''), request.form.get('email', ''), request.form.get('perfil', 'leitor'))
        return render_template('usuario_formulario.html', usuario=usuario, editando=bool(id))
    except fdb.DatabaseError:
        con.rollback()
        app.logger.exception('Falha ao salvar usuário')
        flash('Ocorreu um erro ao salvar o usuário.')
        return redirect(url_for('usuarios'))
    finally:
        cursor.close()


@app.route('/usuario/<int:id>/<acao>', methods=['POST'])
@acesso(administrador=True)
def usuario_acao(id, acao):
    if acao not in ('bloquear', 'desbloquear', 'deletar'):
        abort(404)
    if id == g.usuario[0]:
        flash('Você não pode bloquear ou excluir a própria conta.')
        return redirect(url_for('usuarios'))
    con = conectar()
    cursor = con.cursor()
    try:
        cursor.execute('SELECT ID_USUARIO FROM USUARIO WHERE ID_USUARIO = ?', (id,))
        if not cursor.fetchone():
            abort(404)
        if acao == 'deletar':
            cursor.execute('DELETE FROM USUARIO WHERE ID_USUARIO = ?', (id,))
        else:
            cursor.execute('UPDATE USUARIO SET BLOQUEADO = ?, TENTATIVAS = 0, BLOQUEADO_ATE = 0, VERSAO_SESSAO = VERSAO_SESSAO + 1 WHERE ID_USUARIO = ?', (int(acao == 'bloquear'), id))
        con.commit()
        flash('Usuário atualizado com sucesso.')
    except fdb.DatabaseError:
        con.rollback()
        app.logger.exception('Falha ao alterar usuário')
        flash('Ocorreu um erro ao alterar o usuário.')
    finally:
        cursor.close()
    return redirect(url_for('usuarios'))


@app.cli.command('preparar-banco')
def preparar_banco():
    """Atualiza USUARIO sem alterar os livros do banco fornecido."""
    con = conectar()
    cursor = con.cursor()
    try:
        cursor.execute("SELECT TRIM(RDB$FIELD_NAME) FROM RDB$RELATION_FIELDS WHERE RDB$RELATION_NAME = 'USUARIO'")
        campos = {linha[0] for linha in cursor.fetchall()}
        if not {'ID_USUARIO', 'NOME', 'EMAIL', 'SENHA'} <= campos:
            raise click.ClickException('O banco não corresponde ao modelo da professora.')
        cursor.execute('ALTER TABLE USUARIO ALTER SENHA TYPE VARCHAR(100)')
        for campo, tipo in [('PERFIL', "VARCHAR(10) DEFAULT 'leitor' NOT NULL"), ('BLOQUEADO', 'SMALLINT DEFAULT 0 NOT NULL'), ('TENTATIVAS', 'INTEGER DEFAULT 0 NOT NULL'), ('BLOQUEADO_ATE', 'BIGINT DEFAULT 0 NOT NULL'), ('VERSAO_SESSAO', 'INTEGER DEFAULT 0 NOT NULL')]:
            if campo not in campos:
                cursor.execute(f'ALTER TABLE USUARIO ADD {campo} {tipo}')
        con.commit()
        cursor.execute("SELECT 1 FROM RDB$INDICES WHERE RDB$INDEX_NAME = 'UX_USUARIO_EMAIL'")
        if not cursor.fetchone():
            cursor.execute('CREATE UNIQUE INDEX UX_USUARIO_EMAIL ON USUARIO (EMAIL)')
            con.commit()
        click.echo('Banco preparado. Livros preservados e usuários prontos para Bcrypt.')
    except fdb.DatabaseError as erro:
        con.rollback()
        raise click.ClickException('Não foi possível preparar o banco. Confira a instalação e faça backup antes de migrar.') from erro
    finally:
        cursor.close()


@app.cli.command('criar-admin')
@click.option('--nome', prompt='Nome')
@click.option('--email', prompt='E-mail')
@click.password_option(prompt='Senha')
def criar_admin(nome, email, password):
    try:
        senha_forte(password)
    except ValueError as erro:
        raise click.ClickException(str(erro)) from erro
    email = email.strip().lower()
    if not nome.strip() or len(nome.encode('utf-8')) > 100 or len(email.encode('utf-8')) > 100 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise click.ClickException('Nome ou e-mail inválido.')
    con = conectar()
    cursor = con.cursor()
    try:
        cursor.execute('INSERT INTO USUARIO (NOME, EMAIL, SENHA, PERFIL) VALUES (?, ?, ?, ?)', (nome.strip(), email, bcrypt.generate_password_hash(password).decode(), 'admin'))
        con.commit()
        click.echo('Administrador cadastrado.')
    except fdb.DatabaseError as erro:
        con.rollback()
        raise click.ClickException('Não foi possível cadastrar: confira se o e-mail já existe ou se o banco foi preparado.') from erro
    finally:
        cursor.close()


@app.errorhandler(400)
@app.errorhandler(403)
@app.errorhandler(404)
def erro_pagina(erro):
    return render_template('erro.html', erro=erro), erro.code


if __name__ == '__main__':
    app.run(debug=False)
