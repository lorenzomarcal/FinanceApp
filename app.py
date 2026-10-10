from __future__ import annotations

import logging
import os
import secrets
import sqlite3
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from typing import Any, Callable, Iterator, TypeVar

import requests
from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash


# =========================================================
# CONFIGURAÇÃO
# =========================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "banco.db")
ENV_PATH = os.path.join(BASE_DIR, ".env")

load_dotenv(ENV_PATH)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("SECRET_KEY", secrets.token_hex(32)),
    DATABASE=DB_PATH,
    BRAPI_TOKEN=os.getenv("BRAPI_TOKEN", "").strip(),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("FLASK_ENV") == "production",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

HTTP = requests.Session()
HTTP.headers.update({"User-Agent": "FinanceDashboard/1.0"})


# =========================================================
# TIPAGEM AUXILIAR
# =========================================================

F = TypeVar("F", bound=Callable[..., Any])


# =========================================================
# BANCO DE DADOS
# =========================================================

def get_db() -> sqlite3.Connection:
    """Retorna uma conexão SQLite válida durante a requisição atual."""
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")

    return g.db


@app.teardown_appcontext
def close_db(_error: BaseException | None = None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """Executa uma operação de banco com commit/rollback automático."""
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def init_db() -> None:
    """Cria as tabelas usadas pela versão autenticada do sistema."""
    db = sqlite3.connect(app.config["DATABASE"])
    db.execute("PRAGMA foreign_keys = ON")

    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE COLLATE NOCASE,
            senha_hash TEXT NOT NULL,
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS movimentacoes_usuario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            tipo TEXT NOT NULL CHECK (tipo IN ('ganho', 'gasto')),
            descricao TEXT NOT NULL,
            categoria TEXT NOT NULL,
            valor REAL NOT NULL CHECK (valor > 0),
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_movimentacoes_usuario
        ON movimentacoes_usuario(usuario_id, id DESC);

        CREATE TABLE IF NOT EXISTS cofrinho_usuario (
            usuario_id INTEGER PRIMARY KEY,
            valor REAL NOT NULL DEFAULT 0 CHECK (valor >= 0),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS investimentos_usuario (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            tipo TEXT NOT NULL,
            quantidade REAL NOT NULL CHECK (quantidade > 0),
            preco_medio REAL NOT NULL CHECK (preco_medio >= 0),
            criado_em TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (usuario_id, ticker),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_investimentos_usuario
        ON investimentos_usuario(usuario_id, ticker);
        """
    )

    db.commit()
    db.close()


init_db()


# =========================================================
# AUTENTICAÇÃO / SESSÃO
# =========================================================

def login_required(view: F) -> F:
    @wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any):
        if session.get("usuario_id") is None:
            flash("Faça login para continuar.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view  # type: ignore[return-value]


@app.before_request
def load_logged_user() -> None:
    usuario_id = session.get("usuario_id")

    if usuario_id is None:
        g.usuario = None
        return

    g.usuario = get_db().execute(
        "SELECT id, nome, criado_em FROM usuarios WHERE id = ?",
        (usuario_id,),
    ).fetchone()

    if g.usuario is None:
        session.clear()


def validar_nome_usuario(nome: str) -> str | None:
    nome = nome.strip()

    if len(nome) < 3:
        return "O nome de usuário precisa ter pelo menos 3 caracteres."

    if len(nome) > 30:
        return "O nome de usuário pode ter no máximo 30 caracteres."

    if not all(c.isalnum() or c in "._-" for c in nome):
        return "Use apenas letras, números, ponto, hífen ou underline no usuário."

    return None


def validar_senha(senha: str) -> str | None:
    if len(senha) < 8:
        return "A senha precisa ter pelo menos 8 caracteres."

    if len(senha) > 128:
        return "A senha é muito longa."

    return None


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if g.usuario is not None:
        return redirect(url_for("inicio"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "")
        confirmar_senha = request.form.get("confirmar_senha", "")

        erro = validar_nome_usuario(nome)
        if erro:
            flash(erro, "danger")
            return render_template("cadastro.html", nome=nome)

        erro = validar_senha(senha)
        if erro:
            flash(erro, "danger")
            return render_template("cadastro.html", nome=nome)

        if senha != confirmar_senha:
            flash("As senhas não coincidem.", "danger")
            return render_template("cadastro.html", nome=nome)

        senha_hash = generate_password_hash(senha)

        try:
            with transaction() as db:
                cursor = db.execute(
                    "INSERT INTO usuarios (nome, senha_hash) VALUES (?, ?)",
                    (nome, senha_hash),
                )
                usuario_id = cursor.lastrowid
                db.execute(
                    "INSERT INTO cofrinho_usuario (usuario_id, valor) VALUES (?, 0)",
                    (usuario_id,),
                )
        except sqlite3.IntegrityError:
            flash("Esse nome de usuário já existe.", "danger")
            return render_template("cadastro.html", nome=nome)

        flash("Conta criada com sucesso. Faça seu login.", "success")
        return redirect(url_for("login"))

    return render_template("cadastro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario is not None:
        return redirect(url_for("inicio"))

    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        senha = request.form.get("senha", "")

        usuario = get_db().execute(
            "SELECT id, nome, senha_hash FROM usuarios WHERE nome = ? COLLATE NOCASE",
            (nome,),
        ).fetchone()

        if usuario is None or not check_password_hash(usuario["senha_hash"], senha):
            flash("Usuário ou senha incorretos.", "danger")
            return render_template("login.html", nome=nome)

        session.clear()
        session["usuario_id"] = usuario["id"]
        session.permanent = True

        flash(f"Bem-vindo, {usuario['nome']}!", "success")
        return redirect(url_for("inicio"))

    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    flash("Você saiu da sua conta.", "info")
    return redirect(url_for("login"))


@app.route("/perfil", methods=["GET", "POST"])
@login_required
def perfil():
    if request.method == "POST":
        acao = request.form.get("acao", "")

        if acao == "alterar_nome":
            novo_nome = request.form.get("novo_nome", "").strip()
            erro = validar_nome_usuario(novo_nome)

            if erro:
                flash(erro, "danger")
            else:
                try:
                    with transaction() as db:
                        db.execute(
                            "UPDATE usuarios SET nome = ? WHERE id = ?",
                            (novo_nome, g.usuario["id"]),
                        )
                    flash("Nome de usuário alterado com sucesso.", "success")
                except sqlite3.IntegrityError:
                    flash("Esse nome de usuário já está em uso.", "danger")

        elif acao == "alterar_senha":
            senha_atual = request.form.get("senha_atual", "")
            nova_senha = request.form.get("nova_senha", "")
            confirmar = request.form.get("confirmar_senha", "")

            usuario = get_db().execute(
                "SELECT senha_hash FROM usuarios WHERE id = ?",
                (g.usuario["id"],),
            ).fetchone()

            if not check_password_hash(usuario["senha_hash"], senha_atual):
                flash("A senha atual está incorreta.", "danger")
            elif nova_senha != confirmar:
                flash("A confirmação da nova senha não coincide.", "danger")
            else:
                erro = validar_senha(nova_senha)
                if erro:
                    flash(erro, "danger")
                else:
                    with transaction() as db:
                        db.execute(
                            "UPDATE usuarios SET senha_hash = ? WHERE id = ?",
                            (generate_password_hash(nova_senha), g.usuario["id"]),
                        )
                    flash("Senha alterada com sucesso.", "success")

        else:
            flash("Ação inválida.", "danger")

        return redirect(url_for("perfil"))

    return render_template("perfil.html", usuario=g.usuario)


# =========================================================
# FORMATAÇÃO E VALIDAÇÃO
# =========================================================

@app.template_filter("brl")
def formatar_brl(valor: Any) -> str:
    try:
        numero = Decimal(str(valor)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError, ValueError):
        numero = Decimal("0.00")

    resultado = f"{numero:,.2f}"
    return resultado.replace(",", "X").replace(".", ",").replace("X", ".")


def converter_valor(valor: str) -> float:
    texto = (valor or "").strip().replace("R$", "").replace(" ", "")

    if not texto:
        raise ValueError("Valor vazio.")

    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")

    try:
        numero = Decimal(texto)
    except InvalidOperation as exc:
        raise ValueError("Valor inválido.") from exc

    numero = numero.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(numero)


def converter_quantidade(valor: str) -> float:
    try:
        quantidade = Decimal((valor or "").strip().replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Quantidade inválida.") from exc

    if quantidade <= 0:
        raise ValueError("A quantidade deve ser maior que zero.")

    return float(quantidade)


def usuario_id() -> int:
    return int(g.usuario["id"])


# =========================================================
# FINANÇAS
# =========================================================

def calcular_totais() -> tuple[float, float, float, float]:
    uid = usuario_id()
    db = get_db()

    ganhos = db.execute(
        """
        SELECT COALESCE(SUM(valor), 0)
        FROM movimentacoes_usuario
        WHERE usuario_id = ? AND tipo = 'ganho'
        """,
        (uid,),
    ).fetchone()[0]

    gastos = db.execute(
        """
        SELECT COALESCE(SUM(valor), 0)
        FROM movimentacoes_usuario
        WHERE usuario_id = ? AND tipo = 'gasto'
        """,
        (uid,),
    ).fetchone()[0]

    reserva_row = db.execute(
        "SELECT valor FROM cofrinho_usuario WHERE usuario_id = ?",
        (uid,),
    ).fetchone()

    reserva = float(reserva_row["valor"] if reserva_row else 0)
    ganhos = round(float(ganhos), 2)
    gastos = round(float(gastos), 2)
    reserva = round(reserva, 2)
    saldo = round(ganhos - gastos - reserva, 2)

    if abs(saldo) < 0.01:
        saldo = 0.0

    return ganhos, gastos, reserva, saldo


@app.route("/")
@login_required
def inicio():
    movimentacoes = get_db().execute(
        """
        SELECT id, tipo, descricao, categoria, valor, criado_em
        FROM movimentacoes_usuario
        WHERE usuario_id = ?
        ORDER BY id DESC
        """,
        (usuario_id(),),
    ).fetchall()

    ganhos, gastos, reserva, saldo = calcular_totais()

    return render_template(
        "index.html",
        movimentacoes=movimentacoes,
        ganhos=ganhos,
        gastos=gastos,
        saldo=saldo,
        cofrinho=reserva,
        usuario=g.usuario,
    )


@app.post("/adicionar")
@login_required
def adicionar():
    tipo = request.form.get("tipo", "").strip().lower()
    descricao = request.form.get("descricao", "").strip()
    categoria = request.form.get("categoria", "").strip()

    if tipo not in {"ganho", "gasto"}:
        flash("Tipo de movimentação inválido.", "danger")
        return redirect(url_for("inicio"))

    if not descricao or len(descricao) > 100:
        flash("Informe uma descrição válida.", "danger")
        return redirect(url_for("inicio"))

    if not categoria or len(categoria) > 50:
        flash("Informe uma categoria válida.", "danger")
        return redirect(url_for("inicio"))

    try:
        valor = converter_valor(request.form.get("valor", ""))
    except ValueError:
        flash("Informe um valor válido.", "danger")
        return redirect(url_for("inicio"))

    if valor <= 0:
        flash("O valor deve ser maior que zero.", "danger")
        return redirect(url_for("inicio"))

    with transaction() as db:
        db.execute(
            """
            INSERT INTO movimentacoes_usuario
            (usuario_id, tipo, descricao, categoria, valor)
            VALUES (?, ?, ?, ?, ?)
            """,
            (usuario_id(), tipo, descricao, categoria, valor),
        )

    flash("Movimentação adicionada.", "success")
    return redirect(url_for("inicio"))


@app.post("/cofrinho")
@login_required
def adicionar_reserva():
    try:
        valor = converter_valor(request.form.get("valor_cofrinho", ""))
    except ValueError:
        flash("Informe um valor válido.", "danger")
        return redirect(url_for("inicio"))

    if valor <= 0:
        flash("O valor deve ser maior que zero.", "danger")
        return redirect(url_for("inicio"))

    _ganhos, _gastos, reserva, saldo = calcular_totais()

    if valor > saldo:
        flash("Saldo insuficiente para guardar esse valor.", "danger")
        return redirect(url_for("inicio"))

    nova_reserva = round(reserva + valor, 2)

    with transaction() as db:
        db.execute(
            """
            INSERT INTO cofrinho_usuario (usuario_id, valor)
            VALUES (?, ?)
            ON CONFLICT(usuario_id) DO UPDATE SET valor = excluded.valor
            """,
            (usuario_id(), nova_reserva),
        )

    flash("Valor guardado na reserva.", "success")
    return redirect(url_for("inicio"))


@app.post("/retirar_cofrinho")
@login_required
def retirar_reserva():
    try:
        valor = converter_valor(request.form.get("valor_retirar", ""))
    except ValueError:
        flash("Informe um valor válido.", "danger")
        return redirect(url_for("inicio"))

    if valor <= 0:
        flash("O valor deve ser maior que zero.", "danger")
        return redirect(url_for("inicio"))

    db = get_db()
    row = db.execute(
        "SELECT valor FROM cofrinho_usuario WHERE usuario_id = ?",
        (usuario_id(),),
    ).fetchone()

    reserva_atual = round(float(row["valor"] if row else 0), 2)

    if valor > reserva_atual:
        flash("Você não possui esse valor na reserva.", "danger")
        return redirect(url_for("inicio"))

    nova_reserva = round(reserva_atual - valor, 2)

    with transaction() as db:
        db.execute(
            """
            INSERT INTO cofrinho_usuario (usuario_id, valor)
            VALUES (?, ?)
            ON CONFLICT(usuario_id) DO UPDATE SET valor = excluded.valor
            """,
            (usuario_id(), max(nova_reserva, 0.0)),
        )

    flash("Valor retirado da reserva.", "success")
    return redirect(url_for("inicio"))


@app.post("/excluir/<int:movimentacao_id>")
@login_required
def excluir(movimentacao_id: int):
    with transaction() as db:
        cursor = db.execute(
            "DELETE FROM movimentacoes_usuario WHERE id = ? AND usuario_id = ?",
            (movimentacao_id, usuario_id()),
        )

    if cursor.rowcount:
        flash("Movimentação excluída.", "success")
    else:
        flash("Movimentação não encontrada.", "warning")

    return redirect(url_for("inicio"))


# =========================================================
# BRAPI
# =========================================================

def headers_brapi() -> dict[str, str]:
    token = app.config["BRAPI_TOKEN"]
    return {"Authorization": f"Bearer {token}"} if token else {}


def buscar_mercado(tipo: str, pesquisa: str) -> list[dict[str, Any]]:
    if not app.config["BRAPI_TOKEN"]:
        return []

    parametros: dict[str, Any] = {
        "sortBy": "volume",
        "sortOrder": "desc",
        "limit": 30,
    }

    if tipo == "fiis":
        parametros.update({"type": "fund", "subType": "fii"})
    else:
        parametros.update({"type": "stock", "subType": "stock"})

    if pesquisa:
        parametros["search"] = pesquisa

    try:
        resposta = HTTP.get(
            "https://brapi.dev/api/quote/list",
            headers=headers_brapi(),
            params=parametros,
            timeout=8,
        )
        resposta.raise_for_status()
        dados = resposta.json()
        return dados.get("stocks", [])
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Falha ao buscar mercado na BRAPI: %s", exc)
        return []


def buscar_cotacao(ticker: str) -> dict[str, float] | None:
    if not app.config["BRAPI_TOKEN"]:
        return None

    ticker = ticker.strip().upper()
    if not ticker:
        return None

    try:
        resposta = HTTP.get(
            f"https://brapi.dev/api/quote/{ticker}",
            headers=headers_brapi(),
            timeout=8,
        )
        resposta.raise_for_status()
        resultados = resposta.json().get("results", [])

        if not resultados:
            return None

        ativo = resultados[0]
        preco = ativo.get("regularMarketPrice")
        variacao = ativo.get("regularMarketChangePercent", 0)

        if preco is None:
            return None

        return {
            "preco": float(preco),
            "variacao": float(variacao or 0),
        }
    except (requests.RequestException, ValueError, TypeError) as exc:
        logger.warning("Falha ao buscar cotação de %s: %s", ticker, exc)
        return None


# =========================================================
# INVESTIMENTOS
# =========================================================

@app.route("/investimentos")
@login_required
def investimentos():
    tipo = request.args.get("tipo", "acoes").strip().lower()
    pesquisa = request.args.get("pesquisa", "").strip()[:40]

    if tipo not in {"acoes", "fiis"}:
        tipo = "acoes"

    mercado = buscar_mercado(tipo, pesquisa)

    carteira_banco = get_db().execute(
        """
        SELECT id, ticker, tipo, quantidade, preco_medio
        FROM investimentos_usuario
        WHERE usuario_id = ?
        ORDER BY ticker
        """,
        (usuario_id(),),
    ).fetchall()

    carteira: list[dict[str, Any]] = []
    total_investido = 0.0
    patrimonio = 0.0

    for ativo in carteira_banco:
        ticker = ativo["ticker"]
        quantidade = float(ativo["quantidade"])
        preco_medio = float(ativo["preco_medio"])

        cotacao = buscar_cotacao(ticker)
        preco_atual = float(cotacao["preco"]) if cotacao else preco_medio
        variacao = float(cotacao["variacao"]) if cotacao else 0.0

        investido = round(quantidade * preco_medio, 2)
        valor_atual = round(quantidade * preco_atual, 2)
        resultado = round(valor_atual - investido, 2)
        resultado_percentual = (resultado / investido * 100) if investido > 0 else 0.0

        total_investido += investido
        patrimonio += valor_atual

        carteira.append(
            {
                "id": ativo["id"],
                "ticker": ticker,
                "tipo": ativo["tipo"],
                "quantidade": quantidade,
                "preco_medio": preco_medio,
                "preco_atual": preco_atual,
                "variacao": variacao,
                "investido": investido,
                "valor_atual": valor_atual,
                "resultado": resultado,
                "resultado_percentual": resultado_percentual,
            }
        )

    total_investido = round(total_investido, 2)
    patrimonio = round(patrimonio, 2)
    resultado_total = round(patrimonio - total_investido, 2)
    rentabilidade = (resultado_total / total_investido * 100) if total_investido > 0 else 0.0

    _ganhos, _gastos, _reserva, saldo = calcular_totais()

    return render_template(
        "investimentos.html",
        mercado=mercado,
        carteira=carteira,
        tipo=tipo,
        pesquisa=pesquisa,
        total_investido=total_investido,
        patrimonio=patrimonio,
        resultado_total=resultado_total,
        rentabilidade=rentabilidade,
        saldo=saldo,
        api_configurada=bool(app.config["BRAPI_TOKEN"]),
        usuario=g.usuario,
    )


def processar_compra(ticker: str, tipo: str, quantidade: float) -> None:
    cotacao = buscar_cotacao(ticker)
    if not cotacao:
        raise ValueError("Não foi possível obter a cotação atual.")

    preco_atual = float(cotacao["preco"])
    valor_compra = round(quantidade * preco_atual, 2)

    with transaction() as db:
        existente = db.execute(
            """
            SELECT id, quantidade, preco_medio
            FROM investimentos_usuario
            WHERE usuario_id = ? AND ticker = ?
            """,
            (usuario_id(), ticker),
        ).fetchone()

        if existente:
            quantidade_antiga = float(existente["quantidade"])
            preco_antigo = float(existente["preco_medio"])
            nova_quantidade = quantidade_antiga + quantidade
            novo_preco_medio = (
                (quantidade_antiga * preco_antigo) + (quantidade * preco_atual)
            ) / nova_quantidade

            db.execute(
                """
                UPDATE investimentos_usuario
                SET quantidade = ?, preco_medio = ?, tipo = ?
                WHERE id = ? AND usuario_id = ?
                """,
                (
                    nova_quantidade,
                    round(novo_preco_medio, 6),
                    tipo,
                    existente["id"],
                    usuario_id(),
                ),
            )
        else:
            db.execute(
                """
                INSERT INTO investimentos_usuario
                (usuario_id, ticker, tipo, quantidade, preco_medio)
                VALUES (?, ?, ?, ?, ?)
                """,
                (usuario_id(), ticker, tipo, quantidade, preco_atual),
            )

        db.execute(
            """
            INSERT INTO movimentacoes_usuario
            (usuario_id, tipo, descricao, categoria, valor)
            VALUES (?, 'gasto', ?, 'Investimentos', ?)
            """,
            (usuario_id(), f"Compra {ticker}", valor_compra),
        )


@app.post("/investimentos/adicionar")
@login_required
def adicionar_investimento():
    ticker = request.form.get("ticker", "").strip().upper()
    tipo = request.form.get("tipo", "").strip().lower()

    if not ticker or len(ticker) > 15:
        flash("Ticker inválido.", "danger")
        return redirect(url_for("investimentos"))

    if tipo not in {"acao", "ações", "acoes", "fii", "fiis"}:
        tipo = "acao"

    try:
        quantidade = converter_quantidade(request.form.get("quantidade", ""))
        processar_compra(ticker, tipo, quantidade)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("investimentos"))

    flash(f"Compra de {ticker} registrada com sucesso.", "success")
    return redirect(url_for("investimentos"))


@app.post("/investimentos/comprar")
@login_required
def comprar_investimento():
    return adicionar_investimento()


@app.post("/investimentos/vender")
@login_required
def vender_investimento():
    ticker = request.form.get("ticker", "").strip().upper()

    try:
        quantidade_venda = converter_quantidade(request.form.get("quantidade", ""))
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("investimentos"))

    db = get_db()
    ativo = db.execute(
        """
        SELECT id, quantidade
        FROM investimentos_usuario
        WHERE usuario_id = ? AND ticker = ?
        """,
        (usuario_id(), ticker),
    ).fetchone()

    if ativo is None:
        flash("Esse ativo não existe na sua carteira.", "danger")
        return redirect(url_for("investimentos"))

    quantidade_atual = float(ativo["quantidade"])

    if quantidade_venda > quantidade_atual:
        flash("Você não possui essa quantidade para vender.", "danger")
        return redirect(url_for("investimentos"))

    cotacao = buscar_cotacao(ticker)
    if not cotacao:
        flash("Não foi possível obter a cotação atual.", "danger")
        return redirect(url_for("investimentos"))

    preco_atual = float(cotacao["preco"])
    valor_venda = round(quantidade_venda * preco_atual, 2)
    nova_quantidade = round(quantidade_atual - quantidade_venda, 6)

    with transaction() as db:
        if nova_quantidade <= 0:
            db.execute(
                "DELETE FROM investimentos_usuario WHERE id = ? AND usuario_id = ?",
                (ativo["id"], usuario_id()),
            )
        else:
            db.execute(
                """
                UPDATE investimentos_usuario
                SET quantidade = ?
                WHERE id = ? AND usuario_id = ?
                """,
                (nova_quantidade, ativo["id"], usuario_id()),
            )

        db.execute(
            """
            INSERT INTO movimentacoes_usuario
            (usuario_id, tipo, descricao, categoria, valor)
            VALUES (?, 'ganho', ?, 'Investimentos', ?)
            """,
            (usuario_id(), f"Venda {ticker}", valor_venda),
        )

    flash(f"Venda de {ticker} registrada com sucesso.", "success")
    return redirect(url_for("investimentos"))


@app.post("/investimentos/excluir/<int:investimento_id>")
@login_required
def excluir_investimento(investimento_id: int):
    with transaction() as db:
        cursor = db.execute(
            """
            DELETE FROM investimentos_usuario
            WHERE id = ? AND usuario_id = ?
            """,
            (investimento_id, usuario_id()),
        )

    if cursor.rowcount:
        flash("Investimento removido da carteira.", "success")
    else:
        flash("Investimento não encontrado.", "warning")

    return redirect(url_for("investimentos"))


# =========================================================
# ERROS
# =========================================================

@app.errorhandler(404)
def pagina_nao_encontrada(_error: Exception):
    return render_template("404.html"), 404


@app.errorhandler(500)
def erro_interno(_error: Exception):
    logger.exception("Erro interno não tratado")
    return render_template("500.html"), 500


# =========================================================
# EXECUÇÃO
# =========================================================

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug)
