# 🖥️ GUIA DE INSTALAÇÃO — Máquina do GAMATEC

Este guia instala o sistema **AGENTE EXTRACT** na máquina onde o GAMATEC está instalado.

---

## ✅ PRÉ-REQUISITOS

Antes de começar, instale:

### 1. Python 3.10 ou superior
- Acesse: https://www.python.org/downloads/
- Baixe a versão mais recente
- **IMPORTANTE:** Na tela de instalação, marque a opção **"Add Python to PATH"**
- Clique em **Install Now**

Verifique se instalou corretamente:
```
python --version
```
Deve aparecer algo como: `Python 3.12.0`

---

### 2. Git
- Acesse: https://git-scm.com/download/win
- Baixe e instale com todas as opções padrão

Verifique:
```
git --version
```

---

### 3. Tesseract OCR (necessário para a automação)
- Acesse: https://github.com/UB-Mannheim/tesseract/wiki
- Baixe o instalador Windows (tesseract-ocr-w64-setup-xx.exe)
- Instale no caminho padrão: `C:\Program Files\Tesseract-OCR`
- **IMPORTANTE:** Durante a instalação, marque **"Add to PATH"**

Verifique:
```
tesseract --version
```

---

## 📥 INSTALAÇÃO DO SISTEMA

Abra o **CMD** (tecla Windows + R → digite `cmd` → Enter)

### 1. Ir para o disco C:
```
cd C:\
```

### 2. Clonar o projeto do GitHub
```
git clone https://github.com/Otaviano111979/robo_gamatec_oc.git
```

### 3. Entrar na pasta do projeto
```
cd robo_gamatec_oc
```

### 4. Instalar as dependências Python
```
pip install -r requirements.txt
```
Aguarde terminar — pode demorar alguns minutos.

---

## ⚙️ CONFIGURAR O ARQUIVO .ENV

O arquivo `.env` guarda informações sensíveis do sistema (chave de segurança).
**Ele nunca vai para o GitHub** e é criado automaticamente no primeiro arranque
pelo `rodar_gamatec.bat`. Só precisa de mexer nele se quiser definir a chave à mão.

### 1. Gerar a chave de segurança

No CMD, dentro da pasta do projeto, execute:
```
python -c "import secrets; print(secrets.token_hex(32))"
```

Vai aparecer uma sequência de letras e números, por exemplo:
```
a3f8c2e1b7d94f05e6a1c3b2d8f74e90a1b2c3d4e5f67890abcdef1234567890
```

**Copie esse valor** — você vai usar no próximo passo.

### 2. Criar o arquivo .env (opcional)

O sistema funciona sem `.env`: o `rodar_gamatec.bat` cria um automaticamente
no primeiro arranque, já com a chave de sessão gerada. Se preferir fazer à mão:
```
copy .env.example .env
```

### 3. Editar o arquivo .env (só se criou à mão)

Abra o arquivo com o Bloco de Notas:
```
notepad .env
```

**Substitua** `coloque_aqui_uma_chave_longa_e_aleatoria` pela chave que você gerou no passo anterior.

A linha `GAMATEC_BASE_DIR` **não precisa existir** — o sistema usa a pasta onde
está instalado. Deixe-a comentada (com `#` à frente).

**Salve o arquivo** (Ctrl+S) e feche o Bloco de Notas.

---

## ▶️ RODAR O SISTEMA

**Duplo clique em `rodar_gamatec.bat`** — funciona em qualquer pasta onde o
sistema esteja instalado. O atalho faz tudo: atualiza, abre o navegador e sobe
o servidor.

Se preferir pelo CMD, dentro da pasta do sistema:
```
python iniciar_sistema.py
```

Deve aparecer:
```
[INIT] ...
 * Running on http://0.0.0.0:5000
```

### Acessar a pagina de OCs

- **Nesta máquina:** http://localhost:5000
- **De outra máquina na rede:** http://IP_DESTA_MAQUINA:5000

Para saber o IP desta máquina:
```
ipconfig
```
Procure por **Endereço IPv4** — ex: `192.168.1.105`

### Login padrão
```
Usuário: admin
Senha: admin123
```
**Troque a senha após o primeiro acesso** em Admin Usuários.

---

## 🎯 CALIBRAÇÃO (PRIMEIRA VEZ)

A calibração é feita uma única vez para ensinar o robô onde estão os campos na tela do GAMATEC.

1. Abra o GAMATEC na tela **Itens com Mix**
2. Acesse a pagina de OCs no navegador
3. Clique em **•••** em qualquer OC processada
4. Clique em **🤖 Automação GAMATEC**
5. Clique em **🎯 Calibrar agora**
6. Siga as instruções — para cada ponto:
   - Clique **🎯 Capturar**
   - Você terá **5 segundos** para ir ao GAMATEC e posicionar o mouse
   - O sistema captura automaticamente

Após os 7 pontos, a calibração fica salva em `saida/calibracao_gamatec.json`.

---

## 🔄 MANTER O SISTEMA ATUALIZADO

Sempre que houver atualizações, dentro de `C:\robo_gamatec_oc`:
```
git pull
```

Isso baixa as últimas correções do GitHub automaticamente.

---

## ❓ PROBLEMAS COMUNS

**`python` não reconhecido:**
Reinstale o Python marcando **"Add Python to PATH"**

**`git` não reconhecido:**
Feche e reabra o CMD após instalar o Git

**`tesseract` não reconhecido:**
Reinstale o Tesseract marcando **"Add to PATH"**

**Porta 5000 ocupada:**
Algum outro programa está usando a porta. Tente:
```
python web/app_web.py
```
Se der erro, reinicie o computador e tente novamente.

**Erro ao importar módulos:**
```
pip install -r requirements.txt --force-reinstall
```

---

## 📞 SUPORTE

Para retomar o desenvolvimento ou resolver problemas, use o prompt:

> Estou retomando o desenvolvimento do **robo_gamatec_oc**.
> GitHub: https://github.com/Otaviano111979/robo_gamatec_oc
> Stack: Python, Flask, pdfplumber, rapidfuzz, bcrypt, pyautogui, pytesseract, pandas
> Envio o zip atualizado. Preciso de ajuda com: [DESCREVA AQUI]
