"""Um usuário nunca vê nem altera o que é de outro."""

import pytest


def test_cada_usuario_tem_seu_proprio_saldo(ana, bruno):
    ana.ganho("5.000,00")
    ana.gasto("1.000,00")
    ana.guardar("500,00")

    painel_bruno = bruno.painel()

    assert (painel_bruno["ganhos"], painel_bruno["gastos"]) == (0, 0)
    assert (painel_bruno["cofrinho"], painel_bruno["saldo"]) == (0, 0)
    assert ana.painel()["saldo"] == 3500.00


def test_usuario_nao_ve_movimentacoes_de_outro(ana, bruno):
    ana.ganho("5.000,00", "Salário secreto da Ana")

    resposta = bruno.client.get("/")

    assert bruno.painel()["movimentacoes"] == []
    assert "Salário secreto da Ana" not in resposta.get_data(as_text=True)


def test_usuario_nao_exclui_movimentacao_de_outro(ana, bruno):
    ana.ganho("5.000,00")
    movimentacao = ana.movimentacoes()[0]

    pagina = bruno.excluir_movimentacao(movimentacao["id"])

    assert "Movimentação não encontrada." in pagina
    assert len(ana.movimentacoes()) == 1
    assert ana.painel()["saldo"] == 5000.00


def test_usuario_nao_guarda_usando_o_saldo_de_outro(ana, bruno):
    ana.ganho("5.000,00")

    pagina = bruno.guardar("100,00")

    assert "Saldo insuficiente para guardar esse valor." in pagina
    assert bruno.reserva() == 0


def test_usuario_nao_retira_da_reserva_de_outro(ana, bruno):
    ana.ganho("5.000,00")
    ana.guardar("1.000,00")

    pagina = bruno.retirar("100,00")

    assert "Você não possui esse valor na reserva." in pagina
    assert ana.reserva() == 1000.00
    assert bruno.painel()["saldo"] == 0


def test_usuario_nao_compra_com_o_saldo_de_outro(ana, bruno, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("5.000,00")

    pagina = bruno.comprar("PETR4", "1")

    assert "Saldo insuficiente para essa compra." in pagina
    assert bruno.ativo("PETR4") is None
    assert ana.painel()["saldo"] == 5000.00


def test_usuario_nao_ve_a_carteira_de_outro(ana, bruno, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("5.000,00")
    ana.comprar("PETR4", "10")

    pagina = bruno.investimentos()

    assert pagina["carteira"] == []
    assert pagina["total_investido"] == 0
    assert pagina["saldo"] == 0


def test_usuario_nao_vende_ativo_de_outro(ana, bruno, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("5.000,00")
    ana.comprar("PETR4", "10")

    pagina = bruno.vender("PETR4", "10")

    assert "Esse ativo não existe na sua carteira." in pagina
    assert ana.ativo("PETR4")["quantidade"] == 10
    assert bruno.movimentacoes() == []


def test_usuario_nao_remove_ativo_de_outro(ana, bruno, brapi):
    brapi.definir("PETR4", 50.00)
    ana.ganho("5.000,00")
    ana.comprar("PETR4", "10")

    pagina = bruno.excluir_investimento(ana.ativo("PETR4")["id"])

    assert "Investimento não encontrado." in pagina
    assert ana.ativo("PETR4")["quantidade"] == 10


def test_mesmo_ticker_tem_preco_medio_separado_por_usuario(ana, bruno, brapi):
    ana.ganho("5.000,00")
    bruno.ganho("5.000,00")

    brapi.definir("PETR4", 20.00)
    ana.comprar("PETR4", "10")
    brapi.definir("PETR4", 40.00)
    bruno.comprar("PETR4", "5")

    assert (ana.ativo("PETR4")["quantidade"], ana.ativo("PETR4")["preco_medio"]) == (10, 20.00)
    assert (bruno.ativo("PETR4")["quantidade"], bruno.ativo("PETR4")["preco_medio"]) == (5, 40.00)
    assert ana.painel()["saldo"] == 4800.00
    assert bruno.painel()["saldo"] == 4800.00


def test_nome_de_usuario_e_unico_sem_diferenciar_maiusculas(ana, visitante, consultar):
    resposta = visitante.post(
        "/cadastro",
        data={"nome": "ANA", "senha": "outra-senha-123", "confirmar_senha": "outra-senha-123"},
    )

    assert "Esse nome de usuário já existe." in resposta.get_data(as_text=True)
    assert len(consultar("SELECT id FROM usuarios")) == 1


def test_usuario_nao_assume_o_nome_de_outro_pelo_perfil(ana, bruno, consultar):
    resposta = bruno.client.post(
        "/perfil", data={"acao": "alterar_nome", "novo_nome": "Ana"}, follow_redirects=True
    )

    assert "Esse nome de usuário já está em uso." in resposta.get_data(as_text=True)
    assert [u["nome"] for u in consultar("SELECT nome FROM usuarios ORDER BY id")] == ["ana", "bruno"]


def test_apagar_usuario_apaga_em_cascata_so_o_que_e_dele(ana, bruno, brapi, app, consultar):
    brapi.definir("PETR4", 50.00)
    for conta in (ana, bruno):
        conta.ganho("1.000,00")
        conta.guardar("100,00")
        conta.comprar("PETR4", "2")
    id_ana = ana.id

    with app.app.app_context():
        with app.transaction() as db:
            db.execute("DELETE FROM usuarios WHERE id = ?", (id_ana,))

    for tabela in ("movimentacoes_usuario", "cofrinho_usuario", "investimentos_usuario"):
        donos = {linha["usuario_id"] for linha in consultar(f"SELECT usuario_id FROM {tabela}")}
        assert donos == {bruno.id}, tabela
    assert bruno.painel()["saldo"] == 800.00


@pytest.mark.parametrize("rota", ["/", "/investimentos", "/perfil"])
def test_sessao_de_usuario_apagado_deixa_de_valer(ana, app, rota):
    with app.app.app_context():
        with app.transaction() as db:
            db.execute("DELETE FROM usuarios WHERE id = ?", (ana.id,))

    resposta = ana.client.get(rota)

    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/login")
