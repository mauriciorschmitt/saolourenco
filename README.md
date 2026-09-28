# Monitoramento multiparamétrico da Represa São Lourenço

Sistema automatizado de acompanhamento remoto da qualidade da água e da
cobertura vegetal da Represa São Lourenço, em Mafra (SC), a partir de
imagens Sentinel-2. Roda inteiramente em infraestrutura gratuita.

Sucede o sistema de monitoramento de macrófitas, ampliando o escopo de um
índice para sete, de uma média para setores, e de valores abstratos para
área em hectares.

---

## O que mudou em relação ao sistema anterior

**De um índice para sete.** Além do NDVI, o sistema calcula FAI (algas
flutuantes), NDCI (clorofila relativa), NDTI (turbidez relativa), NDWI
(extensão da água), NDMI (umidade) e um proxy de matéria orgânica
dissolvida.

**De média para área.** Em vez de apenas promediar índices sobre o
reservatório, o sistema classifica pixel a pixel e conta. A saída deixa de
ser "o NDVI subiu 0,08" e passa a ser "12,4 ha com cobertura flutuante".
Isso é diretamente utilizável por quem gere a represa.

**De um polígono para setores.** Uma anomalia que aparece em um setor e não
nos demais é muito mais informativa que uma anomalia na média. O sistema
suporta setores independentes e séries de **contraste** entre pares deles —
a diferença cancela sazonalidade, atmosfera e variação de nível, isolando o
que é local.

**Climatologia protegida.** A referência estatística é calculada apenas
sobre observações de alta confiança e exclui deliberadamente períodos de
evento conhecido. Cenas parcialmente encobertas não deslocam mais a régua.

**Alerta com persistência.** Exige ultrapassagem do limiar em duas
observações qualificadas consecutivas. Pico de cena única é assinatura de
nuvem residual, não de alteração ambiental.

---

## Índices

| Índice | Bandas | O que acompanha |
|---|---|---|
| NDVI | B08, B04 | Vegetação fotossintética sobre a água |
| FAI | B08, B04, B11 | Algas e vegetação flutuante; robusto a aerossol |
| NDCI | B05, B04 | Clorofila relativa — red-edge, eutrofização |
| NDTI | B04, B03 | Turbidez relativa — sedimento em suspensão |
| NDWI | B03, B08 | Delimitação da lâmina d'água |
| NDMI | B08, B11 | Umidade; separa vegetação de substrato exposto |
| CDOM (proxy) | B03, B04 | Matéria orgânica dissolvida — exploratório |

O FAI subtrai uma linha de base traçada entre o vermelho e o SWIR, o que o
torna menos sensível a variação atmosférica que o NDVI — vantagem
relevante numa série de dez anos.

## Como a área é calculada

O evalscript devolve, além dos índices contínuos, **máscaras binárias**: 1
se o pixel cruza um limiar, 0 caso contrário. A média de uma máscara
binária é a fração de pixels válidos que cruzam o limiar; multiplicada pela
área do pixel, vira hectares.

O cálculo acontece no servidor do Sentinel Hub. A API devolve estatísticas
agregadas, nunca a imagem — é isso que mantém o consumo dentro da camada
gratuita.

---

## Limitações — leia antes de usar

**Estes índices são relativos, não concentrações.** Sem amostragem de campo
para calibração, o sistema produz anomalia frente ao histórico. Não escreva
µg/L de clorofila nem NTU de turbidez a partir destes dados.

**A correção atmosférica não é específica para água.** O produto L2A é
destinado a superfícies terrestres e, sobre água escura, frequentemente
produz reflectância negativa no azul e no verde. Índices normalizados como
o NDVI toleram isso; NDCI e NDTI, que dependem mais de valores absolutos,
sofrem mais. Correção específica (ACOLITE, C2RCC) é o próximo passo
técnico previsto.

**O sistema não identifica origem.** Ele detecta alteração espectral na
superfície da água. Não distingue lançamento de efluente de escoamento
agrícola, de revolvimento de sedimento por chuva ou de floração sazonal.
Uma pluma de anomalia a jusante de um ponto suspeito é indício técnico
que justifica investigação — não é prova de origem, e apresentá-la como
tal enfraquece qualquer encaminhamento formal.

**O proxy de CDOM é exploratório.** Em água interior o sinal se confunde
com clorofila e sedimento. Está configurado para acompanhamento, não para
alerta.

**Pixels mistos.** O reservatório tem perímetro 4,6 vezes maior que o de um
círculo de área equivalente. Cerca de 16% dos pixels contêm simultaneamente
água e margem, e vegetação ripária influencia o valor agregado mesmo sem
alteração na lâmina d'água.

---

## Estrutura

```
.
├── config.yaml                 # setores, índices, limiares — toda a parametrização
├── requirements.txt
├── data/setores/
│   └── represa.geojson         # polígono do reservatório (502 vértices, 79,49 ha)
├── src/
│   ├── evalscripts.py          # gera o evalscript com índices e máscaras
│   ├── sentinelhub.py          # autenticação OAuth e Statistical API
│   ├── analise.py              # climatologia, z-score, persistência, contrastes
│   └── monitor.py              # orquestração
├── docs/data/                  # séries publicadas (um CSV por setor)
└── .github/workflows/
    ├── monitor.yml             # agendado: segundas e quintas
    └── serie_historica.yml     # manual: reconstrói desde 2016
```

O código em `src/` é genérico. Para monitorar outro corpo d'água, troque os
polígonos e os limiares em `config.yaml` — sem tocar em Python.

## Configuração

Crie uma conta gratuita no
[Copernicus Data Space Ecosystem](https://dataspace.copernicus.eu/), gere
um cliente OAuth em *Settings → OAuth clients* e registre as credenciais em
*Settings → Secrets and variables → Actions* do repositório:

| Secret | Obrigatório | Uso |
|---|---|---|
| `SH_CLIENT_ID` | sim | Autenticação Sentinel Hub |
| `SH_CLIENT_SECRET` | sim | Autenticação Sentinel Hub |
| `TELEGRAM_BOT_TOKEN` | não | Notificação de falha |
| `TELEGRAM_CHAT_ID` | não | Destinatários |

A camada gratuita tem cota mensal de unidades de processamento. Como o
sistema pede estatísticas agregadas sobre polígonos pequenos, o consumo
cresce com o número de setores × execuções, não com o tamanho da série.
Reconstruir dez anos custa uma fração da cota mensal, mas confira os
limites vigentes antes de configurar muitos setores.

## Execução

```bash
pip install -r requirements.txt
export SH_CLIENT_ID=...  SH_CLIENT_SECRET=...

python -m src.monitor                      # janela padrão de 30 dias
python -m src.monitor --desde 2016-07-19   # série completa
python -m src.monitor --setor jusante      # apenas um setor
```

Pelo navegador, sem instalar nada: aba **Actions** → *Construir série
histórica* → **Run workflow**.

## Adicionar um setor

1. Desenhe o polígono no Google Earth e exporte como KML;
2. Converta para GeoJSON (geojson.io abre KML e exporta GeoJSON);
3. Salve em `data/setores/<id>.geojson`;
4. Acrescente a entrada em `config.yaml`, seção `setores`;
5. Para acompanhar o contraste com outro setor, acrescente também em
   `contrastes`;
6. Rode *Construir série histórica* para preencher o passado do setor novo.

---

## Evolução prevista

- Correção atmosférica específica para água (ACOLITE)
- Sentinel-1 (radar) para as janelas em que a nuvem impede observação ótica
- Banda termal do Landsat 8/9 para anomalias de temperatura
- Armazenamento da reflectância por banda, permitindo calibração
  retroativa quando houver a primeira campanha de campo
- Saída espacial: mapa de cobertura, não apenas série temporal

## Autoria

**Maurício Rodrigo Schmitt**
Universidade do Contestado – UNC
Programa de Pós-Graduação em Engenharia Civil, Sanitária e Ambiental – PMPECSA
Grupo de Pesquisa CENAS (CNPq)

Dados Sentinel-2 do programa Copernicus, Agência Espacial Europeia.

## Licença

Em definição junto à Universidade do Contestado. Até que uma licença seja
adotada, o código permanece sob reserva integral de direitos.
