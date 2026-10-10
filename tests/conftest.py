"""Base dos testes do FinanceApp.

Duas garantias valem para todos os testes:

1. O banco.db real nunca é aberto. Cada teste usa um banco SQLite novo,
   criado numa pasta temporária.
2. A BRAPI nunca é chamada de verdade. As cotações vêm de BrapiSimulada e
   qualquer tentativa de acesso real à rede faz o teste falhar.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
from unittest import mock

import pytest
import requests
from flask import template_rendered

RAIZ = Path(__file__).resolve().parent.parent
BANCO_REAL = RAIZ / "banco.db"

if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))


# ---------------------------------------------------------
# Importação protegida do app.py
# ---------------------------------------------------------
# O app.py lê o .env e roda init_db() no momento do import, apontando para
# o banco.db real. Durante o import, o .env é ignorado e toda conexão SQLite
# é desviada para um arquivo temporário.
#
# A pasta temporária é criada aqui, e não pelo tmp_path do pytest, que falha
# com "Acesso negado" em algumas instalações do Windows.

_PASTA_TEMPORARIA = tempfile.mkdtemp(prefix="financeapp-testes-")
_conectar_real = sqlite3.connect


def _conectar_desviado(_caminho: Any, *args: Any, **kwargs: Any) -> sqlite3.Connection:
    return _conectar_real(os.path.join(_PASTA_TEMPORARIA, "import.db"), *args, **kwargs)


os.environ["SECRET_KEY"] = "chave-apenas-para-testes"
os.environ.pop("BRAPI_TOKEN", None)

with mock.patch("dotenv.load_dotenv", return_value=False), mock.patch(
    "sqlite3.connect", _conectar_desviado
):
    import app as financeapp


def _impressao_digital(caminho: Path) -> tuple[str, int] | None:
    if not caminho.exists():
        return None
    conteudo = caminho.read_bytes()
    return hashlib.sha256(conteudo).hexdigest(), caminho.stat().st_mtime_ns


@pytest.fixture(scope="session", autouse=True)
def banco_real_intocado() -> Iterator[None]:
    """Falha a suíte se o banco.db real for criado ou alterado pelos testes."""
    antes = _impressao_digital(BANCO_REAL)
    yield
    shutil.rmtree(_PASTA_TEMPORARIA, ignore_errors=True)
    assert _impressao_digital(BANCO_REAL) == antes, "Os testes mexeram no banco.db real."


# ---------------------------------------------------------
# BRAPI simulada
# ---------------------------------------------------------

class RespostaSimulada:
    def __init__(self, dados: Any, status: int = 200) -> None:
        self._dados = dados
        self.status_code = status

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self) -> Any:
        if isinstance(self._dados, Exception):
            raise self._dados
        return self._dados


class BrapiSimulada:
    """Substitui HTTP.get do app.py e responde como a BRAPI responderia."""

    def __init__(self) -> None:
        self.precos: dict[str, float] = {}
        self.mercado: list[dict[str, Any]] = []
        self.fora_do_ar = False
        self.resposta_fixa: Any = None
        self.chamadas: list[str] = []

    def definir(self, ticker: str, preco: float) -> None:
        self.precos[ticker] = preco

    def remover(self, ticker: str) -> None:
        self.precos.pop(ticker, None)

    def get(self, url: str, **_kwargs: Any) -> RespostaSimulada:
        self.chamadas.append(url)

        if self.fora_do_ar:
            raise requests.ConnectionError("BRAPI fora do ar (simulado)")

        if self.resposta_fixa is not None:
            return RespostaSimulada(self.resposta_fixa)

        if url.endswith("/quote/list"):
            return RespostaSimulada({"stocks": self.mercado})

        ticker = url.rsplit("/", 1)[-1]
        if ticker not in self.precos:
            return RespostaSimulada({"results": []})

        return RespostaSimulada(
            {
                "results": [
                    {
                        "symbol": ticker,
                        "regularMarketPrice": self.precos[ticker],
                        "regularMarketChangePercent": 1.5,
                    }
                ]
            }
        )

    def cotacoes_consultadas(self) -> list[str]:
        return [url.rsplit("/", 1)[-1] for url in self.chamadas if "/quote/list" not in url]


def _rede_bloqueada(*_args: Any, **_kwargs: Any) -> None:
    raise AssertionError("Um teste tentou acessar a rede de verdade.")


# ---------------------------------------------------------
# Ambiente de cada teste
# ---------------------------------------------------------

@pytest.fixture(autouse=True)
def brapi(monkeypatch: pytest.MonkeyPatch) -> Iterator[BrapiSimulada]:
    """Prepara banco temporário e BRAPI simulada para todo teste."""
    banco = Path(_PASTA_TEMPORARIA) / f"teste-{uuid.uuid4().hex}.db"
    assert banco.resolve() != BANCO_REAL.resolve()

    monkeypatch.setitem(financeapp.app.config, "DATABASE", str(banco))
    monkeypatch.setitem(financeapp.app.config, "TESTING", True)
    monkeypatch.setitem(financeapp.app.config, "BRAPI_TOKEN", "token-de-teste")
    financeapp.init_db()
    financeapp._cache_cotacoes.clear()

    simulada = BrapiSimulada()
    monkeypatch.setattr(financeapp.HTTP, "get", simulada.get)
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", _rede_bloqueada)

    yield simulada

    financeapp._cache_cotacoes.clear()
    banco.unlink(missing_ok=True)


@pytest.fixture
def app():
    return financeapp


@pytest.fixture
def expirar_cache():
    """Esvazia o cache de cotações, como se os 60 segundos tivessem passado."""
    return financeapp._cache_cotacoes.clear


@pytest.fixture
def consultar():
    """Lê direto do banco temporário do teste."""

    def _consultar(sql: str, parametros: tuple = ()) -> list[sqlite3.Row]:
        db = sqlite3.connect(financeapp.app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        try:
            return db.execute(sql, parametros).fetchall()
        finally:
            db.close()

    return _consultar


@contextmanager
def _contexto_do_template() -> Iterator[dict[str, Any]]:
    capturado: dict[str, Any] = {}

    def registrar(_sender: Any, template: Any, context: dict[str, Any], **_extra: Any) -> None:
        capturado.clear()
        capturado.update(context)
        capturado["_template"] = template.name

    template_rendered.connect(registrar, financeapp.app)
    try:
        yield capturado
    finally:
        template_rendered.disconnect(registrar, financeapp.app)


class Conta:
    """Um usuário logado, com atalhos para as ações do sistema.

    As ações devolvem o HTML da página seguinte, para conferir os avisos.
    """

    SENHA = "senha-segura-123"

    def __init__(self, nome: str) -> None:
        self.nome = nome
        self.client = financeapp.app.test_client()

        self.client.post(
            "/cadastro",
            data={"nome": nome, "senha": self.SENHA, "confirmar_senha": self.SENHA},
        )
        resposta = self.client.post("/login", data={"nome": nome, "senha": self.SENHA})
        assert resposta.status_code == 302, f"Login de {nome} falhou."

    @property
    def id(self) -> int:
        db = sqlite3.connect(financeapp.app.config["DATABASE"])
        try:
            return db.execute("SELECT id FROM usuarios WHERE nome = ?", (self.nome,)).fetchone()[0]
        finally:
            db.close()

    def _enviar(self, rota: str, dados: dict[str, Any] | None = None) -> str:
        resposta = self.client.post(rota, data=dados or {}, follow_redirects=True)
        assert resposta.status_code == 200
        return resposta.get_data(as_text=True)

    # Painel
    def movimentar(self, tipo: str, valor: str, descricao: str = "Teste", categoria: str = "Geral") -> str:
        return self._enviar(
            "/adicionar",
            {"tipo": tipo, "descricao": descricao, "categoria": categoria, "valor": valor},
        )

    def ganho(self, valor: str, descricao: str = "Salário") -> str:
        return self.movimentar("ganho", valor, descricao)

    def gasto(self, valor: str, descricao: str = "Mercado") -> str:
        return self.movimentar("gasto", valor, descricao)

    def excluir_movimentacao(self, movimentacao_id: int) -> str:
        return self._enviar(f"/excluir/{movimentacao_id}")

    def guardar(self, valor: str) -> str:
        return self._enviar("/cofrinho", {"valor_cofrinho": valor})

    def retirar(self, valor: str) -> str:
        return self._enviar("/retirar_cofrinho", {"valor_retirar": valor})

    def painel(self) -> dict[str, Any]:
        """Números que a rota / entrega ao template: ganhos, gastos, cofrinho, saldo."""
        with _contexto_do_template() as contexto:
            assert self.client.get("/").status_code == 200
        return contexto

    # Investimentos
    def comprar(self, ticker: str, quantidade: str, tipo: str = "acao", rota: str = "/investimentos/adicionar") -> str:
        return self._enviar(rota, {"ticker": ticker, "tipo": tipo, "quantidade": quantidade})

    def vender(self, ticker: str, quantidade: str) -> str:
        return self._enviar("/investimentos/vender", {"ticker": ticker, "quantidade": quantidade})

    def excluir_investimento(self, investimento_id: int) -> str:
        return self._enviar(f"/investimentos/excluir/{investimento_id}")

    def investimentos(self, consulta: str = "") -> dict[str, Any]:
        """Números que a rota /investimentos entrega ao template."""
        with _contexto_do_template() as contexto:
            assert self.client.get(f"/investimentos{consulta}").status_code == 200
        return contexto

    # Leitura direta do banco temporário
    def _linhas(self, sql: str, parametros: tuple) -> list[sqlite3.Row]:
        db = sqlite3.connect(financeapp.app.config["DATABASE"])
        db.row_factory = sqlite3.Row
        try:
            return db.execute(sql, parametros).fetchall()
        finally:
            db.close()

    def movimentacoes(self) -> list[sqlite3.Row]:
        return self._linhas(
            "SELECT * FROM movimentacoes_usuario WHERE usuario_id = ? ORDER BY id", (self.id,)
        )

    def ativo(self, ticker: str) -> sqlite3.Row | None:
        linhas = self._linhas(
            "SELECT * FROM investimentos_usuario WHERE usuario_id = ? AND ticker = ?",
            (self.id, ticker),
        )
        return linhas[0] if linhas else None

    def reserva(self) -> float:
        linhas = self._linhas(
            "SELECT valor FROM cofrinho_usuario WHERE usuario_id = ?", (self.id,)
        )
        return linhas[0]["valor"] if linhas else 0.0


@pytest.fixture
def criar_conta():
    return Conta


@pytest.fixture
def ana(brapi: BrapiSimulada) -> Conta:
    return Conta("ana")


@pytest.fixture
def bruno(brapi: BrapiSimulada) -> Conta:
    return Conta("bruno")


@pytest.fixture
def visitante(brapi: BrapiSimulada):
    """Navegador sem login."""
    return financeapp.app.test_client()
