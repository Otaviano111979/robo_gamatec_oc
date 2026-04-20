# 🤖 VORTEX — robo_gamatec_oc

Sistema de processamento automático de Ordens de Compra (OC) em PDF com interface web, módulo de automação RPA para o sistema EVOL GAMATEC, e plataforma multi-empresa Vortex.

---

## 📋 O que o sistema faz

```
PDF da OC (MRV / Krona / UAU / SIENGE)
        ↓
Extração dos itens
        ↓
Match com catálogo Krona  →  prioridade: regra aprendida → histórico → lookup → fuzzy → IA
        ↓
Geração de planilha XLSX
        ↓
Dashboard web de controle
        ↓
Automação RPA na tela "Recálculo de Mix" do GAMATEC
```

---

## 🧩 Módulos Vortex

| Módulo | Status | URL |
|---|---|---|
| Pedidos / OC | ✅ ativo | `/dashboard` |
| Agente de Email | ✅ ativo | `/painel` |
| Catálogo Elétrico (Steck/Schneider) | ✅ ativo | `/catalogo/steck/` |
| CRM | 🔜 em breve | — |
| Financeiro | 🔜 em breve | — |
| Inteligência | 🔜 em breve | — |

---

## ⚙️ Instalação

**1. Clonar:**
```bash
git clone https://github.com/Otaviano111979/robo_gamatec_oc.git
cd robo_gamatec_oc
```

**2. Instalar dependências:**
```bash
pip install -r requirements.txt
```

**3. Criar `.env`:**
```
GAMATEC_SECRET_KEY=gere_com_python_-c_"import secrets; print(secrets.token_hex(32))"
GAMATEC_BASE_DIR=C:\robo_gamatec_oc
```

**4. Rodar:**
```bash
python web/app_web.py
```
Acesse **http://localhost:5000** — login padrão: `admin` / `admin123`

---

## 🗂️ Estrutura do projeto

```
C:\robo_gamatec_oc\
├── web\
│   ├── app_web.py                  ← servidor Flask principal
│   ├── catalogo_steck.py           ← Blueprint catálogo Steck/Schneider
│   ├── importar_steck.py           ← importa xlsx do catálogo Steck
│   ├── templates\
│   │   ├── launcher.html
│   │   ├── dashboard.html
│   │   └── steck\                  ← templates do catálogo elétrico
│   └── static\
│       └── steck\                  ← CSS tema Vortex (steck.css)
├── empresas\
│   └── une\
│       └── config.json             ← módulos ativos por empresa
├── instance\
│   ├── catalogo_steck.db           ← banco SQLite do catálogo elétrico
│   └── catalogo_steck_raw.xlsx     ← xlsx original para importação
├── matcher.py
├── launcher.py
└── ...
```

---

## 📦 Formatos de OC suportados

| Formato | Detecção |
|---|---|
| MRV | Automática |
| Krona / L2M | Automática |
| UAU (City, UNE) | Automática |
| SIENGE (EBM) | Automática |

---

## 🤖 Automação GAMATEC

**Primeira vez — calibrar coordenadas da tela:**
```bash
python calibrar_gamatec.py
```

**Uso diário:**
1. Processe a OC pelo dashboard
2. Abra o GAMATEC na tela **Recálculo de Mix**
3. Clique **•••** → **🤖 Automação GAMATEC** → **▶ Iniciar**

---

## 🔄 Padrão de versionamento Git

**Regra do projeto: todo arquivo alterado recebe um commit.**

```bash
cd C:\robo_gamatec_oc
git add <arquivo(s)>
git commit -m "<escopo>: <descrição curta no infinitivo>"
git push
```

### Exemplos de commits por escopo:

| Escopo | Exemplo |
|---|---|
| `une` | `une: adicionar modulo steck ao config da empresa` |
| `launcher` | `launcher: adicionar card catalogo eletrico steck` |
| `steck` | `steck: blueprint flask integrado ao vortex` |
| `matcher` | `matcher: corrigir prioridade regra aprendida` |
| `fix` | `fix: corrigir nome UNE Representacoes` |
| `semana N` | `semana 3: aprendizado - correcoes viram regras automaticas` |

### Commits frequentes — nunca acumule:
```bash
# ✅ certo — commit por mudança
git add empresas\une\config.json
git commit -m "une: adicionar modulo steck"

# ❌ errado — acumular tudo num commit só
git add .
git commit -m "varias mudancas"
```

---

## 🧠 Prioridades do matcher de OC

```
0A → Regra aprendida (JSON, instantâneo)
0  → Histórico banco (SQLite, similaridade ≥ 92%)
1  → MRV / Brasal (código direto)
2  → Lookup direto (JUNCAO, TE, JOELHO...)
3  → Rapidfuzz (fuzzy match)
IA → Claude API (último recurso)
```

---

## 🚀 Prompt de retomada

> Estou retomando o desenvolvimento do **robo_gamatec_oc** (Plataforma Vortex).
> GitHub: https://github.com/Otaviano111979/robo_gamatec_oc
> Stack: Python, Flask, pdfplumber, rapidfuzz, bcrypt, pyautogui, pytesseract, pandas
> Envio o zip atualizado ou arquivo específico. Preciso de ajuda com: [DESCREVA AQUI]
