"""Valores e quantidades inválidos não podem entrar no sistema."""

import pytest

INVALIDOS = ["NaN", "nan", "Infinity", "-Infinity", "inf", "abc", "", "   ", "1e400"]
ACIMA_DO_LIMITE = ["1.000.000.000,00", "1000000000", "999.999.999,995", "-1.000.000.000,00"]
NAO_POSITIVOS = ["0", "0,00", "0,001", "-10", "-0,01"]


# ---------------------------------------------------------
# converter_valor
# ---------------------------------------------------------

@pytest.mark.parametrize("texto", INVALIDOS + ACIMA_DO_LIMITE)
def test_converter_valor_recusa_invalidos_e_acima_do_limite(app, texto):
    with pytest.raises(ValueError):
        app.converter_valor(texto)


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("1.500,00", 1500.00),
        ("1.500", 1500.00),
        ("R$ 2.345,67", 2345.67),
        ("150", 150.00),
        ("10.5", 10.50),
        ("0,01", 0.01),
        ("0,005", 0.01),
        ("999.999.999,99", 999999999.99),
    ],
)
def test_converter_valor_le_o_padrao_brasileiro(app, texto, esperado):
    assert app.converter_valor(texto) == esperado


# ---------------------------------------------------------
# Movimentações
# ---------------------------------------------------------

@pytest.mark.parametrize("tipo", ["ganho", "gasto"])
@pytest.mark.parametrize("valor", INVALIDOS + ACIMA_DO_LIMITE)
def test_movimentacao_recusa_valor_invalido(ana, tipo, valor):
    pagina = ana.movimentar(tipo, valor)

    assert "Informe um valor válido." in pagina
    assert ana.movimentacoes() == []


@pytest.mark.parametrize("valor", NAO_POSITIVOS)
def test_movimentacao_recusa_zero_e_negativo(ana, valor):
    pagina = ana.ganho(valor)

    assert "O valor deve ser maior que zero." in pagina
    assert ana.movimentacoes() == []


def test_movimentacao_aceita_o_valor_maximo(ana):
    pagina = ana.ganho("999.999.999,99")

    assert "Movimentação adicionada." in pagina
    assert ana.painel()["ganhos"] == 999999999.99


@pytest.mark.parametrize(
    "dados, aviso",
    [
        ({"tipo": "transferencia"}, "Tipo de movimentação inválido."),
        ({"descricao": ""}, "Informe uma descrição válida."),
        ({"descricao": "x" * 101}, "Informe uma descrição válida."),
        ({"categoria": ""}, "Informe uma categoria válida."),
        ({"categoria": "x" * 51}, "Informe uma categoria válida."),
    ],
)
def test_movimentacao_recusa_campos_invalidos(ana, dados, aviso):
    campos = {"tipo": "ganho", "descricao": "Teste", "categoria": "Geral", "valor": "10,00"}
    campos.update(dados)

    pagina = ana.movimentar(**campos)

    assert aviso in pagina
    assert ana.movimentacoes() == []


def test_movimentacao_aceita_descricao_e_categoria_no_limite(ana):
    ana.movimentar("ganho", "10,00", descricao="d" * 100, categoria="c" * 50)

    assert len(ana.movimentacoes()) == 1


# ---------------------------------------------------------
# Reserva
# ---------------------------------------------------------

@pytest.mark.parametrize("valor", INVALIDOS + ACIMA_DO_LIMITE)
def test_reserva_recusa_valor_invalido(ana, valor):
    ana.ganho("1.000,00")

    assert "Informe um valor válido." in ana.guardar(valor)
    assert "Informe um valor válido." in ana.retirar(valor)
    assert ana.reserva() == 0


@pytest.mark.parametrize("valor", NAO_POSITIVOS)
def test_reserva_recusa_zero_e_negativo(ana, valor):
    ana.ganho("1.000,00")
    ana.guardar("100,00")

    assert "O valor deve ser maior que zero." in ana.guardar(valor)
    assert "O valor deve ser maior que zero." in ana.retirar(valor)
    assert ana.reserva() == 100.00


# ---------------------------------------------------------
# Quantidade e ticker dos investimentos
# ---------------------------------------------------------

@pytest.mark.parametrize(
    "texto", ["NaN", "Infinity", "-Infinity", "abc", "", "0", "0,0", "-1", "1000000001"]
)
def test_converter_quantidade_recusa_invalidos(app, texto):
    with pytest.raises(ValueError):
        app.converter_quantidade(texto)


@pytest.mark.parametrize("texto, esperado", [("5", 5.0), ("1,5", 1.5), ("0.25", 0.25)])
def test_converter_quantidade_aceita_inteiro_e_fracionado(app, texto, esperado):
    assert app.converter_quantidade(texto) == esperado


@pytest.mark.parametrize("quantidade", ["NaN", "Infinity", "0", "-3", "abc", "", "1000000001"])
def test_compra_recusa_quantidade_invalida(ana, brapi, quantidade):
    brapi.definir("PETR4", 10.00)
    ana.ganho("1.000,00")

    ana.comprar("PETR4", quantidade)

    assert ana.ativo("PETR4") is None
    assert ana.painel()["saldo"] == 1000.00
    assert brapi.cotacoes_consultadas() == []


@pytest.mark.parametrize("ticker", ["", "A", "PETR4/../x", "PETR 4", "ABCDEFGHIJKLM", "PETR4?x=1"])
def test_compra_recusa_ticker_invalido_sem_consultar_a_brapi(ana, brapi, ticker):
    ana.ganho("1.000,00")

    pagina = ana.comprar(ticker, "1")

    assert "Ticker inválido." in pagina
    assert brapi.cotacoes_consultadas() == []
    assert ana.painel()["saldo"] == 1000.00
