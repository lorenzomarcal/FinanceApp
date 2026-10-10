"""Compra e venda de ativos, preço médio e resultado da carteira."""

import pytest

SEM_COTACAO = "Não foi possível obter a cotação atual."


# ---------------------------------------------------------
# Compra
# ---------------------------------------------------------

def test_compra_cria_o_ativo_e_registra_o_gasto(ana, brapi):
    brapi.definir("PETR4", 56.00)
    ana.ganho("1.000,00")

    pagina = ana.comprar("PETR4", "5")

    ativo = ana.ativo("PETR4")
    gasto = ana.movimentacoes()[-1]
    assert "Compra de PETR4 registrada com sucesso." in pagina
    assert (ativo["quantidade"], ativo["preco_medio"], ativo["tipo"]) == (5, 56.00, "acao")
    assert (gasto["tipo"], gasto["descricao"], gasto["categoria"], gasto["valor"]) == (
        "gasto",
        "Compra PETR4",
        "Investimentos",
        280.00,
    )
    assert ana.painel()["saldo"] == 720.00


def test_compra_aceita_ticker_em_minusculas_e_quantidade_fracionada(ana, brapi):
    brapi.definir("PETR4", 56.00)
    ana.ganho("1.000,00")

    ana.comprar(" petr4 ", "1,5")

    assert ana.ativo("PETR4")["quantidade"] == 1.5
    assert ana.painel()["saldo"] == 916.00


def test_compra_de_fii_grava_o_tipo(ana, brapi):
    brapi.definir("MXRF11", 10.00)
    ana.ganho("1.000,00")

    ana.comprar("MXRF11", "10", tipo="fii")

    assert ana.ativo("MXRF11")["tipo"] == "fii"


def test_compra_pela_rota_da_carteira(ana, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("1.000,00")
    ana.comprar("PETR4", "2")

    ana.comprar("PETR4", "3", rota="/investimentos/comprar")

    assert ana.ativo("PETR4")["quantidade"] == 5
    assert ana.painel()["saldo"] == 750.00


def test_compra_com_o_saldo_exato_e_permitida(ana, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("500,00")

    ana.comprar("PETR4", "10")

    assert ana.ativo("PETR4")["quantidade"] == 10
    assert ana.painel()["saldo"] == 0


def test_compra_recusada_por_saldo_insuficiente(ana, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("499,99")

    pagina = ana.comprar("PETR4", "10")

    assert "Saldo insuficiente para essa compra." in pagina
    assert ana.ativo("PETR4") is None
    assert len(ana.movimentacoes()) == 1
    assert ana.painel()["saldo"] == 499.99


def test_compra_nao_pode_usar_o_dinheiro_da_reserva(ana, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("1.000,00")
    ana.guardar("800,00")

    pagina = ana.comprar("PETR4", "10")

    assert "Saldo insuficiente para essa compra." in pagina
    assert ana.ativo("PETR4") is None
    assert ana.painel()["cofrinho"] == 800.00


def test_compra_recusada_quando_o_ticker_nao_tem_cotacao(ana, brapi):
    ana.ganho("1.000,00")

    pagina = ana.comprar("XXXX3", "1")

    assert SEM_COTACAO in pagina
    assert ana.ativo("XXXX3") is None
    assert ana.painel()["saldo"] == 1000.00


def test_compra_recusada_com_a_brapi_fora_do_ar(ana, brapi):
    brapi.definir("PETR4", 50.00)
    brapi.fora_do_ar = True
    ana.ganho("1.000,00")

    pagina = ana.comprar("PETR4", "1")

    assert SEM_COTACAO in pagina
    assert ana.ativo("PETR4") is None
    assert ana.painel()["saldo"] == 1000.00


@pytest.mark.parametrize(
    "resposta",
    [
        ["lista", "no", "lugar", "de", "objeto"],
        {"results": "texto"},
        {"results": ["texto"]},
        {"results": [{"symbol": "PETR4"}]},
        {"results": [{"regularMarketPrice": None}]},
        {"results": [{"regularMarketPrice": "abc"}]},
        {"results": [{"regularMarketPrice": 0}]},
        {"results": [{"regularMarketPrice": -5}]},
        ValueError("corpo que não é JSON"),
    ],
)
def test_resposta_inesperada_da_brapi_vira_sem_cotacao(ana, brapi, resposta):
    brapi.resposta_fixa = resposta
    ana.ganho("1.000,00")

    pagina = ana.comprar("PETR4", "1")

    assert SEM_COTACAO in pagina
    assert ana.ativo("PETR4") is None
    assert ana.painel()["saldo"] == 1000.00


def test_sem_token_da_brapi_nao_compra_nem_chama_a_api(ana, brapi, app, monkeypatch):
    monkeypatch.setitem(app.app.config, "BRAPI_TOKEN", "")
    brapi.definir("PETR4", 50.00)
    ana.ganho("1.000,00")

    pagina = ana.comprar("PETR4", "1")

    assert SEM_COTACAO in pagina
    assert ana.ativo("PETR4") is None
    assert brapi.chamadas == []


def test_compra_usa_a_cotacao_do_momento_e_nao_a_do_cache(ana, brapi):
    brapi.definir("PETR4", 20.00)
    ana.ganho("1.000,00")
    ana.comprar("PETR4", "1")
    ana.investimentos()  # exibir a carteira guarda R$ 20,00 no cache

    brapi.definir("PETR4", 30.00)
    ana.comprar("PETR4", "1")

    assert ana.movimentacoes()[-1]["valor"] == 30.00


# ---------------------------------------------------------
# Preço médio
# ---------------------------------------------------------

def test_preco_medio_pondera_as_compras_pela_quantidade(ana, brapi):
    ana.ganho("10.000,00")
    brapi.definir("PETR4", 20.00)
    ana.comprar("PETR4", "10")

    brapi.definir("PETR4", 30.00)
    ana.comprar("PETR4", "30")

    ativo = ana.ativo("PETR4")
    assert ativo["quantidade"] == 40
    assert ativo["preco_medio"] == pytest.approx(27.50)  # (10×20 + 30×30) ÷ 40


def test_preco_medio_em_tres_compras(ana, brapi):
    ana.ganho("10.000,00")
    for preco, quantidade in [(10.00, "1"), (20.00, "2"), (40.00, "1")]:
        brapi.definir("VALE3", preco)
        ana.comprar("VALE3", quantidade)

    ativo = ana.ativo("VALE3")
    assert ativo["quantidade"] == 4
    assert ativo["preco_medio"] == pytest.approx(22.50)  # (10 + 40 + 40) ÷ 4
    assert ana.painel()["gastos"] == 90.00


def test_venda_nao_altera_o_preco_medio(ana, brapi):
    ana.ganho("10.000,00")
    brapi.definir("PETR4", 20.00)
    ana.comprar("PETR4", "10")

    brapi.definir("PETR4", 50.00)
    ana.vender("PETR4", "4")

    assert ana.ativo("PETR4")["preco_medio"] == pytest.approx(20.00)


def test_compra_recusada_nao_altera_o_preco_medio(ana, brapi):
    ana.ganho("200,00")
    brapi.definir("PETR4", 20.00)
    ana.comprar("PETR4", "10")

    brapi.definir("PETR4", 30.00)
    ana.comprar("PETR4", "1")  # saldo zerado

    ativo = ana.ativo("PETR4")
    assert (ativo["quantidade"], ativo["preco_medio"]) == (10, 20.00)


# ---------------------------------------------------------
# Venda
# ---------------------------------------------------------

def test_venda_parcial_reduz_a_quantidade_e_registra_o_ganho(ana, brapi):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 50.00)
    ana.comprar("PETR4", "10")

    brapi.definir("PETR4", 60.00)
    pagina = ana.vender("PETR4", "4")

    ganho = ana.movimentacoes()[-1]
    assert "Venda de PETR4 registrada com sucesso." in pagina
    assert ana.ativo("PETR4")["quantidade"] == 6
    assert (ganho["tipo"], ganho["descricao"], ganho["categoria"], ganho["valor"]) == (
        "ganho",
        "Venda PETR4",
        "Investimentos",
        240.00,
    )
    assert ana.painel()["saldo"] == 740.00  # 1000 − 500 + 240


def test_venda_total_tira_o_ativo_da_carteira(ana, brapi):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 50.00)
    ana.comprar("PETR4", "10")

    ana.vender("PETR4", "10")

    assert ana.ativo("PETR4") is None
    assert ana.painel()["saldo"] == 1000.00


def test_venda_recusada_por_quantidade_insuficiente(ana, brapi):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 50.00)
    ana.comprar("PETR4", "10")

    pagina = ana.vender("PETR4", "10,5")

    assert "Você não possui essa quantidade para vender." in pagina
    assert ana.ativo("PETR4")["quantidade"] == 10
    assert ana.painel()["saldo"] == 500.00


def test_venda_recusada_de_ativo_que_nao_esta_na_carteira(ana, brapi):
    brapi.definir("VALE3", 70.00)
    ana.ganho("1.000,00")

    pagina = ana.vender("VALE3", "1")

    assert "Esse ativo não existe na sua carteira." in pagina
    assert ana.painel()["saldo"] == 1000.00


@pytest.mark.parametrize("quantidade", ["0", "-1", "NaN", "Infinity", "abc", ""])
def test_venda_recusa_quantidade_invalida(ana, brapi, quantidade):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 50.00)
    ana.comprar("PETR4", "10")

    ana.vender("PETR4", quantidade)

    assert ana.ativo("PETR4")["quantidade"] == 10
    assert ana.painel()["saldo"] == 500.00


def test_venda_recusada_quando_o_ativo_perde_a_cotacao(ana, brapi):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 50.00)
    ana.comprar("PETR4", "10")

    brapi.remover("PETR4")
    pagina = ana.vender("PETR4", "5")

    assert SEM_COTACAO in pagina
    assert ana.ativo("PETR4")["quantidade"] == 10
    assert ana.painel()["saldo"] == 500.00


def test_venda_recusada_com_a_brapi_fora_do_ar(ana, brapi):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 50.00)
    ana.comprar("PETR4", "10")

    brapi.fora_do_ar = True
    pagina = ana.vender("PETR4", "5")

    assert SEM_COTACAO in pagina
    assert ana.ativo("PETR4")["quantidade"] == 10
    assert ana.painel()["saldo"] == 500.00


# ---------------------------------------------------------
# Carteira
# ---------------------------------------------------------

def test_carteira_calcula_resultado_e_rentabilidade(ana, brapi, expirar_cache):
    ana.ganho("10.000,00")
    brapi.definir("PETR4", 20.00)
    ana.comprar("PETR4", "10")
    brapi.definir("VALE3", 100.00)
    ana.comprar("VALE3", "3")

    brapi.definir("PETR4", 25.00)
    brapi.definir("VALE3", 90.00)
    expirar_cache()
    pagina = ana.investimentos()

    petr4, vale3 = pagina["carteira"]
    assert (petr4["investido"], petr4["valor_atual"], petr4["resultado"]) == (200.00, 250.00, 50.00)
    assert petr4["resultado_percentual"] == pytest.approx(25.0)
    assert (vale3["investido"], vale3["valor_atual"], vale3["resultado"]) == (300.00, 270.00, -30.00)
    assert pagina["total_investido"] == 500.00
    assert pagina["patrimonio"] == 520.00
    assert pagina["resultado_total"] == 20.00
    assert pagina["rentabilidade"] == pytest.approx(4.0)
    assert pagina["saldo"] == 9500.00


def test_carteira_sem_cotacao_mostra_o_preco_medio(ana, brapi, expirar_cache):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 20.00)
    ana.comprar("PETR4", "10")

    brapi.fora_do_ar = True
    expirar_cache()
    pagina = ana.investimentos()

    ativo = pagina["carteira"][0]
    assert ativo["preco_atual"] == 20.00
    assert ativo["resultado"] == 0
    assert pagina["resultado_total"] == 0


def test_carteira_reaproveita_a_cotacao_em_cache(ana, brapi):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 20.00)
    ana.comprar("PETR4", "10")
    brapi.chamadas.clear()

    ana.investimentos()
    ana.investimentos()

    assert brapi.cotacoes_consultadas() == []  # a compra já deixou o preço no cache


def test_remover_ativo_tira_da_carteira_sem_devolver_o_dinheiro(ana, brapi):
    ana.ganho("1.000,00")
    brapi.definir("PETR4", 50.00)
    ana.comprar("PETR4", "10")

    pagina = ana.excluir_investimento(ana.ativo("PETR4")["id"])

    assert "Investimento removido da carteira." in pagina
    assert ana.ativo("PETR4") is None
    assert ana.painel()["saldo"] == 500.00


def test_remover_ativo_inexistente_avisa(ana):
    assert "Investimento não encontrado." in ana.excluir_investimento(9999)

