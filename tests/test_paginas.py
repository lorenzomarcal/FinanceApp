"""Carregamento das páginas, login e proteção das rotas."""

import pytest

ROTAS_GET_PROTEGIDAS = ["/", "/investimentos", "/perfil"]
ROTAS_POST_PROTEGIDAS = [
    "/logout",
    "/perfil",
    "/adicionar",
    "/excluir/1",
    "/cofrinho",
    "/retirar_cofrinho",
    "/investimentos/adicionar",
    "/investimentos/comprar",
    "/investimentos/vender",
    "/investimentos/excluir/1",
]


# ---------------------------------------------------------
# Sem login
# ---------------------------------------------------------

@pytest.mark.parametrize("rota", ["/login", "/cadastro"])
def test_paginas_publicas_carregam(visitante, rota):
    assert visitante.get(rota).status_code == 200


@pytest.mark.parametrize("rota", ["/static/css/style.css", "/static/js/script.js"])
def test_arquivos_estaticos_carregam(visitante, rota):
    assert visitante.get(rota).status_code == 200


@pytest.mark.parametrize("rota", ROTAS_GET_PROTEGIDAS)
def test_paginas_protegidas_mandam_para_o_login(visitante, rota):
    resposta = visitante.get(rota)

    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/login")


@pytest.mark.parametrize("rota", ROTAS_POST_PROTEGIDAS)
def test_acoes_protegidas_mandam_para_o_login(visitante, consultar, rota):
    resposta = visitante.post(rota, data={"valor": "10,00", "ticker": "PETR4", "quantidade": "1"})

    assert resposta.status_code == 302
    assert resposta.headers["Location"].endswith("/login")
    assert consultar("SELECT id FROM movimentacoes_usuario") == []


def test_pagina_inexistente_mostra_o_404(visitante):
    assert visitante.get("/nao-existe").status_code == 404


@pytest.mark.parametrize("rota", ["/logout", "/adicionar", "/cofrinho", "/investimentos/vender"])
def test_acoes_nao_aceitam_get(ana, rota):
    assert ana.client.get(rota).status_code == 405


# ---------------------------------------------------------
# Com login
# ---------------------------------------------------------

@pytest.mark.parametrize("rota", ROTAS_GET_PROTEGIDAS)
def test_paginas_carregam_com_a_conta_vazia(ana, rota):
    assert ana.client.get(rota).status_code == 200


def test_paginas_carregam_com_dados(ana, brapi):
    brapi.definir("PETR4", 56.00)
    brapi.definir("MXRF11", 10.00)
    ana.ganho("5.000,00", "Salário de outubro")
    ana.gasto("1.234,56", "Aluguel")
    ana.guardar("500,00")
    ana.comprar("PETR4", "5")
    ana.comprar("MXRF11", "10", tipo="fii")

    painel = ana.client.get("/").get_data(as_text=True)
    carteira = ana.client.get("/investimentos").get_data(as_text=True)

    assert "Salário de outubro" in painel
    assert "1.234,56" in painel
    assert "Compra PETR4" in painel
    assert "PETR4" in carteira
    assert "MXRF11" in carteira
    assert "56,00" in carteira


@pytest.mark.parametrize("consulta", ["?tipo=acoes", "?tipo=fiis", "?tipo=invalido", "?pesquisa=petro"])
def test_pesquisa_de_mercado_carrega(ana, brapi, consulta):
    brapi.mercado = [
        {"stock": "PETR4", "name": "Petrobras", "close": 56.0},
        {"stock": "VALE3", "name": "Vale", "close": 70.5},
    ]

    pagina = ana.investimentos(consulta)

    assert [ativo["stock"] for ativo in pagina["mercado"]] == ["PETR4", "VALE3"]
    assert pagina["tipo"] == ("fiis" if "fiis" in consulta else "acoes")


def test_pesquisa_de_mercado_carrega_com_a_brapi_fora_do_ar(ana, brapi):
    brapi.fora_do_ar = True

    assert ana.investimentos("?pesquisa=petro")["mercado"] == []


def test_pagina_de_investimentos_carrega_sem_token_da_brapi(ana, brapi, app, monkeypatch):
    monkeypatch.setitem(app.app.config, "BRAPI_TOKEN", "")

    pagina = ana.investimentos()

    assert pagina["api_configurada"] is False
    assert brapi.chamadas == []


def test_usuario_logado_nao_ve_login_nem_cadastro(ana):
    for rota in ("/login", "/cadastro"):
        resposta = ana.client.get(rota)
        assert resposta.status_code == 302
        assert resposta.headers["Location"].endswith("/")


# ---------------------------------------------------------
# Conta
# ---------------------------------------------------------

def test_cadastro_grava_so_o_hash_da_senha(ana, consultar):
    usuario = consultar("SELECT nome, senha_hash FROM usuarios")[0]

    assert usuario["nome"] == "ana"
    assert ana.SENHA not in usuario["senha_hash"]


@pytest.mark.parametrize(
    "dados, aviso",
    [
        ({"nome": "ab"}, "pelo menos 3 caracteres"),
        ({"nome": "a" * 31}, "no máximo 30 caracteres"),
        ({"nome": "nome com espaço"}, "Use apenas letras"),
        ({"senha": "curta12", "confirmar_senha": "curta12"}, "pelo menos 8 caracteres"),
        ({"confirmar_senha": "diferente-123"}, "As senhas não coincidem."),
    ],
)
def test_cadastro_recusa_dados_invalidos(visitante, consultar, dados, aviso):
    campos = {"nome": "carla", "senha": "senha-segura-123", "confirmar_senha": "senha-segura-123"}
    campos.update(dados)

    resposta = visitante.post("/cadastro", data=campos)

    assert aviso in resposta.get_data(as_text=True)
    assert consultar("SELECT id FROM usuarios") == []


@pytest.mark.parametrize(
    "nome, senha", [("ana", "senha-errada-123"), ("ninguem", "senha-segura-123"), ("", "")]
)
def test_login_recusa_usuario_ou_senha_incorretos(ana, visitante, nome, senha):
    resposta = visitante.post("/login", data={"nome": nome, "senha": senha})

    assert "Usuário ou senha incorretos." in resposta.get_data(as_text=True)
    assert visitante.get("/").status_code == 302


def test_login_aceita_o_nome_em_maiusculas(ana, visitante):
    visitante.post("/login", data={"nome": "ANA", "senha": ana.SENHA})

    assert visitante.get("/").status_code == 200


def test_logout_encerra_a_sessao(ana):
    ana.client.post("/logout")

    assert ana.client.get("/").status_code == 302


def test_trocar_a_senha_exige_a_senha_atual(ana, visitante):
    nova = "nova-senha-456"

    recusada = ana.client.post(
        "/perfil",
        data={"acao": "alterar_senha", "senha_atual": "errada", "nova_senha": nova, "confirmar_senha": nova},
        follow_redirects=True,
    )
    aceita = ana.client.post(
        "/perfil",
        data={"acao": "alterar_senha", "senha_atual": ana.SENHA, "nova_senha": nova, "confirmar_senha": nova},
        follow_redirects=True,
    )

    assert "A senha atual está incorreta." in recusada.get_data(as_text=True)
    assert "Senha alterada com sucesso." in aceita.get_data(as_text=True)
    assert visitante.post("/login", data={"nome": "ana", "senha": nova}).status_code == 302


def test_trocar_o_nome_de_usuario(ana, consultar):
    resposta = ana.client.post(
        "/perfil", data={"acao": "alterar_nome", "novo_nome": "ana.maria"}, follow_redirects=True
    )

    assert "Nome de usuário alterado com sucesso." in resposta.get_data(as_text=True)
    assert consultar("SELECT nome FROM usuarios")[0]["nome"] == "ana.maria"
