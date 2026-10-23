# Política Tarifária ChargeGrid · Piloto Comercial

**Documento do projeto** · Grupo 2 · Turma 1CCR · FIAP × GoodWe EV Challenge 2026 · Vigência: outubro de 2026

Esta política define os preços praticados pelo operador comercial do piloto. Os valores são parâmetros de negócio do projeto e podem ser alterados pelo operador no painel. Eles não são tarifas reguladas pela distribuidora.

## 1. Tarifa por tipo de conector

| Tipo de recarga | Faixa de potência do conector | Tarifa base (R$/kWh) |
|---|---|---|
| AC lenta | até 7,4 kW | 1,90 |
| AC semirrápida | de 7,4 kW até 22 kW | 2,20 |
| DC rápida (DC Fast) | acima de 22 kW | 3,30 |

## 2. Faixas horárias

| Faixa | Horário (dias úteis) | Multiplicador sobre a tarifa base |
|---|---|---|
| Fora de ponta | 21h às 18h do dia seguinte | 1,00 |
| Ponta | 18h às 21h | 1,30 |
| Fim de semana e feriados | dia inteiro | 1,00 |

Exemplo: recarga AC semirrápida às 19h de uma terça-feira custa R$ 2,20 × 1,30 = R$ 2,86 por kWh.

A faixa de ponta do piloto coincide com o horário de ponta da distribuidora no posto tarifário do estabelecimento. Quando a distribuidora alterar o seu horário de ponta, a política deve ser atualizada para acompanhá-lo.

## 3. Taxa de ociosidade

Após o fim da recarga (veículo deixa de receber energia ou StopTransaction com veículo ainda conectado), há tolerância de 10 minutos. A partir do 11º minuto cobra-se R$ 1,00 por minuto, limitada a R$ 60,00 por sessão. O objetivo é liberar o conector, não gerar receita.

## 4. Ajuste dinâmico por ocupação

Quando mais de 80% dos conectores do estabelecimento estiverem ocupados, a tarifa base pode ser elevada em até 15%, com aviso prévio no aplicativo antes da autorização da sessão. O preço aplicado é o vigente no momento do StartTransaction e não muda durante a sessão.

## 5. Formas de pagamento

Pix (QR Code dinâmico exibido no app ou no totem), cartão de crédito pré-autorizado no aplicativo e faturamento mensal para frotas cadastradas. Pré-autorização padrão: R$ 80,00, estornada a diferença em até 2 dias úteis.

## 6. Composição de custo (referência para o operador)

O custo da energia para o estabelecimento é dado pela fatura da distribuidora (tarifas de energia e de demanda do seu grupo e modalidade tarifária, mais tributos). O operador deve conferir as tarifas homologadas da sua distribuidora, que estão em resolução homologatória da ANEEL, antes de definir a margem. Esta política não substitui análise contábil ou tributária, que deve ser feita por contador habilitado.

## 7. Comprovante ao cliente

Todo comprovante informa: ID da transação, conector, início e fim, energia em kWh, tarifa aplicada, multiplicador de faixa, taxa de ociosidade e valor total.
