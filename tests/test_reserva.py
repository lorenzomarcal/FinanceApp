"""Reserva: guardar tira do saldo, retirar devolve."""


def test_guardar_tira_do_saldo_e_soma_na_reserva(ana):
    ana.ganho("1.000,00")

    pagina = ana.guardar("300,00")

    painel = ana.painel()
    assert "Valor guardado na reserva." in pagina
    assert painel["cofrinho"] == 300.00
    assert painel["saldo"] == 700.00


def test_guardar_duas_vezes_acumula(ana):
    ana.ganho("1.000,00")

    ana.guardar("300,00")
    ana.guardar("150,50")

    assert ana.painel()["cofrinho"] == 450.50
    assert ana.painel()["saldo"] == 549.50


def test_guardar_nao_altera_ganhos_nem_gastos(ana):
    ana.ganho("1.000,00")
    ana.gasto("200,00")

    ana.guardar("300,00")

    painel = ana.painel()
    assert painel["ganhos"] == 1000.00
    assert painel["gastos"] == 200.00
    assert len(ana.movimentacoes()) == 2


def test_guardar_todo_o_saldo_e_permitido(ana):
    ana.ganho("1.000,00")

    ana.guardar("1.000,00")

    assert ana.painel()["cofrinho"] == 1000.00
    assert ana.painel()["saldo"] == 0


def test_guardar_mais_que_o_saldo_e_recusado(ana):
    ana.ganho("1.000,00")
    ana.gasto("400,00")

    pagina = ana.guardar("600,01")

    assert "Saldo insuficiente para guardar esse valor." in pagina
    assert ana.painel()["cofrinho"] == 0
    assert ana.painel()["saldo"] == 600.00


def test_guardar_sem_saldo_nenhum_e_recusado(ana):
    pagina = ana.guardar("0,01")

    assert "Saldo insuficiente para guardar esse valor." in pagina
    assert ana.reserva() == 0


def test_retirar_devolve_para_o_saldo(ana):
    ana.ganho("1.000,00")
    ana.guardar("300,00")

    pagina = ana.retirar("100,00")

    painel = ana.painel()
    assert "Valor retirado da reserva." in pagina
    assert painel["cofrinho"] == 200.00
    assert painel["saldo"] == 800.00


def test_retirar_tudo_zera_a_reserva(ana):
    ana.ganho("1.000,00")
    ana.guardar("300,00")

    ana.retirar("300,00")

    assert ana.painel()["cofrinho"] == 0
    assert ana.painel()["saldo"] == 1000.00


def test_retirar_mais_que_o_guardado_e_recusado(ana):
    ana.ganho("1.000,00")
    ana.guardar("300,00")

    pagina = ana.retirar("300,01")

    assert "Você não possui esse valor na reserva." in pagina
    assert ana.painel()["cofrinho"] == 300.00
    assert ana.painel()["saldo"] == 700.00


def test_retirar_com_reserva_vazia_e_recusado(ana):
    ana.ganho("1.000,00")

    pagina = ana.retirar("50,00")

    assert "Você não possui esse valor na reserva." in pagina
    assert ana.painel()["saldo"] == 1000.00
