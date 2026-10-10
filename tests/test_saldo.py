"""Ganhos − Gastos − Reserva = Saldo disponível."""


def test_conta_nova_comeca_zerada(ana):
    painel = ana.painel()

    assert (painel["ganhos"], painel["gastos"], painel["cofrinho"], painel["saldo"]) == (0, 0, 0, 0)


def test_saldo_e_ganhos_menos_gastos_menos_reserva(ana):
    ana.ganho("5.000,00", "Salário")
    ana.ganho("450,00", "Freela")
    ana.gasto("1.200,00", "Aluguel")
    ana.gasto("637,90", "Mercado")
    ana.guardar("650,00")

    painel = ana.painel()

    assert painel["ganhos"] == 5450.00
    assert painel["gastos"] == 1837.90
    assert painel["cofrinho"] == 650.00
    assert painel["saldo"] == 2962.10


def test_compra_de_ativo_entra_como_gasto_no_saldo(ana, brapi):
    brapi.definir("ITUB4", 61.20)
    ana.ganho("5.450,00")
    ana.gasto("1.837,90")
    ana.guardar("650,00")

    ana.comprar("ITUB4", "5")

    painel = ana.painel()
    assert painel["gastos"] == 2143.90
    assert painel["saldo"] == 2656.10


def test_excluir_movimentacao_recalcula_o_saldo(ana):
    ana.ganho("1.000,00")
    ana.gasto("300,00")
    gasto = ana.movimentacoes()[1]

    pagina = ana.excluir_movimentacao(gasto["id"])

    assert "Movimentação excluída." in pagina
    assert ana.painel()["gastos"] == 0
    assert ana.painel()["saldo"] == 1000.00


def test_excluir_movimentacao_inexistente_nao_muda_nada(ana):
    ana.ganho("1.000,00")

    pagina = ana.excluir_movimentacao(9999)

    assert "Movimentação não encontrada." in pagina
    assert ana.painel()["saldo"] == 1000.00


def test_saldo_pode_ficar_negativo_quando_gasta_mais_do_que_ganha(ana):
    ana.ganho("100,00")
    ana.gasto("250,00")

    assert ana.painel()["saldo"] == -150.00


def test_saldo_nao_acumula_erro_de_centavos(ana):
    for _ in range(10):
        ana.ganho("0,10")
    ana.gasto("0,70")
    ana.gasto("0,30")

    painel = ana.painel()

    assert painel["ganhos"] == 1.00
    assert painel["saldo"] == 0.0


def test_movimentacoes_aparecem_da_mais_recente_para_a_mais_antiga(ana):
    ana.ganho("10,00", "Primeira")
    ana.ganho("20,00", "Segunda")
    ana.gasto("5,00", "Terceira")

    descricoes = [m["descricao"] for m in ana.painel()["movimentacoes"]]

    assert descricoes == ["Terceira", "Segunda", "Primeira"]


def test_distribuicao_mostra_o_percentual_de_cada_parte(ana):
    ana.ganho("1.000,00")
    ana.gasto("250,00")
    ana.guardar("150,00")

    assert ana.painel()["distribuicao"] == {"gastos": 25.0, "reserva": 15.0, "saldo": 60.0}
