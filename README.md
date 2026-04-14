# 🤖 AGENTE EXTRACT — robo_gamatec_oc

Sistema de processamento automático de Ordens de Compra (OC) em PDF com interface web e módulo de automação RPA para o sistema EVOL GAMATEC.

---

## 📋 O que o sistema faz

```
PDF da OC (MRV ou Krona)
        ↓
Extração dos itens
        ↓
Match com catálogo Krona
        ↓
Geração de planilha XLSX
        ↓
Dashboard web de controle
        ↓
Automação RPA na tela "Recálculo de Mix" do GAMATEC
```

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

## 📦 Formatos suportados

| Formato | Detecção |
|---|---|
| MRV | Automática |
| Krona / L2M | Automática |

---

## 🔄 Versionamento

```bash
git add .
git commit -m "descricao"
git push
```

---

## 🚀 Prompt de retomada

> Estou retomando o desenvolvimento do **robo_gamatec_oc**.
> GitHub: https://github.com/Otaviano111979/robo_gamatec_oc
> Stack: Python, Flask, pdfplumber, rapidfuzz, bcrypt, pyautogui, pytesseract, pandas
> Envio o zip atualizado. Preciso de ajuda com: [DESCREVA AQUI]
