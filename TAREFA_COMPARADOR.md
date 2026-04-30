# TAREFA: Instalar módulo Comparador de Orçamento

## Contexto
Projeto: robo_gamatec_oc (Plataforma Vortex)
Raiz: C:\robo_gamatec_oc
Os arquivos do módulo já estão na raiz do projeto.

## Arquivos disponíveis na raiz
- C:\robo_gamatec_oc\extrator_orcamento_gamatec.py
- C:\robo_gamatec_oc\comparador_oc_orcamento.py
- C:\robo_gamatec_oc\comparador_bp.py
- C:\robo_gamatec_oc\templates\comparador\upload.html
- C:\robo_gamatec_oc\templates\comparador\resultado.html

## Tarefas a executar

### 1. Mover arquivos para destinos corretos

```
copy C:\robo_gamatec_oc\extrator_orcamento_gamatec.py C:\robo_gamatec_oc\web\
copy C:\robo_gamatec_oc\comparador_oc_orcamento.py C:\robo_gamatec_oc\web\
copy C:\robo_gamatec_oc\comparador_bp.py C:\robo_gamatec_oc\web\
mkdir C:\robo_gamatec_oc\web\templates\comparador
copy C:\robo_gamatec_oc\templates\comparador\upload.html C:\robo_gamatec_oc\web\templates\comparador\
copy C:\robo_gamatec_oc\templates\comparador\resultado.html C:\robo_gamatec_oc\web\templates\comparador\
```

### 2. Editar app_web.py

Arquivo: C:\robo_gamatec_oc\web\app_web.py

Localizar o bloco do catalogo_steck que se parece com isso:
```python
try:
    from catalogo_steck import catalogo_bp, init_catalogo
    init_catalogo(app)
    app.register_blueprint(catalogo_bp)
    print("[CATALOGO STECK] Módulo carregado — /catalogo/steck/")
except ImportError:
    print("[CATALOGO STECK] catalogo_steck.py não encontrado — módulo desativado")
```

Adicionar DEPOIS desse bloco:
```python
try:
    from comparador_bp import comparador_bp
    app.register_blueprint(comparador_bp)
    print("[COMPARADOR] Módulo carregado — /comparador/")
except ImportError:
    print("[COMPARADOR] comparador_bp.py não encontrado — módulo desativado")
```

### 3. Editar dashboard.html

Arquivo: C:\robo_gamatec_oc\web\templates\dashboard.html

Localizar o bloco de botões de ação de cada OC processada.
Procurar por texto como "Automação GAMATEC" ou "download" ou "planilha".
Adicionar botão de comparar orçamento junto aos outros botões:

```html
<a href="/comparador/{{ oc.nome_base }}" 
   class="btn-action" 
   title="Comparar com orçamento Gamatec e calcular descontos">
  📊 Comparar Orçamento
</a>
```

Atenção: usar a mesma variável que os outros botões usam para identificar a OC.
Só adicionar o botão onde as OCs já estão processadas (status OK/processado).

### 4. Commit e push

```
cd C:\robo_gamatec_oc
git add web/extrator_orcamento_gamatec.py web/comparador_oc_orcamento.py web/comparador_bp.py web/templates/comparador/ web/app_web.py web/templates/dashboard.html
git commit -m "comparador: modulo de comparacao oc vs orcamento gamatec"
git push
```

### 5. Verificar

Reiniciar o servidor e confirmar que aparece no log:
```
[COMPARADOR] Módulo carregado — /comparador/
```

Testar acessando: http://localhost:5000/comparador/NOME_DE_UMA_OC_PROCESSADA
